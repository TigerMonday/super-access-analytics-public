"""成果物（Markdown・HTML原稿）中の数値を `_data/` の実データと突合する。

レポート中の数値を手で `_data/` と突き合わせる作業を機械化する。あわせて、
テンプレート由来で他クライアント名が成果物に残る事故も検出する。

判定方針は「近いが一致しない値」を拾うこと。行に含まれる無関係な数値（日付・
パーセント・IDなど）で誤検知しないよう、真値と同じ桁で±25%以内に入る数値だけを
比較対象とし、そこに一致がなければ mismatch とする。

Usage:
    python run.py verify --client <client_id>
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import AuditConfig, PROJECT_ROOT, REPO_ROOT

# 「1,162」「1162」形式の整数（小数・パーセントは別途扱う）
#
# **`#` に続く数字は参照番号なので数えない。** GTM のタグ番号（`#135`）やイシュー番号は
# 計測値ではない。イベント名の近くに書くと発火数と読み違えられる
# （`来場予約` の説明に「GA4イベントタグ（#135）」と書いて不一致になった）。
NUMBER_RE = re.compile(r"(?<![\d.,#])(\d{1,3}(?:,\d{3})+|\d+)(?![\d,]*\s*%)(?![.\d])")
# イベント名の目印。Markdown はバッククォート、scroll_deck の原稿（HTML）は <code>。
# **両方見る。** 片方だけだと、HTML の原稿では名前が1つも拾えず「0件で合格」になる。
#
# **英数字に限定しない。** GA4 のイベント名は日本語や記号でも通ってしまう
# （`資料請求` `来場予約` `10%` は実在する。GTM がスクロール率をそのまま名前にした例）。
# 以前は `[A-Za-z_][A-Za-z0-9_]*` に限っていたため、**日本語名のキーイベントは
# 1件も突合されていなかった**。囲みの中身をそのまま拾い、実データのイベント名と
# 完全一致するものだけを対象にする（一致しない `/request/complete` 等は自然に外れる）。
BACKTICK_RE = re.compile(r"`([^`\n]+)`|<code>([^<\n]+)</code>")


@dataclass
class Finding:
    severity: str  # "mismatch" | "warn"
    file: str
    line_no: int
    label: str
    expected: str
    found: str
    excerpt: str


def _load(data_dir: Path, name: str) -> dict | None:
    """観点別データセットを読む（旧 phase*.json にもフォールバックする）。"""
    import dataset

    return dataset.load(data_dir, name) or None


def _num(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _numbers_in(line: str, *, after: int = 0, window: int | None = None) -> list[int]:
    """行内の整数を拾う。

    after / window を指定すると、`after` 以降かつ `after + window` 以内に現れるものだけを返す。
    1行に複数の指標が並ぶ散文（「約11,800セッションが集中し …『hp_reserve_form』が 312→1,214」）で、
    遠くの無関係な数値を対象名に結びつけないための近接判定に使う。
    """
    out = []
    for m in NUMBER_RE.finditer(line):
        if m.start() < after:
            continue
        if window is not None and m.start() > after + window:
            continue
        try:
            out.append(int(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


# 対象名の直後どれだけの範囲を「その名前についての数値」とみなすか
PROXIMITY_CHARS = 60


def _comparable(found: int, truth: int) -> bool:
    """真値と「同じことを指していそうな」数値か。桁が同じで ±25% 以内。"""
    if truth == 0 or found == 0:
        return False
    if len(str(found)) != len(str(truth)):
        return False
    return abs(found - truth) / truth <= 0.25


# 「部分集合を語っている」手がかり。**2種類に分けてある。**
#   PATH: URLパスが書かれている（ページ別の内訳らしい）
#   WORD: 「うち」「内訳」など、語で内訳だと分かる
# `<code>/request/complete</code>` のように直前が `>` の形もある（HTML の本文）
PATH_SCOPED_RE = re.compile(r"(?:^|[\s|（(`>])/[A-Za-z0-9_\-./*]+")
WORD_SCOPED_RE = re.compile(r"うち|内訳|のみ|除く|別の内訳")


def _is_scoped(line: str, *, use_path_hint: bool = True) -> bool:
    """行が全体ではなく部分集合を語っているか。

    「`cv_reserve`（`/reserve/thanks.php`）| 1,134」のようなページ別内訳は、
    全体の 1,162 と一致しなくて当然なので不一致にしない（真値を超える場合のみ誤り）。

    **HTML の表の行では URL を手がかりにしない**（`use_path_hint=False`）。
    表の1行には「イベント名・件数・条件のURL」が別のセルとして同居するのが普通で、
    URLがあるだけで内訳と見なすと、**古い小さな数値がそのまま通ってしまう**
    （`資料請求` 150件 ＋ `/request/complete` の行が、真値172に対して合格していた）。

    **ただし外すのは表の行だけ。** 本文（`<p>` など）に書いたページ別内訳
    （`cv_reserve`（`/reserve/thanks.php`）1,134件）は Markdown と同じく内訳として扱う。
    語による手がかりは HTML でも残す。
    """
    if WORD_SCOPED_RE.search(line):
        return True
    return bool(use_path_hint and PATH_SCOPED_RE.search(line))


def _is_breakdown(nums: list[int], truth: int) -> bool:
    """行が真値の内訳を並べているだけか。

    例: 「キーイベント合計: cv_reserve 1,162 / purchase 47」は 1,162 が真値 1,201 に
    近いため単純比較では不一致になるが、行内の数値の和が真値と一致するので誤りではない。
    """
    return truth != 0 and sum(nums) == truth


def _build_truth(data_dir: Path) -> tuple[dict[str, int], dict[str, int]]:
    """(イベント名→発火数, ラベル→件数) を作る。"""
    events: dict[str, int] = {}
    counts: dict[str, int] = {}

    prop = _load(data_dir, "property")
    defs = _load(data_dir, "custom_definitions")
    ev = _load(data_dir, "events")
    tr = _load(data_dir, "traffic")
    p3 = _load(data_dir, "gtm")
    p1 = {**(prop or {}), **(defs or {}),
          **({"key_events": ev["key_events"]} if ev and "key_events" in ev else {})} or None
    p2 = {**{k: v for k, v in (ev or {}).items() if k != "key_events"}, **(tr or {})} or None

    if p2:
        for e in p2.get("events_30d", []):
            events[e["eventName"]] = _num(e.get("eventCount"))
        for e in p2.get("key_event_firing", []):
            events[e["eventName"]] = _num(e.get("eventCount"))
        chan = p2.get("channel_performance", [])
        if chan:
            counts["セッション合計（チャネル別集計）"] = sum(_num(r.get("sessions")) for r in chan)
            counts["キーイベント合計（チャネル別集計）"] = sum(_num(r.get("keyEvents")) for r in chan)
    if p1:
        counts["キーイベント登録数"] = len(p1.get("key_events", []))
        counts["カスタムディメンション"] = len(p1.get("custom_dimensions", []))
        counts["オーディエンス"] = len(p1.get("audiences", []))
    if p3:
        counts["GTMタグ"] = len(p3.get("tags", []))
        counts["GTMトリガー"] = len(p3.get("triggers", []))
        counts["GTM変数"] = len(p3.get("variables", []))
    return events, counts


def _other_client_names() -> set[str]:
    """他案件のクライアント名（自案件以外）。成果物への混入検出に使う。

    案件の入力は `{measurement_design}/{client_id}/inputs/`、成果物は
    `outputs/{client_id}/02_measurement/`（docs/standard-run-order.md §4）に置く。
    どちらも見に行き、**数字だけの名前はクライアント名ではない**ので外す。外さないと、
    レポートが自分のプロパティIDに触れているだけで「他案件の固有名が混入」と
    誤検出する（実際の案件で1レポートあたり複数件出たことがある）。
    """
    names = set()
    outputs_root = REPO_ROOT / "outputs"
    if outputs_root.is_dir():
        for d in outputs_root.iterdir():
            if d.is_dir() and not d.name.startswith("_") and not d.name.isdigit():
                names.add(d.name)
    if PROJECT_ROOT.is_dir():
        for d in PROJECT_ROOT.iterdir():
            if d.is_dir() and not d.name.isdigit() and (d / "inputs").is_dir():
                names.add(d.name)
    return names


def _display_path(path: Path) -> str:
    """所見に載せるパス表記。リポジトリ相対にできればそうする（できなければ絶対パス）。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# 表のセル・行を含む行か（HTML の内訳判定に使う。表の条件セルと本文の内訳を分ける）
