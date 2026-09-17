"""計測が壊れている兆候を、実測値から機械的に検出する。

命名規則や重複タグの検出（`diagnoser.py`）と違い、こちらは
**「数字の形がおかしい」ことから不備を逆算する**チェックを集めたもの。

いずれも実際の案件で見つかった不備を一般化した。
どれも人が気づくのに時間がかかった一方、実測値の比だけで判定できるため
機械化の効果が大きい（例: `session_start` ÷ セッション数が 0.49 と分かれば、
基盤タグの発火タイミングを最初に疑える）。

`review_data` ではなく `_data/` を直接読む。理由は、判定に必要な
ページ別・ホスト別のデータが数万行になり、LLM プロンプトに載せる
`review_data` に入れると他の観点の根拠を押し出してしまうため。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from measurement_design.review.ga4_defaults import DEFAULT_NOISE_KEY_EVENTS
from measurement_design.review.violation_id import dedupe_ids, make_id

# ── しきい値 ──────────────────────────────────────
# セッション比。自動収集イベントはセッションごとに1回は飛ぶのが前提。
# 0.9 を下回ったら「飛んでいないセッションがある」と判断する。
SESSION_RATIO_WARN = 0.9
SESSION_RATIO_CRITICAL = 0.7

# user_id の既定値混入の疑い。件数が多いのにユーザー数が極端に少ない。
UID_COLLAPSE_MIN_EVENTS = 1_000
UID_COLLAPSE_MAX_USERS = 5

# GA4 の 1プロパティあたりイベント名上限。8割で警告する。
EVENT_NAME_LIMIT = 500
EVENT_NAME_WARN_RATIO = 0.8

# `fetch` が取る `events_30d` の件数上限（`ga4_data.get_event_list` の既定）。
# 上限に達している一覧では「名前が無い」＝「0件」とは断定できない（切られただけの可能性）。
EVENTS_LIST_LIMIT = 100

# SPA計測ギャップ判定のしきい値。
# 実績のあるページに絞るための最低PV（ロングテールのノイズを除く）。
SPA_TITLE_MIN_PV = 10
# 「タイトル未設定」を指摘するのに必要な合計PV。
SPA_TITLE_UNSET_MIN_PV = 100
# 「同一タイトルが複数セクションで使われている」と判断する最低の異なりセクション数。
# ページネーション・絞り込み・カテゴリ一覧は同一セクション内なので対象にならない。
SPA_TITLE_STUCK_MIN_SECTIONS = 3
# 同一タイトルを共有する最低ページ数（偶然の一致を排除する）。
SPA_TITLE_STUCK_MIN_PATHS = 10
# 同一タイトルを共有するグループの最低合計PV。
SPA_TITLE_STUCK_MIN_PV = 200
# 404・エラーページのタイトルらしい語。これに当たる場合、複数セクションで
# タイトルが同じなのは当然（存在しないURLは実際に同じエラーページを返している）で、
# 「document.titleを更新していない」という指摘は的外れになる（試用フィードバックで検出:
# 「404ページのタイトル重複指摘は仕方ないのでは」）。
SPA_TITLE_ERROR_PAGE_RE = re.compile(r"404|not\s*found|エラー|ページが見つかりません", re.IGNORECASE)

# 検証環境・プレビュー環境を示すホスト名のパターン
NON_PRODUCTION_HOST_RE = re.compile(
    r"(?:^|[.\-])(?:stg|staging|dev|develop|test|preview|review|local|localhost|sandbox)"
    r"|\.web\.app$|\.vercel\.app$|\.netlify\.app$|^127\.0\.0\.1|^192\.168\.",
    re.IGNORECASE,
)

# GA4 が「初期化」「全ページ」相当で発火するタイミング。基盤タグはここで発火すべき。
INITIALIZATION_EVENTS = ("gtm.init", "gtm.js")

# 流入異常は独自のmedium辞書では判定しない。GA4の既定チャネルグループはGoogle側で
# 更新されるため、ローカル辞書との不一致を「公式定義違反」と断定すると陳腐化する。
# GA4自身が `Unassigned` に分類した実績が、母数1%かつ50セッション以上ある場合だけ出す。
UNASSIGNED_SESSION_RATIO = 0.01
UNASSIGNED_MIN_SESSIONS = 50

# 海外流入は通常発生しうるため、国別比率だけでは異常にしない。サイト全体の5%以上かつ
# 100セッション以上という「異常集中」を入口に、行動品質の複数信号が重なる場合だけ疑う。
FOREIGN_MIN_SESSION_RATIO = 0.05
FOREIGN_MIN_SESSIONS = 100
FOREIGN_RATE_DIVISOR = 10
FOREIGN_MAX_AVG_ENGAGEMENT_SECONDS = 3.0
FOREIGN_ENGAGEMENT_SITE_RATIO = 0.10
FOREIGN_MIN_BOUNCE_RATE = 0.95
FOREIGN_MIN_SIGNALS = 2


def _load(data_dir: Path, stem_prefix: str) -> dict:
    """`_data/<番号>-*.json` を読む。無ければ空 dict。"""
    for path in sorted(data_dir.glob(f"{stem_prefix}-*.json")):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _v(counter: list[int], severity: str, category: str, name: str,
       description: str, fix: str, location: str = "GA4", kind: str = "measurement",
       extra: str = "") -> dict:
    """1件の指摘 dict を作る.

    `counter` は各 `check_*` 関数の呼び出し側に残している引数（この関数の
    呼び出し口が多いため、シグネチャを揃えたまま各所を書き換えずに済ませる目的の
    後方互換パラメータ）。IDの計算にはもう使わない — 通し番号は、GA4/GTM APIが
    返す行の並び順が再取得のたびに変わり得るため、同じ指摘に別のIDが振られる
    不具合の原因だった。IDは `make_id`（内容から決まる安定した符号）に置き換えている。

    `extra`: 同じ category・kind・location・name でも別の指摘になり得る検査だけが渡す
    追加識別子（トリガー名・条件の値など。件数や比率のような変動する数字は不可）。
    """
    counter[0] += 1
    return {
        "id": make_id("V-H-", category, kind, location, name, extra),
        "severity": severity,
        "category": category,
        "target_kind": kind,
        "target_name": name,
        "location": location,
        "description": description,
        "suggested_fix": fix,
    }


# ──────────────────────────────────────
# 個別チェック
# ──────────────────────────────────────

def check_session_health(events: dict, counter: list[int]) -> list[dict]:
    """自動収集イベントのセッション比を見る。

    `session_start` はGoogleタグが初期化されたときに送られる。セッション数に対して
    著しく少ないなら、**基盤タグが初期化時に発火していない**ことを示す。
    GA4管理画面の「Googleタグが正しく設定されていない」警告と同じ事象を数字で捉える。
    """
    totals = events.get("totals", {})
    sessions = int(totals.get("sessions", 0) or 0)
    if sessions <= 0:
        return []

    rows = events.get("events_30d", [])
    if not rows:
        return []  # イベント実績そのものが未取得。比較できない
    counts = {r.get("eventName", ""): int(r.get("eventCount", 0) or 0) for r in rows}

    out = []
    for ev, label in (("session_start", "セッション開始"),
                      ("user_engagement", "エンゲージメント")):
        # **0件・欠落こそ最も重い。** ここで抜けると、基盤タグが全く発火していない
        # という一番深刻な状態を見逃す（実績があるのに0件なら確実に異常）。
        # `session_start` と `user_engagement` は共通してここで見る
        # （0件の断定・上限で切られた一覧の扱いはイベントの性質に関係なく成り立つ）。
        n = counts.get(ev, 0)
        ratio = n / sessions
        if ratio >= SESSION_RATIO_WARN:
            continue
        severity = "Critical" if ratio < SESSION_RATIO_CRITICAL else "High"
        if n == 0:
            # 一覧が上限に達している場合、「名前が無い」は「0件」ではなく
            # 「上位100件から溢れた」可能性がある。断定せず確認を促す。
            if ev not in counts and len(rows) >= EVENTS_LIST_LIMIT:
                out.append(_v(
                    counter, "High", "計測漏れ", ev,
                    f"`{ev}`（{label}）がイベント実績の上位{len(rows)}件に現れない。"
                    "一覧が上限に達しているため0件とは断定できないが、"
                    "セッションごとに1回は飛ぶはずのイベントとしては異常に少ない",
                    f"`{ev}` の実績を単独で確認する。0件なら基盤タグがページで動いていない。"
                    "GA4の基盤タグが「初期化」または「全ページ」で発火しているかを見る",
                ))
                continue
            out.append(_v(
                counter, "Critical", "計測漏れ", ev,
                f"`{ev}`（{label}）が{sessions:,}セッションに対して**1件も記録されていない**。"
                "GA4 が自動収集するイベントなので、送られていないのは基盤タグが動いていないということ",
                "GA4の基盤タグ（Googleタグ）がページに存在し「初期化」または「全ページ」で"
                "発火しているかを最初に確認する。"
                "**GTM に測定IDが見つからない場合は、Universal Analytics タグの"
                "「GA4 にも送信」経由で届いている可能性がある**（この経路では"
                "エンゲージメント時間も拡張計測も働かない）",
            ))
            continue
        if ev == "user_engagement":
            # **`user_engagement` はセッション数と1:1にならないのが正常。**
            # `session_start` はセッションの開始時に必ず1回飛ぶが、
            # `user_engagement` はエンゲージメントが成立したとき
            # （10秒以上の滞在・コンバージョン・2回以上のページ/画面表示のいずれか）
            # だけ飛ぶ。直帰したセッションでは発火しないので、セッション数を
            # 下回るのは定義上の正常系であり、GA4のエンゲージメント率は
            # 一般に2〜8割程度に分布する。「何倍を下回ったら異常」と言える
            # 共通の閾値を説明できないため、0件（上の分岐）以外はここでは判定しない。
            continue
        out.append(_v(
            counter, severity, "計測漏れ", ev,
            f"`{ev}`（{label}）がセッション数の{ratio:.2f}倍しかない"
            f"（{n:,}件 / {sessions:,}セッション）。"
            f"セッションの{(1 - ratio) * 100:.0f}%で発火していない",
            "GA4の基盤タグ（Googleタグ）が「初期化」または「全ページ」で発火しているかを確認する。"
            "DOM Ready や特定のカスタムイベントに紐づいていると、その前のイベントと離脱が落ちる",
        ))
    return out


def check_user_id_collapse(events: dict, counter: list[int]) -> list[dict]:
    """件数が多いのにユーザー数が極端に少ないイベントを検出する。

    `user_id` に既定値（"unknown" 等）を送っていると、未ログインの全アクセスが
    同一人物に統合され、ユーザー数が1に潰れる。
    """
    out = []
    for row in events.get("events_30d", []):
        name = row.get("eventName", "")
        n = int(row.get("eventCount", 0) or 0)
        users = row.get("totalUsers")
        if users is None or not name:
            continue
        users = int(users or 0)
        if n >= UID_COLLAPSE_MIN_EVENTS and users <= UID_COLLAPSE_MAX_USERS:
            out.append(_v(
                counter, "Critical", "ユーザー識別", name,
                f"`{name}` は{n:,}件に対してユーザー数が{users}人。"
                "`user_id` に定数（既定値）が送られている疑いが強い",
                "GTMの `user_id` 変数の既定値を外し、未ログイン時はパラメータ自体を送らない。"
                "実機の通信で `uid` の実値を確認する（DebugView または HAR）",
            ))
    return out


def check_event_name_cardinality(events: dict, counter: list[int]) -> list[dict]:
    """イベント名の異なり数が上限に近づいていないか。

    `events_30d` は上位100件に絞られているため、その行数からは判定できない
    （100 では 500 の8割に決して届かず、チェックが死ぬ）。
    `fetch` が別途取得する `event_name_total` を使い、無ければ判定しない。
    """
    total = events.get("event_name_total") or {}
    n = int(total.get("distinct_event_names", 0) or 0)
    if n <= 0:
        return []  # 未取得。fetch を通せば入る（古い _data では判定しない）
    if n < EVENT_NAME_LIMIT * EVENT_NAME_WARN_RATIO:
        return []
    return [_v(
        counter, "High" if n < EVENT_NAME_LIMIT else "Critical", "上限", "イベント名",
        f"イベント名の異なり数が{n}種（GA4上限 {EVENT_NAME_LIMIT}）",
        "重複しているイベント名を統合し、GTM内部名（`gtm.*`）などの不要な送信を止める",
    )]


def check_gtm_internal_events(events: dict, counter: list[int]) -> list[dict]:
    """GTM の内部イベント名が GA4 イベントとして送られていないか。

    `gtm.dom` `gtm.js` などがGA4に届いているのは、
    `{{Event}}` をイベント名にそのまま使うタグがある証拠。ドットはGA4の許可文字外。
    """
    out = []
    for row in events.get("events_30d", []):
        name = row.get("eventName", "")
        if name.startswith("gtm."):
            out.append(_v(
                counter, "High", "内部名の流出", name,
                f"GTMの内部イベント名 `{name}` がGA4イベントとして{int(row.get('eventCount', 0) or 0):,}件届いている",
                "イベント名に `{{Event}}` をそのまま使っているタグを特定し、"
                "固定文字列にするか発火条件から内部イベントを除外する",
            ))
    return out


def check_non_production_hosts(quality: dict, counter: list[int]) -> list[dict]:
    """検証環境のホストが本番プロパティに混入していないか。"""
    hosts = quality.get("hosts", [])
    hits = [(h.get("hostName", ""), int(h.get("sessions", 0) or 0))
            for h in hosts
            if h.get("hostName") and NON_PRODUCTION_HOST_RE.search(h.get("hostName", ""))]
    if not hits:
        return []
    total = sum(n for _, n in hits)
    top = ", ".join(f"{h}({n:,})" for h, n in sorted(hits, key=lambda x: -x[1])[:5])
    return [_v(
        counter, "Critical" if total >= 1000 else "High", "データ品質", "検証環境の混入",
        f"検証・プレビュー環境のホストが{len(hits)}件、計{total:,}セッション混入している（{top}）",
        "基盤タグの測定IDがハードコードされていないか確認する。"
        "ホスト名で送信先を切り替え、本番以外は検証用プロパティへ送る。"
        "あわせてGA4側で内部トラフィック除外を設定する",
    )]


def check_dimension_cardinality(quality: dict, counter: list[int]) -> list[dict]:
    """主要ディメンションに `(other)` が出ていないか。

    `(other)` が出ると、そのディメンションで分割した合計が全体と一致しなくなる。
    """
    out = []
    for key, label in (("hosts", "hostName"), ("countries", "country")):
        for row in quality.get(key, []):
            value = str(row.get("hostName") or row.get("country") or "")
            if value == "(other)":
                out.append(_v(
                    counter, "High", "上限", label,
                    f"`{label}` に `(other)` が{int(row.get('sessions', 0) or 0):,}セッション出ている。"
                    "異なり値が多すぎてカーディナリティ上限に達している",
                    "値が増え続ける原因（PRごとのプレビューURL等）を本番プロパティから外す。"
                    "このディメンションで分割した合計は全体と一致しないため、分割集計をそのまま使わない",
                ))
    return out


def _page_top_section(path: str) -> str:
    """パスの先頭セグメントを返す（`/media/knowledge/123` → `/media`）.

    「別セクションにまたがって同じタイトルが使われている」を判定するための単位。
    トップページ・セグメントの無いパスは `/` のまま返す。
    """
    p = re.sub(r"[?#].*$", "", path)
    if not p or p == "/":
        return "/"
    parts = [seg for seg in p.split("/") if seg]
    return f"/{parts[0]}" if parts else "/"


def check_spa_tracking_gap(pages: dict, counter: list[int]) -> list[dict]:
    """SPA（シングルページアプリケーション）で計測が追いついていない兆候を検出する。

    旧実装は「PVがセッション数を下回るページがN件」を機械的に指摘していたが、
    実データで見るとPV219/セッション254のような差はどのサイトでも普通に出る程度で、
    しきい値をどこに置いても誤検知になった（`user_engagement` と同じ問題）。実データを見た
    ユーザーからも「これぐらいの差は妥当。SPAの兆候を検出してほしい」という指摘を受け、
    この検査自体を廃止して置き換えた。

    見るのは `pageTitle` ディメンション（`run_pages` で `pagePath` に追加取得）。
    **`pageTitle` が取得されていないデータでは何も判定しない**（0件を返す）。
    「SPAではない」と誤って言い切らないための安全策で、既存の `_data/06-pages.json`
    （タイトル無し）で実行すると常にこの分岐に入る。GA4を再取得して確かめるのは
    従量APIの消費が伴うため、この関数だけでは行わない。

    検出する兆候は2つに絞った。他の兆候（1つのURLにPVが集中する・PV/セッション比が
    1に張り付く）は、単体では「1ページを読んで離脱するのが普通のコンテンツサイト」と
    区別できず誤検知になりやすいため、確度の高い2つに留めている。

      1. タイトル未設定: 実績のあるページで `pageTitle` が空・`(not set)`
      2. タイトル固定: 明らかに違うセクション（先頭パスが異なる）複数にまたがって
         同一タイトルが使われている。**ページネーション・絞り込み・カテゴリ一覧の
         ような同一セクション内での使い回しは対象外**（先頭パスが同じなら数えない）。

    いずれも「SPAである」とは断定しない。SPAかどうかはサイト側の実装方式の話であって
    それ自体は問題ではなく、指摘するのは「タイトルが更新されていない疑い」だけである。
    """
    rows = pages.get("pages", [])
    if not any("pageTitle" in r for r in rows):
        return []  # pageTitle 未取得。判定できない以上、何も言わない

    out: list[dict] = []

    # ── 1. タイトル未設定 ──
    unset_total = 0
    unset_paths: list[tuple[str, int]] = []
    for r in rows:
        path = r.get("pagePath", "")
        if not path or path.startswith("("):
            continue
        title = str(r.get("pageTitle") or "").strip()
        pv = int(r.get("screenPageViews", 0) or 0)
        if title in ("", "(not set)") and pv > 0:
            unset_total += pv
            unset_paths.append((path, pv))
    if unset_total >= SPA_TITLE_UNSET_MIN_PV:
        unset_paths.sort(key=lambda x: -x[1])
        top = ", ".join(f"{p}({pv:,}PV)" for p, pv in unset_paths[:4])
        out.append(_v(
            counter, "High", "SPA計測ギャップ", "ページタイトル",
            f"ページタイトルが未設定（空 または `(not set)`）のまま実績があるページが"
            f"{len(unset_paths)}件、計{unset_total:,}PVある（{top}）。"
            "SPAで画面遷移のたびに `document.title` を更新していない疑いがある",
            "画面遷移のたびに `document.title` をページ内容に合わせて更新する"
            "（またはGA4の `page_title` パラメータを明示的に上書きする）。"
            "SPAでなければ、該当ページのテンプレートに `<title>` が設定されているか確認する",
        ))

    # ── 2. タイトル固定（セクションを跨いで同じタイトルが使われている） ──
    by_title: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        path = r.get("pagePath", "")
        if not path or path.startswith("("):
            continue
        title = str(r.get("pageTitle") or "").strip()
        pv = int(r.get("screenPageViews", 0) or 0)
        if title in ("", "(not set)") or pv < SPA_TITLE_MIN_PV:
            continue  # タイトル未設定は上の1.で扱う。ロングテールは対象外
        by_title[title].append((path, pv))

    for title, entries in by_title.items():
        sections = {_page_top_section(p) for p, _ in entries}
        total_pv = sum(pv for _, pv in entries)
        if (len(entries) < SPA_TITLE_STUCK_MIN_PATHS
                or len(sections) < SPA_TITLE_STUCK_MIN_SECTIONS
                or total_pv < SPA_TITLE_STUCK_MIN_PV):
            continue
        entries.sort(key=lambda x: -x[1])
        top = ", ".join(f"{p}({pv:,}PV)" for p, pv in entries[:4])
        section_note = "、".join(sorted(sections)[:5])
        if SPA_TITLE_ERROR_PAGE_RE.search(title):
            # 404・エラーページは複数セクションで同じタイトルになるのが正常な挙動
            # （存在しないURLは実際に同じエラーページを返している）。
            # 「document.titleを更新していない」という指摘は的外れなので出さず、
            # 代わりに「壊れたリンクがどれだけ流入を生んでいるか」を指摘する。
            out.append(_v(
                counter, "Medium", "リンク切れ", title,
                f"エラーページのタイトル「{title}」に見えるものが、{len(sections)}個の異なる"
                f"セクション（{section_note}）にまたがる{len(entries)}件のURL（計{total_pv:,}PV）"
                f"で使われている（{top}）。存在しないURLへのアクセス（404）の疑いがあり、"
                "タイトルが同じなのは正常な挙動（SPAのタイトル更新の問題ではない）",
                "リンク元（他ページ・外部サイト・広告・過去URLの変更）を確認し、"
                "正しいURLへのリダイレクトまたはリンクの修正を検討する",
            ))
            continue
        out.append(_v(
            counter, "High", "SPA計測ギャップ", title,
            f"ページタイトル「{title}」が、{len(sections)}個の異なるセクション（{section_note}）に"
            f"またがる{len(entries)}件のURL（計{total_pv:,}PV）で同じまま使われている（{top}）。"
            "SPAで画面遷移時にタイトルを更新していない、またはURLと表示内容が対応していない疑いがある",
            "画面遷移のたびに `document.title` をページ内容に合わせて更新する。"
            "ページネーション・絞り込みなど同一セクション内での意図的な共通タイトルは対象外にしている"
            "ため、これが出た場合はセクションをまたぐ使い回しを疑う",
        ))
    return out


# クリック先がページでないことを示す手がかり。
# 外部リンク・ファイル・mailto/tel はページ実績に出てこない。
NON_PAGE_SCHEMES = ("mailto:", "tel:", "sms:", "javascript:")
NON_PAGE_EXTENSIONS = (
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".mp3",
)


def _is_non_page_target(value: str, own_hosts: set[str]) -> bool:
    """条件の値が「ページではないクリック先」か。"""
    low = value.lower()
    if low.startswith(NON_PAGE_SCHEMES):
        return True
    path_part = re.sub(r"[?#].*$", "", low)
    if path_part.endswith(NON_PAGE_EXTENSIONS):
        return True
    m = re.match(r"https?://([^/]+)", low)
    if m and own_hosts:
        host = m.group(1)
        # 自サイトのホストに含まれないなら外部リンク
        return not any(host == h or host.endswith("." + h) for h in own_hosts)
    return False


def check_stale_event_create_rules(defs: dict, pages: dict, counter: list[int],
                                   quality: dict | None = None,
                                   events: dict | None = None) -> list[dict]:
    """イベント作成ルールの条件URLが、実際に使われているページと合っているか。

    フォームのURLが変わったのにルールの条件が古いまま、というのは実際に起きる。
    条件に含まれるパスが実績のほとんど無いページなら、そのルールは死んでいる。
    """
    # **生成先イベントの発火実績があれば、それが最も直接的な証拠。**
    # ページPVは間接的な手がかりにすぎない（条件がクリック先なら特に）。
    fired = {}
    for r in (events or {}).get("events_30d", []):
        name = r.get("eventName", "")
        if name:
            fired[name] = int(r.get("eventCount", 0) or 0)
    events_truncated = len((events or {}).get("events_30d", [])) >= EVENTS_LIST_LIMIT

    # キーイベントの発火実績は**専用の取得で上限に切られていない**ため、
    # ここに現れなければ0件と断定できる（`events_30d` の上位100件では断定できない）。
    key_event_names = {
        k.get("event_name", k.get("eventName", ""))
        for k in (events or {}).get("key_events", [])
    } - {""}
    key_event_fired = {
        r.get("eventName", ""): int(r.get("eventCount", 0) or 0)
        for r in (events or {}).get("key_event_firing", [])
    }

    own_hosts = {
        str(h.get("hostName", "")).lower()
        for h in (quality or {}).get("hosts", [])
        if h.get("hostName") and not str(h.get("hostName", "")).startswith("(")
    }

    pv_by_path = {}
    for r in pages.get("pages", []):
        path = r.get("pagePath", "")
        if path:
            pv_by_path[path] = pv_by_path.get(path, 0) + int(r.get("screenPageViews", 0) or 0)

    # 条件の一致方式ごとの照合。**すべてを前方一致で見てはいけない。**
    # `/form/.*request_material` のような正規表現条件を前方一致で数えると
    # 該当0件になり、**生きているルールを Critical の陳腐化として誤報**する。
    def _matcher(comparison: str, needle: str):
        c = (comparison or "").upper()
        if "REGEX" in c or "REGEXP" in c:
            try:
                rx = re.compile(needle)
            except re.error:
                return None  # 解釈できない条件は判定しない
            # GA4 の `FULL_REGEXP` は**値全体の一致**を要求する。
            # ここを部分一致で見ると、条件に含まれる文字列を持つ別の高PVページが
            # 引っかかり、死んでいるルールを「生きている」と誤判定する。
            return rx.fullmatch if "FULL" in c else rx.search
        if "CONTAIN" in c:
            return lambda path: needle in path
        if "END" in c:
            return lambda path: path.endswith(needle)
        if "BEGIN" in c or "START" in c:
            return lambda path: path.startswith(needle)
        if "EQUAL" in c or "EXACT" in c:
            return lambda path: path == needle
        # 方式が分からない場合は前方一致で見る（従来の挙動）
        return lambda path: path.startswith(needle)

    def pv_of(fragment: str, comparison: str) -> int:
        """条件の値に該当するページの実績PVを合算する。判定できなければ -1。"""
        frag = re.sub(r"^https?://[^/]+", "", fragment)
        if not frag.startswith("/"):
            return -1
        match = _matcher(comparison, frag)
        if match is None:
            return -1
        return sum(pv for path, pv in pv_by_path.items() if match(path))

    out = []
    for key, rules in defs.items():
        if not key.startswith("event_create_rules") or not isinstance(rules, list):
            continue
        for rule in rules:
            dest = rule.get("destination_event", "")
            # 生成先イベントが実際に発火していれば、ルールは生きている
            if fired.get(dest, 0) > 0 or key_event_fired.get(dest, 0) > 0:
                continue
            # 発火0と断定できる条件:
            #  - キーイベントとして登録済みで、切られていない専用一覧に現れない
            #  - または通常のイベント一覧が上限に達しておらず、そこにも無い
            dest_confirmed_dead = (
                (dest in key_event_names and dest not in key_event_fired)
                or (bool(fired) and (dest in fired or not events_truncated))
            )
            for cond in rule.get("event_conditions", []):
                value = str(cond.get("value", ""))
                field = str(cond.get("field", cond.get("field_name", "")))
                if "url" not in field.lower() and "location" not in field.lower():
                    continue
                # **クリック先はページとは限らない。** 外部リンク・PDF・mailto などは
                # ページ実績（06-pages）に出てこないため、PV で判定すると
                # 生きているクリック計測ルールを「壊れている」と誤報する。
                if _is_non_page_target(value, own_hosts):
                    continue
                comparison = str(cond.get("comparison_type", cond.get("comparisonType", "")))
                pv = pv_of(value, comparison)
                if pv < 0:
                    continue
                # `link_url` はクリック先なので、ページ実績との突合は補助的な根拠にとどまる
                is_click_field = "link" in field.lower()
                if pv < 100:
                    if dest_confirmed_dead:
                        severity, note = "Critical", "。生成先イベントの発火も0件"
                    elif is_click_field:
                        severity, note = "High", ("。ただし条件はクリック先（`link_url`）なので、"
                                                  "ページ実績との突合は補助的な根拠にとどまる")
                    else:
                        severity, note = "Critical", ""
                    # 同じ生成先イベントに複数の条件（URL違い）が付くことがあるため、
                    # 条件の値（変動しない識別子）をIDの識別要素に加える。
                    out.append(_v(
                        counter, severity, "設定の陳腐化", dest,
                        f"イベント作成ルール「{dest}」の条件が `{value}` を参照しているが、"
                        f"該当ページの実績は直近30日で{pv:,}PVしかない。ルールが機能していない疑い{note}",
                        "現行のURLに条件を合わせる。同じ計測をGTM側でも持っているなら、"
                        "どちらか一方に一本化してこのルールは削除する",
                        extra=value,
                    ))
    return out


def _page_variants(path: str) -> set[str]:
    """同じページを指す別表記の候補を返す。

    2026-08 のミライズ英会話案件で、`/trial-lesson` と `/trial-lesson.html` が
    バイト単位で同一のページなのに、イベント作成ルールが前者の**完全一致**だけを
    条件にしていて、主導線である後者の 102 セッション（そのページの 76.7%）を
    丸ごと取りこぼしていた。**ルール自体は発火しているので
    `check_stale_event_create_rules` では見つからない。**
    """
    p = re.sub(r"[?#].*$", "", path)
    out = {p}
    if p.endswith(".html"):
        out.add(p[: -len(".html")])
    elif not re.search(r"\.[a-z0-9]{2,5}$", p, re.IGNORECASE):
        out.add(p + ".html")
    # ディレクトリ表記と index
    if p.endswith("/"):
        out.add(p[:-1] or "/")
        out.add(p + "index.html")
    elif p and not re.search(r"\.[a-z0-9]{2,5}$", p, re.IGNORECASE):
        out.add(p + "/")
        # 逆方向（`/foo/index.html` → `/foo`）を同じページとして扱っているので、
        # こちらからも `/foo/index.html` を候補に入れて対称にする
        out.add(p + "/index.html")
    if p.endswith("/index.html"):
        out.add(p[: -len("index.html")])
        out.add(p[: -len("/index.html")] or "/")
    return {v for v in out if v}


# 取りこぼしを指摘する下限。これ未満のセッション数なら誤差として扱う。
VARIANT_MISS_MIN_SESSIONS = 20
# 取りこぼし比率の下限。
VARIANT_MISS_MIN_RATIO = 0.2


def _is_negated(cond: dict) -> bool:
    """条件が否定（〜ではない）かどうか。

    GA4 の条件は `comparison_type` とは別に否定フラグを持つ。
    `does not equal /foo` は「equals 系 + 否定」で表されるため、
    フラグを見ないと **`/foo` を意図的に除外しているルールを
    「`/foo` の完全一致」と誤読**して、別表記の取りこぼしを誤検知する。
    """
    for key in ("negated", "negate", "isNegated"):
        v = cond.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() == "true":
            return True
    return False


def check_event_rule_url_variants(defs: dict, pages: dict, counter: list[int],
                                  quality: dict | None = None) -> list[dict]:
    """イベント作成ルールが、同じページの別URL表記を取りこぼしていないか。

    ルールが発火していても、条件の一致方式（完全一致など）のせいで
    同一ページの別表記が漏れることがある。漏れた分は**そのまま欠測になる**。
    """
    # ページ実績はホストを跨いで `pagePath` で合算されている。計測ホストが
    # 複数あるプロパティでは `page_location`（フルURL）の条件を突き合わせられない。
    hosts = {
        str(h.get("hostName", "")).lower()
        for h in (quality or {}).get("hosts", [])
        if h.get("hostName") and not str(h.get("hostName", "")).startswith("(")
    }
    multi_host = len(hosts) > 1

    sessions_by_path: dict[str, int] = {}
    for r in pages.get("pages", []):
        path = r.get("pagePath", "")
        if path and not path.startswith("("):
            sessions_by_path[path] = sessions_by_path.get(path, 0) + int(r.get("sessions", 0) or 0)
    if not sessions_by_path:
        return []

    # 条件の値ごとにまとめる。同じ条件のルールが複数あると同じ指摘が並ぶため
    # （ミライズ英会話案件では4件が同一条件だった）。
    # キーは (フィールド名, パス)。同じパスでも `page_path` と `page_location` では
    # 提示すべき正規表現が違う（後者の値はフルURL）ため分けて持つ。
    affected: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, rules in defs.items():
        if not key.startswith("event_create_rules") or not isinstance(rules, list):
            continue
        for rule in rules:
            dest = rule.get("destination_event", "")
            conds = rule.get("event_conditions", [])
            # **ページ表示から作るルールに限る。** クリックから作るルール
            # （`event_name` = `click` で `link_url` を条件にするもの）は、
            # 条件の値がクリック先であってページではない。`/trial-lesson.html` に
            # ページ実績があっても「そのリンクが押された」証拠にはならないので、
            # ページ実績と突き合わせると生きているルールを誤って計測漏れにする。
            if not any(
                str(c.get("field", c.get("field_name", ""))).lower() == "event_name"
                and "EQUAL" in str(c.get("comparison_type", c.get("comparisonType", ""))).upper()
                and str(c.get("value", "")) == "page_view"
                and not _is_negated(c)
                for c in conds
            ):
                continue
            for cond in conds:
                field = str(cond.get("field", cond.get("field_name", ""))).lower()
                # `page_path` / `page_location` だけを見る。`link_url` は上記の理由で除外。
                if field not in ("page_path", "page_location"):
                    continue
                # **否定条件は対象外。** `/foo` を意図的に除外しているルールを
                # 「`/foo` の完全一致」と読むと誤検知になる。
                if _is_negated(cond):
                    continue
                comparison = str(cond.get("comparison_type", cond.get("comparisonType", ""))).upper()
                # 完全一致だけが取りこぼす。含む・前方一致・正規表現は別途
                # `check_stale_event_create_rules` と設計側で見る。
                if "EQUAL" not in comparison and "EXACT" not in comparison:
                    continue
                raw = str(cond.get("value", ""))
                # **`page_location` はホストを含むフルURL。** ページ実績
                # （`06-pages`）はホストを跨いで `pagePath` で合算されているため、
                # ホストを落として突き合わせると「別ホストに同じパスがある」だけで
                # 取りこぼしと誤判定する。計測ホストが複数あるときは扱わない。
                if field == "page_location" and multi_host:
                    continue
                value = re.sub(r"^https?://[^/]+", "", raw)
                if value.startswith("/"):
                    key_ = (field, value)
                    if dest not in affected[key_]:
                        affected[key_].append(dest)

    out: list[dict] = []
    for (field, value), dests in affected.items():
        hit = sessions_by_path.get(value, 0)
        missed = {
            v: sessions_by_path[v]
            for v in _page_variants(value) - {value}
            if sessions_by_path.get(v, 0) > 0
        }
        if not missed:
            continue
        miss_total = sum(missed.values())
        total = hit + miss_total
        if miss_total < VARIANT_MISS_MIN_SESSIONS or not total:
            continue
        ratio = miss_total / total
        if ratio < VARIANT_MISS_MIN_RATIO:
            continue
        detail = "、".join(f"`{v}`({s:,}セッション)" for v, s in
                          sorted(missed.items(), key=lambda x: -x[1]))
        # dests は defs（イベント作成ルールの辞書）の走査順に依存するため、
        # そのまま join すると再取得で並びが変わり、target_name（IDの素）が
        # ぶれる。ソートして固定する。
        names = "、".join(sorted(d for d in dests if d))
        # 取りこぼしのほうが多ければ、条件が主導線を外している
        severity = "Critical" if ratio >= 0.5 else "High"
        # **実際に実績があるパスの列挙から正規表現を組む。**
        # `値 + (\.html)?` のような組み立て方をすると、条件が `.html` 側で
        # 取りこぼしが拡張子なし側のときに、提示した式では直らない
        # （`^/foo\.html(\.html)?$` は `/foo` に当たらない）。
        alts = "|".join(re.escape(p) for p in sorted({value, *missed}))
        # **フィールドに合う式を出す。** `page_location` の値はフルURLなので、
        # パスだけの式を同じフィールドに当てるとどちらにも一致しない。
        if field == "page_location":
            regex = f"^https?://[^/]+({alts})$"
            field_note = ("（`page_location` はフルURLなのでホスト部分を含める。"
                          "`page_path` に変えるなら `^(" + alts + ")$`）")
        else:
            regex = f"^({alts})$"
            field_note = ""
        # (field, value) が affected のキーそのもの（同じ names 文字列が別の
        # field/value 組から生じる可能性に備えて識別要素に含める）。
        out.append(_v(
            counter, severity, "計測漏れ", names or value,
            f"イベント作成ルール（{names}）の条件が `{field}` = `{value}` の"
            f"**完全一致**になっているが、"
            f"同じページの別表記 {detail} が条件に当たらない。"
            f"合計{total:,}セッションのうち{miss_total:,}セッション（{ratio:.1%}）が"
            f"計測から漏れている",
            f"両方に当たる正規表現（完全一致）に変える: `{regex}`{field_note}。"
            "**`含む`／`前方一致` にしてはいけない** — 完了ページなど"
            "前方一致する別ページまで拾って、今度は逆に水増しになる。"
            "URL自体をどちらかに正規化するのが根本対処",
            extra=f"{field}|{value}",
        ))
    return out


# レポートの分裂を指摘する下限（両方の表記に実績があること）。
# 取りこぼしと違い被害は「毎回2行足す手間」なので、比率ではなく実数で見る。
DUP_URL_MIN_SESSIONS = 50


def check_duplicate_page_urls(pages: dict, counter: list[int]) -> list[dict]:
    """同じページが複数のURL表記で計測されていないか。

    `check_event_rule_url_variants` と原因は同じだが、被害が違う。あちらは
    計測漏れ（数字が足りない）、こちらは**レポートの分裂**（数字が2行に割れる）。
    比率が小さくてもページ別レポートを読むたびに合算が必要になるので、
    実数だけで拾う。

    ミライズ英会話案件では `/` 1,996 と `/index.html` 176 に割れており、
    トップページの実PVは 4,707 なのにレポート上は 4,275 と表示されていた。

    **拾えるのは拡張子と `index.html` の違いだけ。** 同じ内容が別ディレクトリに
    ある場合（同案件の `/plan/online.html` と `/online.html`）は、GA4 のデータだけでは
    別ページと区別できない。あれは両方を取得してバイト比較して初めて分かった。
    """
    sessions: dict[str, int] = {}
    pv: dict[str, int] = {}
    for r in pages.get("pages", []):
        path = r.get("pagePath", "")
        if not path or path.startswith("("):
            continue
        sessions[path] = sessions.get(path, 0) + int(r.get("sessions", 0) or 0)
        pv[path] = pv.get(path, 0) + int(r.get("screenPageViews", 0) or 0)

    groups: list[tuple[int, list[str]]] = []
    handled: set[str] = set()
    for path in sorted(sessions, key=lambda p: -sessions[p]):
        if path in handled:
            continue
        members = sorted(v for v in _page_variants(path) if sessions.get(v, 0) > 0)
        if len(members) < 2:
            continue
        handled.update(members)
        total = sum(sessions[m] for m in members)
        if min(sessions[m] for m in members) < 5 or total < DUP_URL_MIN_SESSIONS:
            continue
        groups.append((total, members))

    if not groups:
        return []
    groups.sort(key=lambda g: -g[0])
    shown = groups[:5]
    detail = "、".join(
        " / ".join(f"`{m}`({pv[m]:,}PV)" for m in members) for _, members in shown
    )
    more = f"（ほか{len(groups) - len(shown)}組）" if len(groups) > len(shown) else ""
    return [_v(
        counter, "Low", "レポートの分裂", f"{len(groups)}組のURL",
        f"末尾表記・拡張子等が異なるURL候補が{len(groups)}組ある: "
        f"{detail}{more}。ページ別レポートで数字が割れるため、"
        "内容が同一かを確認する。各表記5セッション以上・組合計50セッション以上の候補に限定している",
        "両URLの内容・リダイレクトと既存の正規化用定義を確認する。"
        "同じページならサイト側の正規URL誘導または収集・集計時の正規化を設計し、"
        "イベント作成条件への影響を確認してから変更する",
    )]


# ──────────────────────────────────────
# 個人情報の混入
#
# 試用で実際に見つかった事象: `/mypage/reset_password/<長いトークン>/` のように、
# パスワード再設定用のトークンがそのままGA4のページパスに記録されていた。
# GA4の閲覧権限を持つ全員がそのトークンを読める状態になり、GA4の利用規約が禁じる
# 「個人を特定できる情報の送信」に抵触しうる。
#
# **過検出しないことを最優先にする。** 記事ID・商品ID・注文番号のような正当な
# 長い英数字を「トークン」と誤認すると、この検査自体が信用されなくなる。
# そのため判定は「文脈（隣接するディレクトリ名）」と「形（長さ・英数字の混在）」の
# **両方が揃ったときだけ**にする。片方だけでは判定しない。
# ──────────────────────────────────────

# トークンらしいと判定する最低文字数。**記事ID・商品IDとの唯一の切り分け材料。**
# 実際のパスワード再設定・招待リンクのトークンはハッシュ/UUID/base64相当で
# 20文字を大きく超えるのが通例（UUID4は36文字、多くのフレームワークは32文字hex、
# Djangoのdefault_token_generatorでも約20文字）。一方、記事ID・商品ID・注文番号は
# 連番かせいぜい十数文字のslugで、20文字を超えることは稀。この境界で切ることで
# 「長い英数字=トークン」と早合点する誤検知を避ける。
PII_TOKEN_MIN_LEN = 20

# トークンが置かれる典型的なディレクトリ名（の直前セグメント）。
# **これに隣接する場合に限って**長い英数字をトークン候補として見る（隣接条件が
# もう1つの絞り込み）。「明らかにパスワード系・認証系」と「文脈だけでは断定しづらい
# 汎用語」の2群に分け、後者は severity を1段落として過検出の影響を抑える。
PII_TOKEN_STRONG_CONTEXT_RE = re.compile(
    r"^(reset[-_]?password|password[-_]?reset|forgot[-_]?password|"
    r"activat(?:e|ion)|confirm(?:ation)?|verif(?:y|ication)|"
    r"invit(?:e|ation)|unsubscribe|magic[-_]?link|login[-_]?link)$",
    re.IGNORECASE,
)
PII_TOKEN_WEAK_CONTEXT_RE = re.compile(
    r"^(auth|token|session|sid)$", re.IGNORECASE,
)

# トークンらしい文字列そのものの形。UUID（ハイフン込み36文字）と、区切りの無い
# 英数字（英字・数字が両方混ざった20文字以上）の2パターンに限る。
# **数字だけ・英字だけの20文字超は対象にしない**（0埋めした連番IDと区別が付かない）。
_PII_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE,
)
_PII_TOKEN_CHARS_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _looks_like_pii_token(segment: str) -> bool:
    """パスの1セグメントが、トークンらしい文字列に見えるか。

    **単独では呼ばない。** `PII_TOKEN_STRONG_CONTEXT_RE` / `_WEAK_CONTEXT_RE` に
    隣接するセグメントに対してだけ使う。この条件を外すと、`20241001-release-note`
    のような日付付きの記事slugまで拾ってしまう。
    """
    if _PII_UUID_RE.fullmatch(segment):
        return True
    if len(segment) < PII_TOKEN_MIN_LEN or not _PII_TOKEN_CHARS_RE.fullmatch(segment):
        return False
    return bool(re.search(r"[0-9]", segment) and re.search(r"[A-Za-z]", segment))


# クエリのキー名そのものが個人情報の送信を示すもの。**値の中身を見るまでもなく、
# このキー名が実測に出ている時点で「個人情報をURLに載せる設計」を示す。**
# email/password/token系は値がほぼ確実に機微情報かトークンなので Critical、
# sid/name系は用途によって当たり外れがある（社内向けの識別子・表示名の場合もある）
# ため一段落として High にする。
PII_QUERY_KEY_STRONG_RE = re.compile(
    r"^(email|mail|tel|phone|phone_?number|password|pwd|passwd|"
    r"token|access_?token|refresh_?token|auth_?token)$", re.IGNORECASE,
)
PII_QUERY_KEY_WEAK_RE = re.compile(
    r"^(sid|session_?id|name|fullname|full_?name|last_?name|first_?name)$", re.IGNORECASE,
)


def _split_path_and_query(raw: str) -> tuple[list[str], dict[str, str]]:
    """パスをセグメントに、クエリを key→value に分ける。

    GA4 の `pagePath` ディメンションは通常クエリ文字列を含まないが、実装によっては
    フルURLがそのまま記録される事故が起こり得るため、`?` があれば分けて両方を見る。
    """
    path_part, _, query_part = raw.partition("?")
    segments = [s for s in path_part.split("/") if s]
    query: dict[str, str] = {}
    if query_part:
        for pair in query_part.split("&"):
            key, _, value = pair.partition("=")
            if key:
                query[key] = value
    return segments, query


def _mask_pii_path(segments: list[str], token_idx: int) -> str:
    """パスのディレクトリ構造は残し、トークンのセグメントだけ伏せて返す。

    レポートは共有される文書なので、実際のトークン値をそのまま印字しない。
    一方、利用者が直す場所を特定できるよう、ディレクトリ構造は残す。
    """
    masked = list(segments)
    masked[token_idx] = "****"
    return "/" + "/".join(masked)


def check_page_pii(pages: dict, counter: list[int]) -> list[dict]:
    """GA4のページパス・クエリパラメータに個人情報らしき値が記録されていないか。

    見るのは3種類。

      1. パスワード再設定・認証系のディレクトリに続く、トークンらしい長い英数字
      2. メールアドレス・電話番号（パス・クエリの値として）
      3. `email=` `password=` `token=` のような、個人情報を示すクエリのキー名

    **1トークン=1件で指摘しない。** ユーザーごとに値が変わるトークンを1件ずつ挙げると
    ユーザー数だけ指摘が並ぶが、実体は「そのURL設計が個人情報を記録する」という
    1件の設計不備なので、ディレクトリ（またはキー名）単位で束ねて件数とPVを集計する。

    **同じキーに値レベルとキー名レベルの両方が当たる場合、キー名の指摘は出さない。**
    `?email=taro@example.com` は値そのものがメールアドレスなので (2) で検出できる。
    ここで (3) も別枠で数えると、1本のURLの1つの問題が2件に水増しされて出る
    （実データ確認で見つかった不具合）。キー名の検出が本来担当するのは、値がハッシュ化・
    エンコード済みで正規表現に当たらないケース（`?email=8f3a9c...`）。そこは値レベルが
    空振りするので、キー名の検出だけが拾う必要がある。そのため、除外の判定は
    「そのURL・そのキーの**値自体**がメール／電話の形に一致するか」で行う
    （キー名ごと丸ごと除外すると、同じ `?email=` に生値とハッシュ済みが混在する
    サイトで後者まで消えてしまう）。

    レポートに実URLをそのまま出さないため、この関数が返す `target_name` / `description`
    はマスク済みの値だけを持つ（`_mask_pii_path` / メールを `****@****` に置換 等）。
    """
    rows = pages.get("pages", [])
    if not rows:
        return []

    import pii  # scripts/pii.py。email/電話の判定は既存の正規表現をそのまま再利用する

    token_groups: dict[str, dict] = {}
    email_groups: dict[str, dict] = {}
    phone_groups: dict[str, dict] = {}
    query_key_groups: dict[str, dict] = {}

    for r in rows:
        raw = r.get("pagePath", "")
        if not raw or raw.startswith("("):
            continue
        pv = int(r.get("screenPageViews", 0) or 0)
        segments, query = _split_path_and_query(raw)

        # 1. パスワード再設定・認証系ディレクトリに続くトークン
        for i in range(len(segments) - 1):
            seg = segments[i]
            is_strong = bool(PII_TOKEN_STRONG_CONTEXT_RE.match(seg))
            is_weak = bool(PII_TOKEN_WEAK_CONTEXT_RE.match(seg))
            if not (is_strong or is_weak):
                continue
            if not _looks_like_pii_token(segments[i + 1]):
                continue
            prefix = "/" + "/".join(segments[: i + 1])
            key = f"{prefix}\x1f{'strong' if is_strong else 'weak'}"
            g = token_groups.setdefault(key, {
                "prefix": prefix, "severity": "Critical" if is_strong else "High",
                "count": 0, "pv": 0, "example": _mask_pii_path(segments, i + 1),
            })
            g["count"] += 1
            g["pv"] += pv
            break  # 1パスにつき1回だけ数える

        # 2. メールアドレス（パス・クエリの値として）
        if pii.EMAIL_RE.search(raw):
            section = _page_top_section(raw)
            g = email_groups.setdefault(section, {
                "count": 0, "pv": 0, "example": pii.EMAIL_RE.sub("****@****", raw),
            })
            g["count"] += 1
            g["pv"] += pv

        # 3. 電話番号。pii.PHONE_RE と同じ理由で、区切り文字があるものだけを対象にする
        # （区切りの無い数字列はtransaction_id等のIDと区別が付かない）。
        if pii.PHONE_RE.search(raw):
            section = _page_top_section(raw)
            g = phone_groups.setdefault(section, {
                "count": 0, "pv": 0, "example": pii.PHONE_RE.sub("****-****-****", raw),
            })
            g["count"] += 1
            g["pv"] += pv

        # 4. クエリのキー名そのもの。**値自体が(2)(3)のメール/電話として既に
        # 検出されているキーは対象外にする。** 値が読めた時点でキー名の指摘は
        # 情報を足さない（同じURL・同じ問題を2件に水増しするだけになる）。
        # 値がハッシュ化・エンコード済みでメール/電話の形に当たらない場合だけ、
        # ここでキー名から拾う（本来の担当範囲）。
        for qkey, qval in query.items():
            is_strong = bool(PII_QUERY_KEY_STRONG_RE.match(qkey))
            is_weak = bool(PII_QUERY_KEY_WEAK_RE.match(qkey))
            if not (is_strong or is_weak):
                continue
            if pii.EMAIL_RE.search(qval) or pii.PHONE_RE.search(qval):
                continue
            norm_key = qkey.lower()
            g = query_key_groups.setdefault(norm_key, {
                "severity": "Critical" if is_strong else "High", "count": 0, "pv": 0,
            })
            g["count"] += 1
            g["pv"] += pv

    out: list[dict] = []
    for g in token_groups.values():
        out.append(_v(
            counter, g["severity"], "個人情報の混入", f"{g['prefix']}/****",
            f"ページパス `{g['prefix']}/` 配下に、トークンらしき値がそのまま記録されている"
            f"URLが{g['count']:,}件、計{g['pv']:,}PVある（例: `{g['example']}`）。"
            "パスワード再設定・認証・招待などに見えるディレクトリ名の直後に、"
            "20文字以上で英字・数字が混在する値が来ており、記事ID・商品IDとは考えにくい。"
            "GA4に記録されると、GA4の閲覧権限を持つ全員がこの値を読める状態になり、"
            "GA4の利用規約が禁じる「個人を特定できる情報の送信」に抵触するおそれがある",
            "該当のURL設計を見直し、トークンをパスに含めない形にする"
            "（値をハッシュ化する、POSTボディ・Cookie経由でやり取りする等）。"
            "あわせてGA4管理画面のユーザーデータ削除リクエストで、記録済みの該当データを消す",
            location="GA4", kind="page", extra=g["prefix"],
        ))
    for section, g in email_groups.items():
        out.append(_v(
            counter, "Critical", "個人情報の混入", f"{section}配下のメールアドレス",
            f"`{section}` 配下のページパスまたはクエリパラメータに、メールアドレスが"
            f"そのまま記録されているURLが{g['count']:,}件、計{g['pv']:,}PVある"
            f"（例: `{g['example']}`）",
            "メールアドレスをURLに含めない設計に変える（内部的な識別子に置き換える）。"
            "あわせてGA4管理画面のユーザーデータ削除リクエストで、記録済みの該当データを消す",
            location="GA4", kind="page", extra=section,
        ))
    for section, g in phone_groups.items():
        out.append(_v(
            counter, "High", "個人情報の混入", f"{section}配下の電話番号らしき値",
            f"`{section}` 配下のページパスまたはクエリパラメータに、電話番号らしき値"
            f"（区切り文字あり）がそのまま記録されているURLが{g['count']:,}件、"
            f"計{g['pv']:,}PVある（例: `{g['example']}`）",
            "電話番号をURLに含めない設計に変える。"
            "あわせてGA4管理画面のユーザーデータ削除リクエストで、記録済みの該当データを消す",
            location="GA4", kind="page", extra=section,
        ))
    for qkey, g in query_key_groups.items():
        out.append(_v(
            counter, g["severity"], "個人情報の混入", f"クエリキー `{qkey}`",
            f"クエリパラメータのキー名 `{qkey}=` を含むURLが{g['count']:,}件、"
            f"計{g['pv']:,}PVある。値の中身を見るまでもなく、このキー名が実測に出ている"
            "時点で個人情報をURLに載せる設計になっている疑いが強い",
            f"`{qkey}` の値に個人情報を入れない設計に変える"
            "（サーバー側のセッション・POSTボディで受け渡す）。"
            "あわせてGA4管理画面のユーザーデータ削除リクエストで、記録済みの該当データを消す",
            location="GA4", kind="page", extra=qkey,
        ))
    return out


def check_duplicate_event_rules(defs: dict, counter: list[int]) -> list[dict]:
    """条件がまったく同じイベント作成ルールが複数無いか。

    ミライズ英会話案件では `診断_スクール` / `診断_オンライン` / `診断_コーチング` の
    3件が同一条件で、実測でも3件とも同数だった。プラン別に分ける意図だったが
    条件に差が無く、**1回のページ表示から3イベントが作られる多重計上**になっていた。
    """
    out: list[dict] = []
    for key, rules in defs.items():
        if not key.startswith("event_create_rules") or not isinstance(rules, list):
            continue
        groups: dict[tuple, list[str]] = defaultdict(list)
        for rule in rules:
            sig = tuple(sorted(
                (str(c.get("field", c.get("field_name", ""))),
                 str(c.get("comparison_type", c.get("comparisonType", ""))),
                 str(c.get("value", "")))
                for c in rule.get("event_conditions", [])
            ))
            if sig:
                groups[sig].append(rule.get("destination_event", ""))
        for sig, dests in groups.items():
            names = [d for d in dests if d]
            if len(names) < 2:
                continue
            # rules の走査順（defs の並び）に依存しないよう固定してから使う。
            names = sorted(names)
            cond_desc = "、".join(f"{f} {c} `{v}`" for f, c, v in sig)
            out.append(_v(
                counter, "High", "多重計上", "、".join(names),
                f"イベント作成ルール {len(names)} 件（{'、'.join(names)}）が"
                f"**まったく同じ条件**（{cond_desc}）で作られている。"
                "1回のページ表示から同時に生成されるため、分岐しておらず多重計上になる",
                "1件に統合する。軸（プラン・店舗など）で分けたいなら、"
                "その軸を表す値を条件に入れるか、パラメータで持たせて1イベントにまとめる",
                extra=str(sig),
            ))
    return out


def check_enhanced_measurement_disabled(prop: dict, counter: list[int]) -> list[dict]:
    """拡張計測が実質すべて無効になっていないか。

    ストリームの有効化以外が全部オフだと、スクロール・離脱クリック・
    フォーム操作・サイト内検索・動画・ファイルDLが一切取れない。
    設定画面のスイッチだけで直るのに、気づかれないまま放置されやすい。
    """
    flags = ("scrolls_enabled", "outbound_clicks_enabled", "site_search_enabled",
             "video_engagement_enabled", "file_downloads_enabled",
             "page_changes_enabled", "form_interactions_enabled")
    out: list[dict] = []
    for key, settings in prop.items():
        if not key.startswith("enhanced_measurement") or not isinstance(settings, dict):
            continue
        if not settings.get("stream_enabled"):
            continue
        on = [f for f in flags if settings.get(f)]
        if on:
            continue
        note = ""
        if settings.get("search_query_parameter"):
            note = ("。サイト内検索のクエリパラメータ"
                    f"（`{settings['search_query_parameter']}`）は設定済みだが、"
                    "サイト内検索そのものが無効なので使われていない")
        # 複数ストリームがそれぞれ無効化されている場合、target_name（"拡張計測"）は
        # 共通になるため、ストリームを表す key を識別要素に加えて区別する。
        out.append(_v(
            counter, "High", "計測漏れ", "拡張計測",
            "拡張計測がストリームの有効化以外すべて無効。スクロール・離脱クリック・"
            f"フォーム操作・サイト内検索・動画・ファイルダウンロードが取れていない{note}",
            "管理画面のスイッチで有効化する（当日から溜まり始めるが、過去には遡れない）。"
            "**GA4 が Universal Analytics 経由で送られている場合は有効化しても効かない**ので、"
            "先に基盤タグの実装経路を確認する",
            extra=key,
        ))
    return out


def check_base_tag_trigger(gtm_public: dict, counter: list[int]) -> list[dict]:
    """GA4 の基盤タグ（Googleタグ）が初期化タイミングで発火しているか。

    `gtm.dom`（DOM Ready）や特定のカスタムイベントにしか紐づいていないと、
    それ以前のイベントと、そこに到達しない離脱が計測から落ちる。
    """
    tags = gtm_public.get("tags", [])
    base = [t for t in tags if t.get("function") == "__googtag"]
    if not base:
        return []

    ga4_base = [t for t in base if str(t.get("destination", "")).startswith(("G-", "ルックアップ"))]
    if not ga4_base:
        return []

    initialized = [
        t for t in ga4_base
        if any(f"Event = {ev}" in c for t_conds in [t.get("fire_on", [])] for c in t_conds
               for ev in INITIALIZATION_EVENTS)
    ]
    out = []
    if not initialized:
        whens = "／".join(
            sorted({c for t in ga4_base for c in t.get("fire_on", [])})
        )[:160]
        out.append(_v(
            counter, "Critical", "発火タイミング", "Googleタグ（基盤設定）",
            "GA4の基盤タグが「初期化」「全ページ」のいずれでも発火していない"
            f"（現在の発火条件: {whens}）",
            "基盤タグの発火トリガーを「初期化 - All Pages」に付け替える。"
            "GTMスニペット自体が `<head>` の外にある場合は、あわせて `<head>` の上部へ移す",
            location="GTM", kind="tag",
        ))

    # 測定IDの決め方が混在していないか（片方だけハードコードだと検証環境が混入する）
    literal = {t["index"] for t in ga4_base if str(t.get("destination", "")).startswith("G-")}
    lookup = {t["index"] for t in ga4_base if str(t.get("destination", "")).startswith("ルックアップ")}
    if literal and lookup:
        out.append(_v(
            counter, "High", "発火タイミング", "測定IDの決定方法",
            f"基盤タグの測定IDの決め方が混在している（直接指定 #{sorted(literal)} / "
            f"環境判定 #{sorted(lookup)}）。直接指定側は検証環境からも本番へ送る",
            "すべての基盤タグでホスト名による環境判定に揃える",
            location="GTM", kind="tag",
        ))
    return out


# 完全一致以外で Event を見ているトリガーを表す擬似的な名前（`gtm_public.py` と対応）
ANY_DATALAYER_EVENT = "(すべてのカスタムイベント)"


def check_duplicate_datalayer_fires(gtm_public: dict, counter: list[int]) -> list[dict]:
    """同じ送信先へ同じGA4イベントを重ねて送る候補だけを検出する。

    同じ dataLayer イベントに複数タグがぶら下がること自体は異常ではない。1つの行動から
    用途の異なるイベントを送り分ける構成や、別の送信先へ転送する構成があるためである。
    そこで、次の3条件が揃うグループだけを候補にする。

    * 同じ dataLayer イベントで発火する
    * 送信先が同じ
    * 送信するGA4イベント名が同じ固定値

    `Event`、`DLV:...`、ルックアップ等の動的なイベント名は、静的設定だけでは実際の
    送信名を比較できないので指摘しない。複数トリガーや変数利用だけを不備扱いしないための
    安全策である。最終的な二重計上の確定には、プレビューで同じ操作時の発火を確認する。
    """
    from collections import defaultdict
    by_event: dict[str, list[dict]] = defaultdict(list)
    for t in gtm_public.get("tags", []):
        if t.get("function") not in ("__gaawe", "__googtag"):
            continue
        for ev in t.get("datalayer_events", []):
            by_event[ev].append(t)

    def label(t: dict) -> str:
        return f"`{t.get('event_name') or t.get('type_label')}`(#{t['index']})"

    def is_dynamic(value: str) -> bool:
        value = str(value or "").strip()
        if not value:
            return True
        if value == "Event":
            return True
        markers = (
            "{{", "}}", "DLV:", "URL:", "Cookie:", "DOM:",
            "自動イベント変数:", "カスタムJS", "ルックアップ(", "macro[",
        )
        return any(marker in value for marker in markers)

    def duplicate_groups(tags: list[dict]) -> list[tuple[str, str, list[dict]]]:
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        seen_tags: set[tuple[str, str]] = set()
        for tag in tags:
            # 全イベント条件と専用イベント条件の両方を持つ1本のタグは、照合用リストへ
            # 2回入る。同じタグIDを二重計上して「2本」と誤検出しない。
            tag_index = tag.get("index")
            tag_key = (
                "index", str(tag_index)
            ) if tag_index is not None else ("object", str(id(tag)))
            if tag_key in seen_tags:
                continue
            seen_tags.add(tag_key)
            if tag.get("function") != "__gaawe":
                continue
            event_name = str(tag.get("event_name", "")).strip()
            destination = str(tag.get("destination", "")).strip()
            if is_dynamic(event_name) or is_dynamic(destination):
                continue
            groups[(destination, event_name)].append(tag)
        return [
            (destination, event_name, members)
            for (destination, event_name), members in groups.items()
            if len(members) >= 2
        ]

    out = []
    seen_groups: set[tuple[str, str, tuple[str, ...]]] = set()

    def group_key(destination: str, event_name: str, tags: list[dict]) -> tuple[str, str, tuple[str, ...]]:
        return (
            destination,
            event_name,
            tuple(sorted(str(t.get("index", "")) for t in tags)),
        )

    all_event_tags = by_event.pop(ANY_DATALAYER_EVENT, [])
    individual = {ev: tags for ev, tags in by_event.items() if not ev.startswith("gtm.")}

    # 全イベント対象タグも、本数だけでは不備にしない。同じ固定イベント名・同じ送信先の
    # タグが複数ある場合だけ、全カスタムイベントで重複し得る候補として1件にまとめる。
    for destination, event_name, tags in duplicate_groups(all_event_tags):
        seen_groups.add(group_key(destination, event_name, tags))
        names = " / ".join(label(t) for t in tags)
        out.append(_v(
            counter, "High", "多重発火", "すべてのカスタムイベント",
            f"完全一致ではない条件で、同じ送信先 `{destination}` へ同じイベント "
            f"`{event_name}` を送るタグが{len(tags)}本ある（{names}）。"
            "同じ操作で同時に発火する場合は二重計上になる",
            "GTMプレビューで同じ操作時の発火タグとGA4 DebugViewの受信回数を確認する。"
            "同時発火が確認できた場合だけ、条件を分けるか重複タグを停止する",
            location="GTM", kind="tag",
        ))

    # 専用タグは dataLayer イベント単位に、同じ送信名・送信先のグループだけを見る。
    # 全イベント対象タグは各専用イベントでも発火するため、照合には含める。ただし同じ
    # メンバーの候補を複数回表示しないよう、タグ集合を根本候補のキーとして重複排除する。
    all_event_ids = {t.get("index") for t in all_event_tags}
    for ev, tags in sorted(individual.items(), key=lambda x: -len(x[1])):
        for destination, event_name, members in duplicate_groups([*all_event_tags, *tags]):
            key = group_key(destination, event_name, members)
            if key in seen_groups:
                continue
            seen_groups.add(key)
            names = " / ".join(label(t) for t in members)
            overlap_note = (
                "すべてのカスタムイベント対象タグと専用タグが重なるため、"
                if any(t.get("index") in all_event_ids for t in members)
                else ""
            )
            out.append(_v(
                counter, "Medium", "多重発火", ev,
                f"dataLayer の `{ev}` で、{overlap_note}同じ送信先 `{destination}` へ同じイベント "
                f"`{event_name}` を送るタグが{len(members)}本ある（{names}）。"
                "URL等の追加条件が相互排他なら重複しないため、現時点では候補",
                "GTMプレビューで同じ操作時に両方が発火するか確認する。"
                "同時発火が確認できた場合だけ、条件を分けるか重複タグを停止する",
                location="GTM", kind="tag",
            ))
    return out


# ──────────────────────────────────────
# まとめ
# ──────────────────────────────────────

# Universal Analytics は 2024-07 にデータ処理を停止済み。送っても保存されない。
UA_SHUTDOWN = "2024年7月"

# 操作・閲覧を表すトリガー種別。クリックやスクロールはMCVとして正当なことがあり、
# 種別だけで「成果ではない」と判定してはいけない。キーは正規化した小文字で持つ。
INTERACTION_TRIGGER_TYPES = {
    "scrolldepth": "スクロール",
    "click": "クリック",
    "linkclick": "リンククリック",
    "elementvisibility": "要素の表示",
    "timer": "タイマー",
    "youtubevideo": "動画再生",
}


def _norm_type(value: str) -> str:
    """`scrollDepth` / `SCROLL_DEPTH` / `scroll_depth` を同じキーに寄せる。"""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def check_universal_analytics_tags(gtm: dict, counter: list[int]) -> list[dict]:
    """停止済みの Universal Analytics タグが残っていないか。"""
    ua = [t for t in gtm.get("tags", []) if t.get("type") == "ua"]
    if not ua:
        return []
    # gtm.get("tags", []) の並び順（GTM APIが返した順）に依存しないよう、
    # target_name（IDの素）に使う前にソートして固定する。
    active = sorted(t.get("name", "") for t in ua if not t.get("paused"))
    paused = sorted(t.get("name", "") for t in ua if t.get("paused"))
    out: list[dict] = []
    if active:
        out.append(_v(
            counter, "High", "設定の陳腐化", "、".join(active),
            f"Universal Analytics タグが {len(active)} 本稼働している"
            f"（{'、'.join(active)}）。**Universal Analytics は{UA_SHUTDOWN}に"
            "データ処理を停止済み**で、送っても保存されない",
            "削除する。ただし GA4 側の Google タグが別に設置されていることを"
            "**先に確認する** — UA タグの「GA4 にも送信」経由でしか GA4 に"
            "届いていない場合、消すと GA4 の計測が止まる",
            location="GTM", kind="tag",
        ))
    if paused:
        out.append(_v(
            counter, "Low", "設定の陳腐化", "、".join(paused),
            f"一時停止中の Universal Analytics タグが {len(paused)} 本ある"
            f"（{'、'.join(paused)}）",
            "不要であれば削除する", location="GTM", kind="tag",
        ))
    return out


def _active_ga4_measurement_ids(gtm: dict) -> set[str]:
    """稼働中のタグから、このコンテナが送っている GA4 測定IDを集める。

    見る場所:
      - Google タグ（`googtag`）の `tagId`
      - GA4 イベントタグ（`gaawe`）の `measurementId` と **`measurementIdOverride`**
      - 上記が `{{変数}}` 参照のときは変数の定数値まで辿る

    `gtm.get("measurement_ids")` は一時停止タグを除外せず `measurementIdOverride`
    も見ないため、そのまま使うと
      - 一時停止タグにしか測定IDが無いコンテナ → 検査が飛ばされる
      - イベントタグの上書きにしか測定IDが無いコンテナ → 誤った停止リスク
    のどちらも起きる。
    """
    # **変数の中身は定数だけではない。** ルックアップテーブル（`smm`）で
    # ホスト別に本番／検証を切り替える書き方が普通にあり、その場合 `G-` の値は
    # `map` のリストの中に入る。`value` だけを見ると空になり、
    # 「コンテナに測定IDが無い」と誤判定して偽の停止リスクを出す。
    # **取りこぼす方向が誤検知になるので、変数定義の中を全部走って集める。**
    def _collect_ids(node) -> set[str]:
        found: set[str] = set()
        if isinstance(node, str):
            if node.startswith("G-"):
                found.add(node)
        elif isinstance(node, dict):
            for v in node.values():
                found |= _collect_ids(v)
        elif isinstance(node, list):
            for v in node:
                found |= _collect_ids(v)
        return found

    ids_by_var: dict[str, set[str]] = {}
    for v in gtm.get("variables", []):
        name = v.get("name", "")
        if not name:
            continue
        found = _collect_ids(v.get("parameter", []))
        if found:
            ids_by_var[name] = found

    def _resolve(value: str) -> set[str]:
        value = str(value)
        if value.startswith("{{") and value.endswith("}}"):
            return ids_by_var.get(value[2:-2], set())
        return {value} if value.startswith("G-") else set()

    keys_by_type = {
        "googtag": ("tagId",),
        # `gaawc` は旧世代の「GA4 設定」タグ。古いコンテナではこちらだけで
        # 設置されていることがあり、見落とすと偽の停止リスクを出す。
        "gaawc": ("measurementId",),
        "gaawe": ("measurementId", "measurementIdOverride"),
    }
    ids: set[str] = set()
    for tag in gtm.get("tags", []):
        if tag.get("paused"):
            continue
        keys = keys_by_type.get(tag.get("type", ""))
        if not keys:
            continue
        params = {p.get("key"): p.get("value") for p in tag.get("parameter", [])}
        for key in keys:
            ids |= _resolve(params.get(key, "") or "")
    return ids


def check_ga4_via_ua_bridge(gtm: dict, prop: dict, counter: list[int],
                            quality: dict | None = None) -> list[dict]:
    """GA4 の測定IDが GTM に無く、UA タグ経由で送られていないか。

    ミライズ英会話案件の上流原因。プロパティ側の測定IDがコンテナのどこにも無いのに
    データが入っている場合、UA タグの「GA4 にも送信」（`enableGA4Schema`）で
    橋渡しされている。この経路では **gtag.js 本来のローダーを通らない**ため、
    拡張計測もエンゲージメント時間も働かない。UA の配信が終われば全量止まる。

    **複数ストリームのプロパティでは、見ているコンテナが担当していない
    ストリームまで巻き込まないようにする。** 別サイト用のストリームが
    別コンテナや直書きで実装されている場合、それを「停止リスク」として
    挙げるのは誤報になる。ストリームの `default_uri` のホストが実測の
    ホスト名一覧に現れるものだけを対象にする。
    """
    # **`measurement_ids` をそのまま信用しない。** あれは補助的な抽出結果で、
    # 一時停止タグを除外せず、GA4 イベントタグの `measurementIdOverride` も見ない。
    # ここは「いま実際にこのコンテナから送られている宛先」が要るので、
    # 稼働中の生タグから取り直す（見落とすと誤った停止リスクを出す）。
    ids = _active_ga4_measurement_ids(gtm)

    streams = [s for s in prop.get("data_streams", [])
               if s.get("web_stream_data", {}).get("measurement_id")]
    measured_hosts = {
        str(h.get("hostName", "")).lower()
        for h in (quality or {}).get("hosts", [])
        if h.get("hostName") and not str(h.get("hostName", "")).startswith("(")
    }

    def _host_of(stream: dict) -> str:
        uri = stream.get("web_stream_data", {}).get("default_uri", "")
        return re.sub(r"^https?://", "", str(uri)).strip("/").lower()

    # 実測ホストと結びつくストリームに絞る。ホスト名が取れていない場合
    # （07 未取得）は絞れないので、ストリームが1本だけのときに限って続行する。
    if measured_hosts:
        target = [s for s in streams
                  if any(_host_of(s) == h or h.endswith("." + _host_of(s))
                         or _host_of(s).endswith("." + h)
                         for h in measured_hosts if _host_of(s))]
    else:
        target = streams if len(streams) == 1 else []

    own = {s["web_stream_data"]["measurement_id"] for s in target}
    missing = sorted(own - ids)
    if not missing or not ids and not gtm.get("tags"):
        return []
    multi_note = (
        f"（このプロパティには web ストリームが{len(streams)}本ある。"
        "見ているコンテナが担当していないストリームは対象外にしている）"
        if len(streams) > 1 else ""
    )
    ua_active = [t.get("name", "") for t in gtm.get("tags", [])
                 if t.get("type") == "ua" and not t.get("paused")]
    if not ua_active:
        return []
    names = "、".join(f"`{m}`" for m in missing)
    # **断定しない。** このコンテナに測定IDが無い理由は UA ブリッジだけではない。
    #  - ページに `gtag.js` が直書きされている
    #  - 別の GTM コンテナが同じページで動いている
    # のどちらでも `own - ids` は空にならない。
    # 実案件（ミライズ英会話）で確定できたのは、`analytics.js` の読み込みを
    # 遮断して当該測定IDへのヒットが消えることを実機で確かめたからで、
    # データだけからは切り分けられない。**確認手順を必ず添える。**
    return [_v(
        counter, "High", "計測の停止リスク", "、".join(missing),
        f"このプロパティの測定ID {names} が GTM コンテナに存在しないのに、"
        f"データは入っている{multi_note}。送信経路の候補は3つ。"
        f"(1) 稼働中の Universal Analytics タグ（{'、'.join(ua_active)}）の"
        "「GA4 にも送信」経由 "
        "(2) ページに Google タグが直書きされている "
        "(3) 別の GTM コンテナが動いている。"
        f"**(1) だった場合、Universal Analytics は{UA_SHUTDOWN}に停止済みなので、"
        "配信が終わった時点でこのプロパティのデータは全量止まる**"
        "（止まってもエラーは出ず、数字が0になるだけ）",
        "**まず経路を確定させる。** ブラウザで対象サイトを開き、"
        "`google-analytics.com/analytics.js` の読み込みだけを遮断して、"
        f"{names} へのヒットが消えるかを見る（消えれば (1)）。"
        "ページの HTML と読み込まれている GTM コンテナIDも併せて確認する。"
        f"(1) と分かったら {'、'.join(missing)} の Google タグを GTM に直接置き"
        "（初期化トリガーで1本）、そのうえで UA タグを削除する。"
        "**経路が確定するまで UA タグを消さない**",
        location="GTM", kind="tag",
    )]


# トリガーグループの種別名（正規化後）。
TRIGGER_GROUP_TYPE = "triggergroup"


def _trigger_group_members(trigger: dict) -> set[str]:
    """トリガーグループが参照しているメンバートリガーのIDを返す。

    GTM API v2 では、グループの `parameter` に `triggerIds` というリストが入り、
    各要素が `{"type": "triggerReference", "value": "<id>"}` の形になる。
    タグ側の `firingTriggerId` にはグループのIDしか出てこないため、
    ここを解かないと
      - 成果定義の検査がグループ経由のスクロール／クリックを見逃す
      - 未使用トリガーの検査がメンバーを「未使用」として削除を勧める
    の両方が起きる（後者は生きている依存を消させてしまう）。
    """
    members: set[str] = set()

    def _walk(node) -> None:
        if isinstance(node, dict):
            val = node.get("value")
            if isinstance(val, str) and val and node.get("type") == "triggerReference":
                members.add(val.strip("{} "))
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for prm in trigger.get("parameter", []):
        if prm.get("key") in ("triggerIds", "triggerIdList"):
            _walk(prm)
    return members


def _expand_triggers(trigger_by_id: dict, tid: str, _depth: int = 0) -> set[str]:
    """トリガーIDを、実際に発火を決めるトリガーIDの集合に展開する。

    グループならメンバーへ降りる。入れ子と循環参照に備えて深さを制限する。
    """
    trig = trigger_by_id.get(tid)
    if trig is None or _depth >= 5:
        return {tid}
    if _norm_type(trig.get("type", "")) != TRIGGER_GROUP_TYPE:
        return {tid}
    members = _trigger_group_members(trig)
    if not members:
        return {tid}
    out: set[str] = set()
    for m in members:
        out |= _expand_triggers(trigger_by_id, m, _depth + 1)
    return out


def _referenced_triggers(trigger_by_id: dict, tid: str, _depth: int = 0) -> set[str]:
    """`tid` から辿れるトリガーIDを、**中間のグループも含めて**返す。

    `_expand_triggers` は「実際に発火を決める葉」だけを返す。
    未使用トリガーの判定にそれを使うと、入れ子のグループ
    （タグ → グループA → グループB → 実トリガー）で**中間のBが
    未使用として挙がり、削除を勧めてしまう**。B を消すと A が壊れる。
    """
    out = {tid}
    trig = trigger_by_id.get(tid)
    if trig is None or _depth >= 5:
        return out
    if _norm_type(trig.get("type", "")) != TRIGGER_GROUP_TYPE:
        return out
    for m in _trigger_group_members(trig):
        out |= _referenced_triggers(trigger_by_id, m, _depth + 1)
    return out


def _resolve_constant(value: str, variables_by_name: dict, _depth: int = 0) -> str | None:
    """変数参照を辿り、**定数（type `c`）のときだけ**リテラル値まで解決する。

    ルックアップテーブル（`smm`）やカスタムJS（`jsm`）は実行時の入力（ホスト名など）
    によって値が変わるため、値を1つに決め切れない。そこまで解決しようとすると、
    たまたま候補の1つが一致しただけで「同じ」と誤判定するおそれがある
    （逆に本当は同じ値を指しているのに候補が食い違って「違う」と見落とすおそれもある）。
    定数以外は解決できないもの（`None`）として扱い、呼び出し側に
    「判定できない」と正直に出させる。
    """
    value = str(value)
    if not (value.startswith("{{") and value.endswith("}}")):
        return value or None
    if _depth >= 5:
        return None
    name = value[2:-2].strip()
    var = variables_by_name.get(name)
    if var is None or var.get("type") != "c":
        return None
    params = {p.get("key"): p.get("value") for p in var.get("parameter", []) or []}
    inner = params.get("value")
    if inner is None:
        return None
    return _resolve_constant(inner, variables_by_name, _depth + 1)


def check_duplicate_ad_conversion_labels(gtm: dict, counter: list[int]) -> list[dict]:
    """同じコンバージョンID・ラベルの組み合わせが複数の広告タグに設定されていないか。

    重複していると、1回の成果が広告側で多重にカウントされ、入札の自動調整が
    実際より多い成果数を前提に動く。

    **値が変数参照のときは、定数（type `c`）まで解決できたときだけ比較する。**
    ルックアップテーブルなど実行時に値が変わる変数は「同じ」と決め打ちできないため、
    比較せず別枠の `判定不能` として報告し、○（問題なし）と混同しない
    （`_resolve_constant` を参照）。
    """
    variables_by_name = {v.get("name"): v for v in gtm.get("variables", []) if v.get("name")}
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    unresolved: list[str] = []
    for t in gtm.get("tags", []):
        if t.get("type") != "awct" or t.get("paused"):
            continue
        params = {p.get("key"): p.get("value") for p in t.get("parameter", []) or []}
        raw_id = params.get("conversionId")
        raw_label = params.get("conversionLabel")
        # 片方でも未設定なら組み合わせが作れない。B-1はラベルの重複だけを見る
        # （どちらか欠けている設定不備は、この検査の対象外）。
        if not raw_id or not raw_label:
            continue
        name = t.get("name", "")
        cid = _resolve_constant(raw_id, variables_by_name)
        label = _resolve_constant(raw_label, variables_by_name)
        if cid is None or label is None:
            unresolved.append(name)
            continue
        groups[(cid, label)].append(name)

    out: list[dict] = []
    for (cid, label), names in groups.items():
        if len(names) < 2:
            continue
        # gtm.get("tags", []) の並び順に依存しないよう固定してから使う。
        names = sorted(names)
        out.append(_v(
            counter, "High", "多重計上", "、".join(names),
            f"Google広告のコンバージョンタグ{len(names)}本（{'、'.join(names)}）が"
            f"同じコンバージョンID・ラベル（`{cid}` / `{label}`）で発火する。"
            "1回の成果が広告側で多重にカウントされ、入札の最適化が実際より多い"
            "成果数を前提に動く",
            "1本に統合する。プラン別・店舗別などに分けたい意図があるなら、"
            "Google Ads側で別のコンバージョンラベルを発行してから分岐させる",
            location="GTM", kind="tag", extra=f"{cid}|{label}",
        ))
    if unresolved:
        names = "、".join(sorted(set(unresolved)))
        out.append(_v(
            counter, "Low", "判定不能", names,
            f"広告コンバージョンタグ{len(set(unresolved))}本のコンバージョンID・ラベルが"
            f"変数参照で、定数まで解決できない（{names}）。他のタグと重複していないか判定できない",
            "変数の中身（ルックアップテーブル等）を確認し、実際に配信される値を"
            "目視で突き合わせる",
            location="GTM", kind="tag",
        ))
    return out


def resolve_gaawe_event_names(gtm: dict) -> tuple[dict[str, list[dict]], list[str]]:
    """稼働中の `gaawe`（GA4イベント）タグを、解決した `eventName` でグルーピングする。

    実データの測定IDと同じで、`eventName` もリテラルではなく変数参照のことがある。
    `_resolve_constant` で定数まで解決できたものだけをキーにまとめ、
    解決できなかったタグ名は別に返す（判定できないと正直に出すため）。
    """
    variables_by_name = {v.get("name"): v for v in gtm.get("variables", []) if v.get("name")}
    by_event: dict[str, list[dict]] = defaultdict(list)
    unresolved: list[str] = []
    for t in gtm.get("tags", []):
        if t.get("type") != "gaawe" or t.get("paused"):
            continue
        params = {p.get("key"): p.get("value") for p in t.get("parameter", []) or []}
        raw_name = params.get("eventName", "")
        if not raw_name:
            continue
        resolved = _resolve_constant(raw_name, variables_by_name)
        if resolved is None:
            unresolved.append(t.get("name", ""))
            continue
        by_event[resolved].append(t)
    return by_event, unresolved


def check_non_outcome_key_events(events: dict, gtm: dict, counter: list[int]) -> list[dict]:
    """GA4キーイベントのうち、クリック型MCVの発火範囲が広すぎないか。

    GA4のキーイベント自体（`gaawe`）を対象にする。02-events.json の `key_events` を
    GTMの `gaawe` タグへ `eventName` で橋渡しし、そのタグの発火トリガーの種別を見る。

    **クリック・スクロール等の種別だけでは異常にしない。** リンククリックはMCVとして
    妥当な場合がある。機械で指摘するのは、クリック系トリガーに絞り込み条件が無く、
    全クリックを数える可能性がある場合だけ。登録解除や完了ページ除外は勧めず、役割と
    対象範囲の確認を促す。

    **GTMに対応するタグが見つからない＝異常ではない。** GA4管理画面のイベント作成ルール・
    gtag直書き・サイト側の実装など、GTM経由でない構成がありうる。ここでは該当タグが
    無いキーイベントは黙ってスキップし（＝異常として報告しない）、判定表側
    （`audit_matrix._judge_non_outcome_key_events`）で「GTMからは確認できない」と
    中立的に書き分ける。
    """
    trigger_by_id = {t.get("triggerId"): t for t in gtm.get("triggers", [])}
    trig_type = {t.get("triggerId"): (t.get("type", ""), t.get("name", ""))
                 for t in gtm.get("triggers", [])}
    trig_has_filter = {
        t.get("triggerId"): any(t.get(key) for key in ("filter", "customEventFilter", "autoEventFilter"))
        for t in gtm.get("triggers", [])
    }
    by_event, unresolved = resolve_gaawe_event_names(gtm)

    key_events = [
        k.get("event_name", k.get("eventName", ""))
        for k in events.get("key_events") or []
    ]
    key_events = [k for k in key_events if k and k not in DEFAULT_NOISE_KEY_EVENTS]

    out: list[dict] = []
    for name in key_events:
        for t in by_event.get(name, []):
            expanded: list[str] = []
            for raw_tid in t.get("firingTriggerId", []):
                # トリガーグループは「クリック AND 別条件」のような構成を持ち得る。
                # 葉のクリックだけへ展開すると、グループ全体の条件を失って
                # 「無条件の全クリック」と誤報するため、この検査では直接指定だけを見る。
                trigger = trigger_by_id.get(raw_tid, {})
                if _norm_type(trigger.get("type", "")) == TRIGGER_GROUP_TYPE:
                    continue
                if raw_tid not in expanded:
                    expanded.append(raw_tid)
            for tid in expanded:
                ttype, tname = trig_type.get(tid, ("", ""))
                normalized_type = _norm_type(ttype)
                label = INTERACTION_TRIGGER_TYPES.get(normalized_type)
                # スクロール・動画・要素表示等はMCVになり得る。クリックも対象リンクを
                # 絞っていれば正常なので、種別だけでは指摘しない。
                if normalized_type not in {"click", "linkclick"} or trig_has_filter.get(tid):
                    continue
                # 同じキーイベントに複数のタグ・トリガーが絡む場合があるため、
                # タグ名とトリガー名を識別要素に加える。
                out.append(_v(
                    counter, "Low", "発火範囲の確認", name,
                    f"キーイベント「{name}」に対応するGA4イベントタグ「{t.get('name', '')}」が"
                    f"{label}トリガー「{tname}」で発火しているが、対象リンクを絞る条件が"
                    "見当たらない。クリック型MCVとしては成立し得るものの、全クリックを"
                    "数えている可能性がある",
                    "このクリックをMCVとして使う意図を確認する。意図どおりなら維持し、"
                    "対象リンクを限定する必要があれば Click URL・Click ID 等の条件を追加する",
                    location="GTM", kind="tag", extra=f"{t.get('name', '')}|{tname}",
                ))
    if unresolved:
        names = "、".join(sorted(set(unresolved)))
        out.append(_v(
            counter, "Low", "判定不能", names,
            f"GA4イベントタグ{len(set(unresolved))}本の `eventName` が変数参照で、"
            f"定数まで解決できない（{names}）。どのキーイベントに対応するか判定できない",
            "変数の中身を確認し、キーイベントとの対応を目視で突き合わせる",
            location="GTM", kind="tag",
        ))
    return out


# ──────────────────────────────────────
# 流入計測の指摘（audit_matrix.py から一本化）
#
# 元々 audit_matrix.py の判定関数（`_judge_referral_exclusion` 等）だけが持っていた
# ロジックで、×判定でも check-report の指摘（§4健全性検出・改善ロードマップ）を
# 一切作っていなかった。**「見た項目と判定」の表にだけ現れて、直す手順にはどこにも
# 出てこない**という不整合が試用フィードバックで見つかったため、判定を作る側の
# ロジックをここに移し、判定表側は結果を呼ぶだけにする（`check_non_production_hosts`
# と同じ形）。
# ──────────────────────────────────────

def check_self_referral(prop: dict, traffic: dict, counter: list[int]) -> list[dict]:
    """自社ドメインが参照元（referral）として計上されていないか。

    **末尾2ラベルで比べない。** `www.example.jp` と `www.example.co.jp` は
    末尾2つが `example.jp` と `co.jp` になって一致せず、自社内の移動を見逃す
    （実測で月2,000セッション超の事故があった）。`www.` を外した先頭のラベル
    （ブランド名）で見る。
    """
    uri = ((prop.get("data_streams") or [{}])[0].get("web_stream_data") or {}).get("default_uri", "")
    host = re.sub(r"^https?://", "", uri).strip("/").lower()
    rows = traffic.get("source_medium") or []
    if not host or not rows:
        return []
    labels = [x for x in host.split(".") if x not in ("www", "")]
    brand = labels[0] if labels else ""
    own = [
        r for r in rows
        if brand and brand in str(r.get("sessionSource", "")).lower()
        and str(r.get("sessionMedium", "")) == "referral"
    ]
    if not own:
        return []
    total = sum(int(r.get("sessions", 0) or 0) for r in own)
    sources = "、".join(sorted({str(r.get("sessionSource", "")) for r in own}))
    return [_v(
        counter, "High", "自己参照", "参照元除外リスト",
        f"自社ドメインからの移動が参照(referral)として計上されている（{sources}・月{total:,}セッション）",
        "GA4管理画面のデータ設定→参照元除外リストに自社ドメインを追加する",
    )]


def check_cross_domain_referral_candidates(
    quality: dict, traffic: dict, counter: list[int],
) -> list[dict]:
    """計測対象ホスト由来の referral を、クロスドメイン確認候補として出す。

    予約・決済・オンラインサービス等のドメインを利用者へ事前質問するのではなく、
    GA4で実際に受信した主要 ``hostName`` を対象候補にする。単発の開発ホストやbotを
    候補にしないため、全体の1%未満・検証環境・``(not set)`` は除外する。ただし、
    hostName集計とsource/medium集計だけでは実際のホスト間遷移やセッション分断を
    直接確認できないため、不備とは断定しない。
    """
    rows = quality.get("hosts") or []
    total = sum(int(row.get("sessions", 0) or 0) for row in rows)
    if not total:
        return []
    hosts = []
    for row in rows:
        host = str(row.get("hostName", "")).strip().lower()
        sessions = int(row.get("sessions", 0) or 0)
        if (
            not host or host == "(not set)" or NON_PRODUCTION_HOST_RE.search(host)
            or sessions < total * 0.01
        ):
            continue
        hosts.append(host)
    hosts = sorted(set(hosts))
    if len(hosts) <= 1:
        return []

    hits = []
    for row in traffic.get("source_medium") or []:
        if str(row.get("sessionMedium", "")).strip().lower() != "referral":
            continue
        source = str(row.get("sessionSource", "")).strip().lower()
        if any(source == host or source.endswith("." + host) for host in hosts):
            hits.append(row)
    if not hits:
        return []

    sessions = sum(int(row.get("sessions", 0) or 0) for row in hits)
    sources = "、".join(sorted({str(row.get("sessionSource", "")) for row in hits}))
    return [_v(
        counter, "Medium", "クロスドメイン計測", "・".join(hosts),
        f"複数の主要ホスト（{'・'.join(hosts)}）を計測しており、そのうち計測対象ホスト由来の"
        f"referral が月{sessions:,}セッションある（{sources}）。予約・決済・オンラインサービス等の"
        "実際のホスト間遷移によるものか、過去の参照元帰属や別導線によるものかはこの集計だけでは未確定",
        "対象ホスト間の導線、同じWebストリーム・タグIDの利用状況、実ブラウザ遷移時の"
        "クライアントIDとセッション継続を確認する。分断を再現できた場合だけ、"
        "クロスドメイン設定や不要な参照元の修正要否を判断する",
    )]


def check_unknown_medium_values(traffic: dict, counter: list[int]) -> list[dict]:
    """GA4自身が既定チャネルへ分類できなかった流入が多い場合だけ指摘する。

    関数名は既存呼び出しとの互換のため残しているが、独自のmedium語彙との比較は行わない。
    GA4の公式チャネル定義は更新されるため、取得した `sessionDefaultChannelGroup` が
    `Unassigned` かどうかを根拠にする。チャネル値を取得していない旧データでは判定しない。
    """
    rows = traffic.get("source_medium") or []
    if not rows:
        return []
    if not any("sessionDefaultChannelGroup" in row for row in rows):
        return []

    total = sum(int(row.get("sessions", 0) or 0) for row in rows)
    unassigned_rows = [
        row for row in rows
        if str(row.get("sessionDefaultChannelGroup", "")).strip().lower()
        in {"unassigned", "(not set)"}
    ]
    unassigned = sum(int(row.get("sessions", 0) or 0) for row in unassigned_rows)
    if (
        not total
        or unassigned < UNASSIGNED_MIN_SESSIONS
        or unassigned / total <= UNASSIGNED_SESSION_RATIO
    ):
        return []

    top = sorted(
        unassigned_rows,
        key=lambda row: -int(row.get("sessions", 0) or 0),
    )[:4]
    examples = "・".join(
        f"{row.get('sessionSource') or '(not set)'} / "
        f"{row.get('sessionMedium') or '(not set)'}（{int(row.get('sessions', 0) or 0):,}）"
        for row in top
    )
    ratio = unassigned / total
    return [_v(
        counter, "High" if ratio >= 0.05 else "Medium", "流入分類", "Unassigned",
        f"GA4の既定チャネルで未分類の流入が{unassigned:,}セッション（{ratio:.1%}）ある"
        f"（主な内訳: {examples}）",
        "該当source / mediumをGoogleの既定チャネルグループ定義と照合する。"
        "媒体側の自動タグまたはUTM値を直し、変更後にUnassignedが減ったことを確認する",
    )]


def check_foreign_noise(quality: dict, counter: list[int]) -> list[dict]:
    """海外からの機械的アクセスを、国ではなく複数の行動信号で疑う。

    海外流入や特定国名だけでは異常にしない。国別セッションがサイト全体へ異常に集中し、
    かつ平均エンゲージメント時間・直帰率・キーイベント率のうち2つ以上が極端な場合だけ
    「機械的アクセスの疑い」とする。ブラウザ×OSの偏りは説明用の補助根拠であり、判定条件
    には使わない。除外はサーバー/CDN/WAFログで確認した後に行う。
    """
    countries = quality.get("countries") or []
    country_env = quality.get("country_environment") or []
    total = sum(int(r.get("sessions", 0) or 0) for r in countries)
    if not total or not country_env:
        return []
    by_country: dict[str, list[dict]] = {}
    for r in country_env:
        by_country.setdefault(str(r.get("country", "")), []).append(r)

    site_key_events = sum(int(r.get("keyEvents", 0) or 0) for r in countries)
    site_rate = site_key_events / total
    site_engagement = sum(float(r.get("userEngagementDuration", 0) or 0) for r in countries) / total
    suspicious, names = 0, []
    for row in countries:
        country = str(row.get("country", ""))
        sessions = int(row.get("sessions", 0) or 0)
        if (
            country in ("Japan", "日本", "(not set)", "")
            or sessions < FOREIGN_MIN_SESSIONS
            or sessions < total * FOREIGN_MIN_SESSION_RATIO
        ):
            continue
        key_events = int(row.get("keyEvents", 0) or 0)
        rate = key_events / sessions if sessions else 0
        engagement_raw = row.get("userEngagementDuration")
        engagement = (
            float(engagement_raw or 0) / sessions
            if sessions and engagement_raw not in (None, "")
            else None
        )
        bounce_raw = row.get("bounceRate")
        try:
            bounce_rate = float(bounce_raw) if bounce_raw not in (None, "") else None
        except (TypeError, ValueError):
            bounce_rate = None

        signals: list[str] = []
        low_engagement = (
            engagement is not None
            and engagement <= FOREIGN_MAX_AVG_ENGAGEMENT_SECONDS
            and (not site_engagement or engagement <= site_engagement * FOREIGN_ENGAGEMENT_SITE_RATIO)
        )
        if low_engagement:
            signals.append(f"平均エンゲージメント{engagement:.1f}秒")
        if bounce_rate is not None and bounce_rate >= FOREIGN_MIN_BOUNCE_RATE:
            signals.append(f"直帰率{bounce_rate:.1%}")
        if key_events == 0 or (site_rate and rate <= site_rate / FOREIGN_RATE_DIVISOR):
            signals.append(f"キーイベント{key_events:,}件")
        if len(signals) < FOREIGN_MIN_SIGNALS:
            continue
        group = by_country.get(country) or []
        group_total = sum(int(r.get("sessions", 0) or 0) for r in group)
        top = max(group, key=lambda r: int(r.get("sessions", 0) or 0), default=None)
        share = (int(top.get("sessions", 0) or 0) / group_total) if (top and group_total) else 0
        env_label = f"{top.get('browser', '')}/{top.get('operatingSystem', '')} {share:.0%}" if top else ""
        suspicious += sessions
        detail = "・".join(signals)
        if env_label:
            detail += f"・最大環境{env_label}"
        names.append(f"{country}{sessions:,}（{detail}）")
    if not suspicious:
        return []
    return [_v(
        counter, "Medium", "アクセス品質", "機械的アクセスの疑い",
        f"特定地域へ集中し行動品質の異常が重なるセッションが月{suspicious:,}件"
        f"（{suspicious / total:.1%}・{'／'.join(names[:3])}）",
        "国名だけでは除外しない。サーバー、CDNまたはWAFログで発信元とUser-Agentを確認し、"
        "機械的アクセスと確認できた範囲だけを除外する",
    )]


def check_form_measurement_gap(events: dict, counter: list[int]) -> list[dict]:
    """フォーム到達を計測できているか。

    BtoBサイトではフォームページ閲覧を分母にした通過率を既定とする。`form_start` は
    取得できれば精度を上げられる補助指標だが、未取得だけで不備にしない。フォーム閲覧も
    入力開始も見当たらない場合だけ、フォームURLを利用者へ確認する必要があると知らせる。
    """
    ev = {r.get("eventName", ""): int(r.get("eventCount", 0) or 0) for r in events.get("events_30d", [])}
    if ev.get("form_start", 0):
        return []
    viewed = sum(c for n, c in ev.items() if "form" in n.lower() or "フォーム" in n)
    if viewed:
        return []
    return [_v(
        counter, "Medium", "フォーム到達未確認", "フォームページ",
        "フォームページの閲覧またはフォーム到達イベントを確認できない",
        "フォームURLを利用者に確認し、ページ閲覧を分母、確認済みの完了イベントを分子として"
        "通過率を計算する。入力開始イベントは必要な場合だけ追加する",
    )]


def check_unused_triggers(gtm: dict, counter: list[int]) -> list[dict]:
    """どのタグからも使われていないトリガーが残っていないか。

    `normalizer` が `orphans.triggers_without_tag` として算出しているが、
    LLM プロンプトにしか渡っておらず `--no-llm` では見えないため、
    機械検出としても出す。発火するだけで受け手が無いトリガーは処理の無駄。
    """
    trigger_by_id = {t.get("triggerId"): t for t in gtm.get("triggers", [])}
    used: set[str] = set()
    for t in gtm.get("tags", []):
        for tid in list(t.get("firingTriggerId", []) or []) +                 list(t.get("blockingTriggerId", []) or []):
            # **グループのメンバーも中間グループも使用中に数える。** タグ側には
            # グループのIDしか出てこないため、解かないと生きている依存を
            # 「未使用」として削除を勧めてしまう。
            used |= _referenced_triggers(trigger_by_id, tid)
    # gtm.get("triggers", []) の並び順に依存しないよう固定してから使う。
    orphans = sorted(t.get("name", "") for t in gtm.get("triggers", [])
                      if t.get("triggerId") not in used)
    if not orphans:
        return []
    return [_v(
        counter, "Low", "残骸候補", "、".join(orphans),
        f"どのタグからも使われていないトリガーが {len(orphans)} 件ある"
        f"（{'、'.join(orphans)}）。スクロールや要素表示のトリガーは"
        "受け手が無くてもページ側で判定が走り続ける",
        "使う予定が無ければ削除する", location="GTM", kind="trigger",
    )]


def load_gtm_api(data_dir: Path) -> dict:
    """GTM API で取得した `09-gtm.json` を読む（公開 gtm.js 由来のものは除く）。

    `_load(data_dir, "09")` は辞書順で先に来る `09-gtm-public.json` を返してしまう。
    タグ名・トリガー種別が要る検査は API 版だけを対象にする。

    `audit_matrix.load_datasets` も `ds["gtm_api"]` としてこれを使う（UA経由・
    キーイベントの発火条件はトリガーIDの構造まで要るため、公開gtm.js形式
    には対応できない。関数名の先頭アンダースコアを外したのはそのため）。
    """
    path = data_dir / "09-gtm.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    # 公開 gtm.js 由来のファイルが同名で置かれていた場合は対象外
    if data.get("source", {}).get("method") == "public_gtm_js":
        return {}
    return data


def health_checks(data_dir: Path) -> list[dict]:
    """`_data/` から実測ベースの不備を検出する。"""
    prop = _load(data_dir, "01")
    events = _load(data_dir, "02")
    defs = _load(data_dir, "03")
    traffic = _load(data_dir, "05")
    pages = _load(data_dir, "06")
    quality = _load(data_dir, "07")
    gtm_public = _load(data_dir, "09")
    gtm_api = load_gtm_api(data_dir)

    counter = [0]
    out: list[dict] = []
    out += check_session_health(events, counter)
    out += check_user_id_collapse(events, counter)
    out += check_event_name_cardinality(events, counter)
    out += check_gtm_internal_events(events, counter)
    out += check_non_production_hosts(quality, counter)
    out += check_self_referral(prop, traffic, counter)
    out += check_cross_domain_referral_candidates(quality, traffic, counter)
    out += check_unknown_medium_values(traffic, counter)
    out += check_foreign_noise(quality, counter)
    out += check_form_measurement_gap(events, counter)
    out += check_dimension_cardinality(quality, counter)
    out += check_spa_tracking_gap(pages, counter)
    # 「成果の条件が現行URLと合っているか」は監査項目自体を廃止したため、
    # URL実績からイベント作成ルールの陳腐化を推定する診断も通常実行しない。
    out += check_event_rule_url_variants(defs, pages, counter, quality)
    out += check_duplicate_page_urls(pages, counter)
    out += check_page_pii(pages, counter)
    out += check_duplicate_event_rules(defs, counter)
    out += check_enhanced_measurement_disabled(prop, counter)
    if gtm_api:
        out += check_ga4_via_ua_bridge(gtm_api, prop, counter, quality)
        out += check_universal_analytics_tags(gtm_api, counter)
        out += check_duplicate_ad_conversion_labels(gtm_api, counter)
        out += check_non_outcome_key_events(events, gtm_api, counter)
        out += check_unused_triggers(gtm_api, counter)
    if gtm_public.get("source", {}).get("method") == "public_gtm_js":
        out += check_base_tag_trigger(gtm_public, counter)
        out += check_duplicate_datalayer_fires(gtm_public, counter)
    # 各 check_* が渡す識別要素の取りこぼしで、別の指摘が同じIDになった場合の最終防衛。
    return dedupe_ids(out)
