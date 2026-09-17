"""確認事項（questions.md）の**骨組み**を `_data/` から生成する。

出力するのは「検出できた事実と数値」だけで、**「なぜ確認が必要か」は書かない**。
そこは人が書く。数値の意味付けを自動化すると、解釈の誤りがそのままクライアントに出る。

出力先は `docs/questions.draft.md`（毎回作り直す骨組み）。
人が書き込む先は `docs/questions.md`（`ensure_questions_file` が無ければ作り、
あれば絶対に**上書きしない**。人が書いた本文を機械が消さないため）。

Usage:
    python run.py questions --client <client_id>
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from config import AuditConfig

# 命名規則の判定は review 側の実装を使う（判定基準を二重に持たない）。
# naming_severity が 'high'（GA4の仕様外）と判定したものだけを対象にする。
# 大文字だけの表記ゆれ（'low'）と日本語（対象外）はここでは論点にしない。
from measurement_design.review.diagnoser import naming_severity, suggest_name

# purchase 等、どのプロパティにも既定で入るため確認事項にしないイベント名（判定基準を二重に持たない）
from measurement_design.review.ga4_defaults import DEFAULT_NOISE_KEY_EVENTS

# キーイベント未登録でも「成果候補」として拾わない標準イベント。
# 自動収集・拡張計測で必ず発火するため、並べても論点にならない。
NOT_OUTCOME_CANDIDATES = {
    "page_view", "session_start", "first_visit", "user_engagement",
    "scroll", "click", "view_search_results", "video_start", "video_progress",
    "video_complete", "file_download", "form_start", "form_submit",
}

# 回遊・エンゲージメント系のイベント。発火数は大きいが成果候補ではない。
# これを除かないと、発火数順に並べたとき成果候補が下に沈んで論点にならない。
ENGAGEMENT_RE = re.compile(
    r"scroll|impression|link_click|^view_|^click_|到達|表示|閲覧|スクロール",
    re.IGNORECASE,
)

# 「成果候補」として拾う発火数の下限。これ未満は論点にする価値が薄い
OUTCOME_CANDIDATE_MIN = 30

# A-1 に載せる最大件数（これを超えた分は件数を明記して切る）
OUTCOME_CANDIDATE_LIMIT = 15

# GA4 が想定する medium の値。これ以外は独自値として論点にする
STANDARD_MEDIUMS = {
    "organic", "cpc", "ppc", "paid", "referral", "email", "affiliate",
    "display", "social", "video", "banner", "none", "(none)", "(not set)",
}


def _num(value) -> int:
    """GA4 Data API は数値を文字列で返すため int に寄せる。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _table(headers: list[str], rows: list[list[str]], align_right: set[int] | None = None) -> list[str]:
    align_right = align_right or set()
    sep = ["---:" if i in align_right else "---" for i in range(len(headers))]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _blank(prompt: str) -> list[str]:
    """人が本文を書くための空欄。ここを埋めないと資料として成立しない。"""
    return ["", f"<!-- {prompt} -->", ""]


# ── 検出 ──────────────────────────────────────────────


def _outcome_candidates(events: dict) -> list[str]:
    """キーイベント未登録だが発火数が大きいイベント（成果の定義の論点）。"""
    registered = {e.get("event_name", "") for e in events.get("key_events", [])}
    rows: list[list[str]] = []
    excluded = 0
    for row in events.get("events_30d", []):
        name = row.get("eventName", "")
        count = _num(row.get("eventCount"))
        if not name or name.startswith("("):
            continue
        if name in registered or name in NOT_OUTCOME_CANDIDATES:
            continue
        if count < OUTCOME_CANDIDATE_MIN:
            continue
        if ENGAGEMENT_RE.search(name):
            excluded += 1
            continue
        rows.append([f"`{name}`", f"{count:,}", ""])

    if not rows:
        return []
    rows.sort(key=lambda r: -int(r[1].replace(",", "")))
    shown, rest = rows[:OUTCOME_CANDIDATE_LIMIT], len(rows) - OUTCOME_CANDIDATE_LIMIT

    out = ["### A-1. 成果に含めるイベントの確定", ""]  # `## A` は _section_a が出す
    out += _blank(
        "ここに「なぜ確認が必要か」を書く。"
        "含めた場合／含めない場合で成果数がどう変わるか、"
        "チャネル評価にどう影響するかを数値で示す"
    )
    out += _table(
        ["イベント名", "30日発火", "成果に含めるか"],
        shown,
        align_right={1},
    )
    notes = [f"発火 {OUTCOME_CANDIDATE_MIN} 件未満は除外"]
    if excluded:
        notes.append(f"回遊・エンゲージメント系 {excluded} 件を除外（成果候補ではないため）")
    if rest > 0:
        notes.append(f"ほか {rest} 件は非表示")
    out += ["", f"<!-- {' / '.join(notes)}。全件は _data/02-events.json -->", ""]
    return out