TABLE_LINE_RE = re.compile(r"<t[dhr]\b", re.I)
TR_OPEN_RE = re.compile(r"<tr\b", re.I)
TR_CLOSE_RE = re.compile(r"</tr\s*>", re.I)


def _blank_html_comments(text: str) -> str:
    """HTML のコメント（`<!-- ... -->`）を空にする。行数は変えない。

    **表示されないものを突合の対象にしない。** 原稿の冒頭にはビルド手順の覚書きを
    複数行のコメントで置く。行単位の走査では開始行しか飛ばせないため、
    そこに残った古いメモの数値で `verify` が落ちる（画面には出ないのに）。
    """
    out = []
    for chunk_no, chunk in enumerate(re.split(r"(<!--.*?-->)", text, flags=re.S)):
        if chunk_no % 2 == 1:  # 区切りに使ったコメント本体
            out.append("\n" * chunk.count("\n"))
        else:
            out.append(chunk)
    return "".join(out)


def _collapse_table_rows(text: str) -> str:
    """HTML の表の1行（`<tr>`〜`</tr>`）を1行に畳む。

    **近接判定は行単位なので、畳まないと表がまるごと素通りする。**
    セルを改行して書いた表では、`<code>event_name</code>` の行と件数の行が別になり、
    「名前と数値が同じ行にある」という条件に当たらない。実害は「verify が0件で合格するが
    何も比べていない」状態で、これは検査が無いより悪い。

    **行数は変えない。** 畳んだ内容は `<tr>` が始まった行に置き、続く行は空にする。
    所見に出す行番号がずれないようにするため。
    """
    lines = text.split("\n")
    out = list(lines)
    i = 0
    while i < len(lines):
        if TR_OPEN_RE.search(lines[i]) and not TR_CLOSE_RE.search(lines[i]):
            j = i + 1
            while j < len(lines) and not TR_CLOSE_RE.search(lines[j]):
                j += 1
            if j < len(lines):
                out[i] = " ".join(x.strip() for x in lines[i : j + 1])
                for k in range(i + 1, j + 1):
                    out[k] = ""
                i = j + 1
                continue
        i += 1
    return "\n".join(out)