def _zero_key_events(events: dict) -> list[str]:
    """登録されているが発火0のキーイベント。

    purchase はどのプロパティにも既定で入るため確認事項から除外する（ga4_defaults）。
    """
    registered = [
        ke.get("event_name", "") for ke in events.get("key_events", [])
        if ke.get("event_name") and ke.get("event_name") not in DEFAULT_NOISE_KEY_EVENTS
    ]
    if not registered:
        return []

    if "key_event_firing" not in events:
        # 発火実績が無いまま0件と書くと「登録済みキーイベントが全部実装漏れ」に見える。
        # 判定できないことを書く（phase1 だけ取得された状態で起きる）
        return [
            "### A-2. 発火していないキーイベントの扱い",
            "",
            "**判定不能。** `_data/02-events.json` にキーイベントの発火実績"
            "（`key_event_firing`）が入っていないため、機械では判定できない。",
            f"登録は {len(registered)} 件。`fetch` で発火実績まで取得して再生成すること。",
            "",
        ]

    firing = {r.get("eventName", ""): _num(r.get("eventCount")) for r in events.get("key_event_firing", [])}
    rows = [[f"`{name}`", "0", ""] for name in registered if firing.get(name, 0) == 0]

    if not rows:
        return []
    out = ["### A-2. 発火していないキーイベントの扱い", ""]
    out += _blank(
        "ここに「なぜ確認が必要か」を書く。"
        "実装漏れなのか、廃止済みなのか、そもそも何を意図した指標なのか"
    )
    out += _table(["キーイベント", "30日発火", "実装漏れ / 廃止"], rows, align_right={1})
    out += [""]
    return out


def _section_a(events: dict) -> list[str]:
    """A. 成果の定義（A-1 + A-2）。

    見出しは片方しか出ないときも1回だけ出す。A-1 が空のときに A-2 から始めると、
    節見出しの無い小見出しが宙に浮く。
    """
    body = _outcome_candidates(events) + _zero_key_events(events)
    if not body:
        return []
    return ["## A. 成果の定義", ""] + body


def _hosts(data_quality: dict) -> list[str]:
    """同一プロパティに計測されているホスト（計測対象の範囲の論点）。"""
    hosts = data_quality.get("hosts", [])
    if not hosts:
        return [
            "## B. 計測対象の範囲", "",
            "### B-1. 計測されているホストの棚卸し", "",
            "<!-- ホスト別データ（_data/07-data-quality.json）が未取得。",
            "     `fetch` で取得してから、standards/host-inventory.md の手順で実体を確認する -->",
            "",
        ]

    rows = []
    for row in hosts:
        name = row.get("hostName", "")
        sessions = _num(row.get("sessions"))
        if not name:
            continue
        rows.append([f"`{name}`", f"{sessions:,}", ""])
    rows.sort(key=lambda r: -int(r[1].replace(",", "")))

    out = ["## B. 計測対象の範囲", "", "### B-1. 計測されているホストの棚卸し", ""]
    out += _blank(
        "ここに「なぜ確認が必要か」を書く。"
        "意図的な合算なのか、意図せず測定IDが貼られているのか。"
        "**判定の前に standards/host-inventory.md の手順で各ホストの実体を確認すること。**"
        "広告の着地先から測定IDを外すと広告の計測が壊れる"
    )
    out += _table(["ホスト", "30日セッション", "実体 / 判定"], rows[:20], align_right={1})
    out += [""]
    return out


def _unassigned(traffic: dict) -> list[str]:
    """Unassigned の規模（UTM 運用主体の論点）。"""
    out: list[str] = []

    channels = traffic.get("channel_performance", [])
    unassigned = [c for c in channels if c.get("sessionDefaultChannelGroup") == "Unassigned"]
    if unassigned:
        sessions = sum(_num(c.get("sessions")) for c in unassigned)
        total = sum(_num(c.get("sessions")) for c in channels) or 1
        out += ["### C-1. Unassigned の中身と UTM の運用主体", ""]  # `## C` は _section_c が出す
        out += _blank(
            "ここに「なぜ確認が必要か」を書く。"
            "誰がパラメータを付けているか（自社／代理店／ASP）が分からないと、"
            "ルールを決めても運用に乗らない"
        )
        out += _table(
            ["項目", "セッション", "構成比"],
            [["Unassigned", f"{sessions:,}", f"{sessions / total * 100:.1f}%"]],
            align_right={1, 2},
        )
        out += [""]
    return out


def _custom_mediums(traffic: dict) -> list[str]:
    """独自 medium（GA4 の既定チャネルに分類されない値）。

    UTM 別の実値（`source_medium` = sessionSource × sessionMedium）は `run_phase5` の
    `get_utm_sources` で取得できるが、**`fetch` が phase5 を呼んでおらず、
    `dataset.LEGACY_KEY_MAP` にも割り当てが無い**（接続は P-4741）。
    未取得のまま黙って何も出さないと「独自 medium は無かった」と読まれるので、
    未取得であることを本文に出す（`_hosts` と同じ扱い）。
    """
    if "source_medium" not in traffic:
        return [
            "### C-2. 独自 medium の扱い",
            "",
            "<!-- UTM 別の実値（source_medium）が未取得のため判定できていない。",
            "     medium に代理店名・媒体名が入っていると GA4 の既定チャネルに分類されず、",
            "     広告の成果が自然流入として計上される。取得を接続してから再生成する -->",
            "",
        ]

    out: list[str] = []
    sources = traffic["source_medium"]
    custom = []
    for row in sources:
        medium = str(row.get("sessionMedium", "")).strip()
        if not medium or medium.lower() in STANDARD_MEDIUMS:
            continue
        custom.append([f"`{medium}`", f"`{row.get('sessionSource', '')}`", f"{_num(row.get('sessions')):,}", ""])

    if custom:
        custom.sort(key=lambda r: -int(r[2].replace(",", "")))
        out += ["### C-2. 独自 medium の扱い", ""]
        out += _blank(
            "ここに「なぜ確認が必要か」を書く。"
            "medium に代理店名・媒体名が入っていると GA4 の既定チャネルに分類されない"
        )
        out += _table(
            ["medium", "source", "セッション", "正しい組み合わせ"],
            custom[:15],
            align_right={2},
        )
        out += [""]
    return out


def _section_c(traffic: dict) -> list[str]:
    """C. 流入パラメータ（UTM）（C-1 + C-2）。

    A 節と同じ理由で、片方しか出ないときも見出しを1回だけ出す。
    Unassigned が無く独自 medium だけがある案件で C-2 から始まると、
    前の節の下に潜り込む。
    """
    body = _unassigned(traffic) + _custom_mediums(traffic)
    if not body:
        return []
    return ["## C. 流入パラメータ（UTM）", ""] + body


def _naming(events: dict) -> list[str]:
    """GA4の仕様に合わない名前（移行するかの論点）。GA4の仕様外（high）のものだけを対象にする。"""
    rows = []
    for row in events.get("events_30d", []):
        name = row.get("eventName", "")
        if not name or name.startswith("("):
            continue
        if naming_severity(name) != "high":
            continue
        rows.append([f"`{name}`", f"{_num(row.get('eventCount')):,}", f"`{suggest_name(name)}`", ""])

    if not rows:
        return []
    rows.sort(key=lambda r: -int(r[1].replace(",", "")))

    out = ["## D. イベント名の表記", "", "### D-1. GA4の仕様に合わない名前を移行するか", ""]
    out += _blank(
        "ここに「なぜ確認が必要か」を書く。"
        "リネームすると過去データと繋がらない。移行の可否と時期は業務都合に依存する"
    )
    out += _table(
        ["現状の名前", "30日発火", "変更案", "移行する / 削除する"],
        rows[:20],
        align_right={1},
    )
    out += [""]
    return out


def _unused_definitions(custom_definitions: dict) -> list[str]:
    """値が入っていないカスタム定義（削除可否の論点）。"""
    values = custom_definitions.get("dimension_values", {})
    if not values:
        return []

    rows = []
    for param, info in values.items():
        if isinstance(info, dict) and info.get("has_data") is False:
            rows.append([f"`{param}`", str(info.get("scope", "")), ""])

    if not rows:
        return []
    total = len(custom_definitions.get("custom_dimensions", []))

    out = ["## E. カスタム定義", "", "### E-1. 値が入っていないカスタムディメンションを削除してよいか", ""]
    out += _blank(
        "ここに「なぜ確認が必要か」を書く。"
        "カスタムディメンションには登録上限があり、必要なものを入れるには不要なものを削る必要がある。"
        f"現在の登録数は {total} 件"
    )
    out += _table(["パラメータ名", "スコープ", "削除してよいか"], rows, align_right=set())
    out += [""]
    return out


# ── 生成 ──────────────────────────────────────────────