def _iter_docs(config: AuditConfig):
    """突合対象の原稿を列挙する。

    docs/ の中間成果物に加え、納品レポートの原稿（report/）も対象にする。
    誤記は納品物側で見つかることが多いため、ここを外すと意味がない。
    テンプレートのひな型（*.example.md / *.template.md / *.reference.md）は
    ダミー値を含むので除外する。

    **HTML の原稿（`*.src.html`）も対象にする。** `*.md` だけを見ていると、
    HTML化した原稿で「verify は通ったが数値は誰も突合していない」状態になる。
    ビルド後の `*.html`（`*.src.html` 以外）は見ない（埋め込んだ CSS の数値を
    拾って誤検知する）。
    """
    seen: set[Path] = set()
    targets = [config.docs_dir, config.output_dir / "report"]
    for root in targets:
        if not root.is_dir():
            continue
        for pattern in ("*.md", "*.src.html"):
            for path in sorted(root.rglob(pattern)):
                if path in seen:
                    continue
                if any(
                    path.name.endswith(s)
                    for s in (
                        ".example.md",
                        ".template.md",
                        ".reference.md",
                        ".example.src.html",
                        ".template.src.html",
                    )
                ):
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if path.suffix.lower() == ".html":
                    text = _collapse_table_rows(_blank_html_comments(text))
                yield path, text


def _own_client_base_name(client_name: str) -> str:
    """混入検出の除外対象になる「自分自身」の名前を返す。

    client_name は "acme-123456789" のように末尾へ数字（プロパティID等）を
    付ける運用があるため、その数字サフィックスだけを落とす。
    `rsplit("-", 1)[0]` だと "my-site" のようにハイフンを含む client_id 自体を
    誤って "my" に切り落としてしまい、除外対象から漏れた "my-site" 自身を
    「他案件名の混入」として誤検知していた（実案件で発生したバグ）。
    数字サフィックスかどうかを判定してから切り落とす。
    """
    return re.sub(r"-\d+$", "", client_name)