def generate(config: AuditConfig) -> Path:
    """`docs/questions.draft.md` を書き出してパスを返す。"""
    from config import resolve_client_paths
    import dataset

    paths = resolve_client_paths(config.client_name)
    data_dir, docs_dir = paths.data_dir, paths.docs_dir

    events = dataset.load(data_dir, "events")
    traffic = dataset.load(data_dir, "traffic")
    custom_definitions = dataset.load(data_dir, "custom_definitions")
    data_quality = dataset.load(data_dir, "data_quality")

    if not events:
        raise FileNotFoundError(
            f"02-events.json が見つかりません: {data_dir}\n先に `fetch` を実行してください。"
        )
    # phase1（設定）だけでも 02-events.json は key_events で埋まる。発火実績が無いまま
    # 生成すると「登録済みキーイベントが全部発火0」という誤った指摘を出してしまう
    if "events_30d" not in events:
        raise FileNotFoundError(
            f"02-events.json に発火実績（events_30d）がありません: {data_dir}\n"
            "プロパティ設定だけが取得された状態です。"
            "`fetch` で発火実績まで取得してから再実行してください。"
        )

    lines = [
        f"# 確認事項（骨組み） — {config.client_name}",
        "",
        "**このファイルは機械生成の骨組み。** 検出できた事実と数値だけが入っている。",
        "`<!-- -->` の箇所に「なぜ確認が必要か」を書き、影響が大きい順に並べ替えてから",
        "`questions.md` として仕上げる。**このファイル自体はクライアントに出さない。**",
        "",
        f"生成日: {date.today().isoformat()}",
        "",
        "---",
        "",
    ]

    # 影響の大きい順（成果の定義 → 計測対象 → UTM → 命名 → カスタム定義）
    for section in (
        _section_a(events),
        _hosts(data_quality),
        _section_c(traffic),
        _naming(events),
        _unused_definitions(custom_definitions),
    ):
        lines += section

    lines += [
        "---",
        "",
        "## 機械的に検出できないもの",
        "",
        "以下は `_data/` からは判定できない。**ヒアリングで埋める。**",
        "",
        "- 各成果指標の目標値（月次の件数）",
        "- 予約・申込のあとの歩留まり（キャンセル率など）",
        "- 実装の担当者と、要件定義書の有無",
        "- 現在の分析手段と、そこで見られていない指標（観点10）",
        "- 広告・アフィリエイトの運用主体と、パラメータルールの周知先",
        "",
    ]

    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "questions.draft.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def ensure_questions_file(docs_dir: Path, draft_path: Path, client: str) -> tuple[Path, bool]:
    """人が書き込む確認事項ファイル（questions.md）を用意する。**既にあれば何もしない。**

    generate() が毎回作り直す questions.draft.md と違い、questions.md は人が
    「なぜ確認が必要か」を書き足し、ヒアリング結果を埋めていく先。
    `review` の check-report.md に対する check-report-notes.md と同じ構図の不具合
    （完了メッセージが書き込み先として draft を案内するのに、draft は次回実行で
    まるごと消える）だったため、renderer.ensure_check_report_notes と同じ
    「無ければ作る。あれば絶対に上書きしない」に揃える。

    中身は questions.draft.md の骨組み（検出済みの表・`<!-- -->` の空欄）をそのまま
    複製する。空で作ると、検出済みの事実と数値を draft を見ながら手で書き写す必要が
    生じて draft と二重管理になる。骨組みを複製し、その場で空欄を埋めていくほうが
    実際の使い方（draft を見て → questions.md に清書）に合う。
    ヘッダーだけ、draft 専用の断り書き（「クライアントに出さない」「骨組み」）を
    questions.md 用の案内（上書きされない・仕上げたらクライアントへの確認事項として使う）
    に差し替える。ヘッダーの終わりは最初の "---" 行（generate() が必ず先頭の区切りとして
    出す）で判定するため、ヘッダーの行数が変わっても追従できる。

    戻り値: (questions_path, 今回新規作成したか)
    """
    docs_dir.mkdir(parents=True, exist_ok=True)
    questions_path = docs_dir / "questions.md"
    if questions_path.exists():
        return questions_path, False

    draft_lines = draft_path.read_text(encoding="utf-8").splitlines()
    try:
        sep_idx = draft_lines.index("---")
        body_lines = draft_lines[sep_idx + 1:]
    except ValueError:
        body_lines = draft_lines

    header = [
        f"# 確認事項 — {client}",
        "",
        "**このファイルは `questions` を再実行しても上書きされません。**",
        "`questions.draft.md` は毎回まっさらに作り直される骨組みです。"
        "こちらに書き足した内容は消えません。",
        "`<!-- -->` の箇所に「なぜ確認が必要か」を書き、影響が大きい順に並べ替えて"
        "仕上げてください。仕上がったらこのファイルをクライアントへの確認事項として使います。",
        "",
        "---",
    ]
    questions_path.write_text("\n".join(header + body_lines), encoding="utf-8")
    return questions_path, True