def verify(config: AuditConfig) -> list[Finding]:
    data_dir = config.data_dir
    events, counts = _build_truth(data_dir)
    if not events and not counts:
        raise FileNotFoundError(
            f"突合に使える実データがありません: {data_dir}\n先に fetch を実行してください。"
        )

    own = _own_client_base_name(config.client_name)
    others = _other_client_names() - {own}
    # テンプレート由来で混入しやすい固有名（他案件の client_id）
    leak_words = {w for w in others if len(w) >= 3}

    findings: list[Finding] = []
    for path, text in _iter_docs(config):
        rel = _display_path(path)
        is_html = path.suffix.lower() == ".html"
        for i, line in enumerate(text.split("\n"), start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # 1. 他クライアント名・テンプレート由来語の混入
            #    過去の事故（テンプレート冒頭の「> ... サンプル ... シート相当。」）は
            #    引用記法の行に出たため、注記・コメント行も対象に含める。
            for word in leak_words:
                if word in line:
                    findings.append(Finding(
                        "mismatch", rel, i, f"他案件・テンプレート由来の固有名 '{word}'",
                        "混入なし", word, stripped[:110],
                    ))

            # 数値の突合は本文のみ。注記・コメントには過去実行の参考値が入りうる。
            if stripped.startswith(("> ", "<!--")):
                continue

            nums = _numbers_in(line)
            if not nums:
                continue

            # 2. バッククォートで囲まれたイベント名の発火数
            #    名前の直後 PROXIMITY_CHARS 以内の数値だけを対象にする。1行に複数の指標が
            #    並ぶ散文で、遠くの無関係な数値を結びつけないため。
            # 2つの書き方（`name` と <code>name</code>）を1つの正規表現で見るので、
            # findall はグループの組を返す。空でないほうを取る。
            line_names = {g for t in BACKTICK_RE.findall(line) for g in t if g}
            for m in BACKTICK_RE.finditer(line):
                name = m.group(1) or m.group(2)
                truth = events.get(name)
                if truth is None or truth == 0:
                    continue
                near = _numbers_in(line, after=m.end(), window=PROXIMITY_CHARS)
                close = [n for n in near if _comparable(n, truth)]
                # 同じ行に出てくる別イベントの実測値と一致する数値は、その別イベントを
                # 指しているので誤りではない（例:「hp_reserve_complete は cv_reserve と
                # 同一ページで発火（1,139件）」の 1,139 は hp_reserve_complete の値）
                others = {events[o] for o in line_names if o != name and o in events}
                # 行内で名前が挙がっているイベントの合計。「`purchase`、`line_cv_reserve_dl` | 801」
                # のように合計を書いている行を不一致にしないため。
                named_total = sum(events[o] for o in line_names if o in events)
                # 真値そのものは決して除外しない（別イベントと同数のことがあるため）
                close = [n for n in close
                         if n == truth or (n not in others and n != named_total)]
                # ページ別などの部分集合を語る行は、真値を超えたときだけ誤りとみなす
                # HTML の**表の行**だけ、URLを内訳の手がかりから外す。
                # 本文に書いたページ別内訳は Markdown と同じ扱いにする
                use_path_hint = not (is_html and TABLE_LINE_RE.search(line))
                if _is_scoped(line, use_path_hint=use_path_hint):
                    close = [n for n in close if n > truth]
                if close and truth not in close and not _is_breakdown(near, truth):
                    findings.append(Finding(
                        "mismatch", rel, i, f"`{name}` の発火数",
                        f"{truth:,}", ", ".join(f"{n:,}" for n in close), stripped[:110],
                    ))

            # 3. 明示ラベル付きの件数（GTMタグ/トリガー/変数 等）
            for label, truth in counts.items():
                key = label.split("（")[0]
                if key not in line or truth == 0:
                    continue
                close = [n for n in nums if _comparable(n, truth)]
                if close and truth not in close and not _is_breakdown(nums, truth):
                    findings.append(Finding(
                        "mismatch", rel, i, label,
                        f"{truth:,}", ", ".join(f"{n:,}" for n in close), stripped[:110],
                    ))

    # 重複（同一ファイル・行・ラベル）を除去
    seen, unique = set(), []
    for f in findings:
        key = (f.file, f.line_no, f.label)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def report(findings: list[Finding]) -> None:
    if not findings:
        print("突合完了。実データと矛盾する数値・他案件名の混入はありません。")
        return
    mismatches = [f for f in findings if f.severity == "mismatch"]
    print(f"不一致 {len(mismatches)} 件を検出しました。\n")
    for f in mismatches:
        print(f"  {f.file}:{f.line_no}")
        print(f"    項目  : {f.label}")
        print(f"    実データ: {f.expected}")
        print(f"    記載  : {f.found}")
        print(f"    該当行: {f.excerpt}")
        print()
