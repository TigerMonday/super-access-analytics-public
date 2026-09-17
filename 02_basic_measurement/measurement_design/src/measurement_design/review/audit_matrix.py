"""監査項目と判定の表を、観点別データセットから組む。

`health_checks` は**不備しか出さない**。それだけでは
「どこまで見たのか」「何が問題なかったのか」が残らず、レポートの章頭に置く
**「見た項目と判定」の1枚**（○確認範囲で問題なし／△要確認／×要修正）を
毎回手で書くことになる（実際の案件でそうなったことがある）。

このモジュールは**計測領域ごとの監査項目**を持ち、データセットから判定を返す。

    from measurement_design.review.audit_matrix import audit_matrix, render_matrix
    rows = audit_matrix(data_dir)
    print(render_matrix(rows))

check-report.md にはこの表をそのまま埋め込む（renderer.build_check_report が
`render_matrix` の結果をそのまま章頭に置く）。単体でこのモジュールだけ確認したいときは
上のとおり直接呼んでよい。

**判定表の行に指摘ID・指摘の参照は付けない。** 以前は `add_violation_references` が
×・△の行の `state` に対応する指摘IDを埋め込んでいたが、レポート内で最初に・一番目立つ形で
読まれる表に指摘IDの羅列が残ることになり、「指摘IDの羅列が多すぎる」「IDいらない」という
試用フィードバックへの対応が判定表にだけ及んでいなかった（§2〜§5・改善ロードマップからは
先に外していた）。いまは行を対象名・カテゴリで引ける（各 `_judge_*` が state 文に対象名や
検出内容を書く設計はそのまま）。指摘IDは内部処理だけに残し、レポートには出さない。

判定の意味は3つだけ。

| 判定 | 意味 |
|---|---|
| `ok` | 記載した確認範囲で問題を検出しない。実動作の保証ではない |
| `warn` | 要確認。未取得・未検証・要件次第・不備の疑いを状態文で区別する |
| `ng` | 取得した根拠から修正が必要と判断できる |

**データから判定できない項目はここに入れない。** 「未使用のプロパティ」「タグ名の重複」
のようにアカウント全体や現物が要るものは `standards/audit-items.md` に
「目視」として書いてある。**表に出したうえで判定を空にすると、見たのか見ていないのかが
分からなくなる**ため、そこは分けている。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from measurement_design.review.ga4_defaults import DEFAULT_NOISE_KEY_EVENTS

# 流入分類は独自のmedium辞書ではなく、GA4が返す `sessionDefaultChannelGroup` の
# `Unassigned` 実績を health_checks.py で判定する。公式定義の更新にローカル辞書が
# 追従できず、正常な値を誤検知するのを避けるためである。
# サイト内の通知・ポップアップに使われがちな medium。外から来た印ではない疑いが濃い。
INTERNAL_MEDIUM_RE = re.compile(r"^(pop|popup|modal|banner_in|inapp|in-app|notice)", re.IGNORECASE)
# 数値だけのキャンペーン名・広告名（媒体が自動で入れるID）
NUMERIC_ONLY_RE = re.compile(r"^\d+$")
# 電話タップを表すイベント名。**「電話」だけで拾わない。**
# 実測で `テレビ電話相談予約`（オンライン相談のフォーム）を電話タップとして拾った。
# 電話番号のリンクを押した、という形（クリック・タップ）まで揃って初めて電話タップ。
TEL_EVENT_RE = re.compile(
    r"(?=.*(?:^tel|[_\-]tel|tel[_\-]|phone|電話|TEL))(?=.*(?:click|tap|クリック|タップ))",
    re.IGNORECASE,
)
# 申込の手前を数えるイベント（GA4 の推奨イベント名。独自名でも部分一致で拾う）
MICRO_EVENT_HINTS = (
    "view_item", "select_item", "add_to_cart", "add_to_wishlist", "add_to_compare",
    "view_form", "form_start", "begin_checkout", "view_search_results",
)
# スクロールの深度を独自イベント名にしている形（`10%` `scroll_50` など）
SCROLL_NAME_RE = re.compile(r"^\d+%$|scroll[_-]?\d+|^\d+percent", re.IGNORECASE)
# GA4 の測定ID
MEASUREMENT_ID_RE = re.compile(r"G-[A-Z0-9]{6,}")

# しきい値。**数字を直書きしない**（根拠を書く場所が無くなる）。
# 未分類の割合: 1% を超えると、月に数千セッション規模でチャネルが読めなくなる
UNCLASSIFIED_SESSION_RATIO = 0.01
# 数値IDだけのキャンペーン名の割合: 3割を超えると、レポートを名前で読めない
NUMERIC_CAMPAIGN_RATIO = 0.3
# 海外ノイズのしきい値（FOREIGN_MIN_SESSION_RATIO・FOREIGN_RATE_DIVISOR）は
# health_checks.py の `check_foreign_noise` に移した（上の KNOWN_MEDIUMS と同じ理由）。
# 「申込の手前」を計測できているとみなす推奨イベントの数
MICRO_EVENT_ENOUGH = 4
# サイト内検索が拾えていないと判断する比（記録が検索結果ページの表示回数の何分の1未満か）
SITE_SEARCH_DIVISOR = 5
# クロスドメイン計測で「ドメイン」として数える最低セッション比（サイト全体比）。
# 開発環境やbotの単発アクセスが1ホストだけ混ざることがあり、それを2本目のドメインと
# 誤って数えると、単一ドメインの案件で存在しない論点（自己参照）を作ってしまう
# （`FOREIGN_MIN_SESSION_RATIO` と同じ考え方）。
CROSS_DOMAIN_MIN_SESSION_RATIO = 0.01

# 外部決済・予約の戻りで参照元として現れやすいサービス。ここに現れた事実だけで
# 除外すべきとは断定せず、実際の購入・予約導線を確認する候補として扱う。
EXTERNAL_CHECKOUT_SOURCE_RE = re.compile(
    r"(?:^|\.)(?:paypal\.com|amazon\.(?:co\.jp|com)|amazonpay\.com|stripe\.com|"
    r"paypay\.ne\.jp|squareup\.com|komoju\.com|sbpayment\.jp|gmo-pg\.com|"
    r"reservation\.jp|reserve\.jp)$",
    re.IGNORECASE,
)

JUDGE_MARK = {"ok": "○", "warn": "△", "ng": "×"}
AREAS = (
    "GA4本体の設定", "広告連携", "GTM", "イベント計測", "流入計測",
    "ページ計測", "カスタム計測", "その他推奨設定事項",
)


def _load(data_dir: Path, stem_prefix: str) -> dict:
    """`_data/<番号>-*.json` を読む。無ければ空 dict。"""
    for path in sorted(data_dir.glob(f"{stem_prefix}-*.json")):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _events(events: dict) -> dict[str, int]:
    return {r.get("eventName", ""): _int(r.get("eventCount")) for r in events.get("events_30d", [])}


def _first(d: dict, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


# ──────────────────────────────────────
# GA4本体の設定・広告連携・GTM
# ──────────────────────────────────────

def _judge_key_events(ds: dict) -> tuple[str, str]:
    """成果（キーイベント）が登録されているか（電話タップの見落としも含む）。

    **発火の有無（0件かどうか）はここでは判定しない。** 旧実装はここと
    `_judge_unused_events`（イベント計測）の両方が「発火0件」という同じ事実から
    別々に×を立てていた（1つの事実に×が2つ立ち、同じことを2回直させる指摘に
    なっていた）。発火の有無は「使われていないイベント」（`_judge_unused_events`）に
    一本化し、ここでは登録そのものの有無と、電話タップのような
    「登録漏れ」（発火はあるのに成果に登録されていない）だけを見る。
    """
    key_events = ds["events"].get("key_events") or []
    if not key_events:
        return "ng", "成果（キーイベント）が1件も登録されていない"

    firing = {r.get("eventName", ""): _int(r.get("eventCount")) for r in ds["events"].get("key_event_firing", [])}
    tel = [n for n in _events(ds["events"]) if TEL_EVENT_RE.search(n) and n not in firing]
    if tel:
        return "ng", f"{len(key_events)}件登録されている。電話タップ（{tel[0]}）が成果に未登録"
    return "ok", f"{len(key_events)}件登録されている（発火の有無は「使われていないイベント」を参照）"


def _judge_internal_traffic(ds: dict) -> tuple[str, str]:
    """検証環境・開発端末が本番プロパティに混ざっていないか。

    判定を作る `check_non_production_hosts` をそのまま呼ぶ（`_judge_url_variants` と
    同じ形）。旧実装はここに同じ正規表現判定を複製して持っており、×でも
    `check_non_production_hosts` 側の指摘（改善ロードマップに載る）と紐付かなかった。
    """
    from measurement_design.review.health_checks import check_non_production_hosts

    rows = ds["quality"].get("hosts") or []
    if not rows:
        return "warn", "受信ホスト名が取れていない"
    found = check_non_production_hosts(ds["quality"], [0])
    if found:
        return _worst_judgement(found), found[0]["description"]

    # データストリームのURLを対象サイトの基準にする。www有無だけは同一とみなし、
    # 主要ホストの1%以上を占める別ホストは「対象外」と断定せず確認候補として出す。
    streams = ds.get("property", {}).get("data_streams") or []
    uri = ((streams[0].get("web_stream_data") or {}).get("default_uri", "") if streams else "")
    target = re.sub(r"^https?://", "", uri).split("/")[0].lower().removeprefix("www.")
    total = sum(_int(row.get("sessions")) for row in rows)
    unexpected = []
    if target and total:
        for row in rows:
            host = str(row.get("hostName", "")).strip().lower()
            sessions = _int(row.get("sessions"))
            normalized = host.removeprefix("www.")
            if (
                host and host != "(not set)" and normalized != target
                and sessions >= total * CROSS_DOMAIN_MIN_SESSION_RATIO
            ):
                unexpected.append((host, sessions))
    if unexpected:
        unexpected.sort(key=lambda item: -item[1])
        labels = "・".join(f"{host}（{sessions:,}）" for host, sessions in unexpected[:4])
        return "warn", (
            f"対象サイト（{target}）以外の主要ホストでも計測されている（{labels}）。"
            "正規のクロスドメイン対象か、除外すべき検証・別サイトかを確認する。"
            "社内アクセスの除外設定・適用状態は別途未確認"
        )
    target_note = f"対象サイト（{target}）以外の主要ホストは見つからない。" if target else ""
    return "warn", target_note + "社内アクセスの除外設定・適用状態は未確認"


def _judge_referral_exclusion(ds: dict) -> tuple[str, str]:
    """自社ドメインが参照元として入っていないか。

    判定を作る `check_self_referral`（末尾2ラベルではなくブランド名で見る。
    `www.example.jp` と `www.example.co.jp` の自社内移動を見逃さないため）を呼ぶ。
    旧実装はここにしかロジックが無く、×でも指摘が作られず改善ロードマップに
    出ない不整合があった（試用フィードバックで検出）。
    """
    from measurement_design.review.health_checks import check_self_referral

    uri = ((ds["property"].get("data_streams") or [{}])[0].get("web_stream_data") or {}).get("default_uri", "")
    host = re.sub(r"^https?://", "", uri).strip("/").lower()
    if not host:
        return "warn", "サイトのURLが取れていない"
    if not ds["traffic"].get("source_medium"):
        return "warn", "流入のデータが取れていない"
    found = check_self_referral(ds["property"], ds["traffic"], [0])
    if found:
        return _worst_judgement(found), found[0]["description"]

    checkout_sources = []
    for row in ds["traffic"].get("source_medium") or []:
        source = str(row.get("sessionSource", "")).strip().lower()
        medium = str(row.get("sessionMedium", "")).strip().lower()
        if medium == "referral" and EXTERNAL_CHECKOUT_SOURCE_RE.search(source):
            checkout_sources.append((source, _int(row.get("sessions"))))
    if checkout_sources:
        checkout_sources.sort(key=lambda item: -item[1])
        labels = "・".join(f"{source}（{sessions:,}セッション）" for source, sessions in checkout_sources[:4])
        return "warn", (
            f"自己参照は見つからないが、外部の決済・予約サービス由来の参照を確認（{labels}）。"
            "購入・予約の完了後に同一セッションが分断されている場合は、該当ドメインを"
            "『除外する参照のリスト』へ追加する"
        )
    return "warn", "取得した流入に自己参照や主要な外部決済サービス参照は見つからない。除外設定は未確認（除外する参照のリスト自体は管理画面で確認）"


def _measured_domains(ds: dict) -> tuple[list[str], int]:
    """`quality.hosts` から、クロスドメインの判定で「ドメイン」として数えるホスト名の一覧を返す。

    `(not set)` と空文字は送信元ホストが取れなかった行で、ドメインではないので除く。
    検証環境・プレビュー環境（`NON_PRODUCTION_HOST_RE`）と、セッション数がサイト全体の
    `CROSS_DOMAIN_MIN_SESSION_RATIO` 未満のホストも、開発端末やbotの単発アクセスの
    疑いが強く、ここでは実在のドメインとして数えない（`check_non_production_hosts` と
    同じ考え方。ただし内部トラフィックそのものの指摘は「内部トラフィックの除外」項目の役割
    なので、ここでは黙って除くだけで別途 ng にはしない）。
    """
    from measurement_design.review.health_checks import NON_PRODUCTION_HOST_RE

    rows = ds["quality"].get("hosts") or []
    total = sum(_int(r.get("sessions")) for r in rows)
    hosts = []
    for r in rows:
        host = str(r.get("hostName", "")).strip().lower()
        if not host or host == "(not set)" or NON_PRODUCTION_HOST_RE.search(host):
            continue
        sessions = _int(r.get("sessions"))
        if total and sessions < total * CROSS_DOMAIN_MIN_SESSION_RATIO:
            continue
        hosts.append(host)
    return hosts, total


def _judge_cross_domain(ds: dict) -> tuple[str, str]:
    """クロスドメイン計測ができているか。

    まず計測しているドメインの数を見る（単一ドメインならこの論点は無い）。複数ドメインなら、
    ドメイン間の移動が参照（`referral`）として計上されていないかを見る。**正しく
    クロスドメイン計測が設定されていれば、ドメインAからBへの遷移は同一セッションのまま
    続き、参照としては現れない。** 現れているなら、セッションが分断されている実害がある。

    **GTM側の設定（`googtag`タグのクロスドメインのドメインリスト）はここでは見ない。**
    実データにも該当パラメータが無く、GTM API v2 の仕様でも `googtag` の内部パラメータの
    キー名が公式に文書化されていない。読めないキー名を推測で決め打ちすると、キー名の
    不一致だけで「設定なし」と誤判定しうる（GA4管理画面で直接設定した場合はGTM側に
    そもそも何も現れない）ため、`standards/audit-items.md` の目視項目に送っている。
    """
    hosts, total = _measured_domains(ds)
    if not total:
        return "warn", "受信ホスト名が取れていない"
    if len(hosts) <= 1:
        label = hosts[0] if hosts else "(不明)"
        return "warn", (
            f"取得範囲で主要ホストは1つ（{label}）。予約・決済等の別ホストはGA4受信データに"
            "現れていないため、クロスドメインの分断はこのデータだけでは判定できない"
        )

    rows = ds["traffic"].get("source_medium") or []
    if not rows:
        return "warn", f"{len(hosts)}ドメインを計測しているが、流入のデータが取れていない"

    domains = "・".join(hosts)
    from measurement_design.review.health_checks import check_cross_domain_referral_candidates
    found = check_cross_domain_referral_candidates(ds["quality"], ds["traffic"], [0])
    if found:
        return "warn", found[0]["description"]
    return "warn", f"{len(hosts)}ドメイン（{domains}）間の自己参照は取得範囲で見つからない。ドメイン間遷移の継続性は未検証"


def _judge_scroll(ds: dict) -> tuple[str, str]:
    enhanced = _first(ds["property"], *[k for k in ds["property"] if k.startswith("enhanced_measurement")]) or {}
    ev = _events(ds["events"])
    own = {n: c for n, c in ev.items() if SCROLL_NAME_RE.search(n)}
    std = ev.get("scroll", 0)
    if own and (enhanced.get("scrolls_enabled") or std):
        return (
            "ok",
            f"標準scroll {std:,}件と独自スクロール{len(own)}種・{sum(own.values()):,}件を受信。"
            "複数の到達率を測る併用は正常な設計として扱う",
        )
    if own:
        return "warn", f"独自のスクロールイベント{len(own)}種。標準機能は使っていない"
    if enhanced.get("scrolls_enabled"):
        if not std:
            return "warn", "標準スクロール計測の設定は有効だがscrollイベントは0件。実操作での受信は未確認"
        return "ok", f"標準機能が有効、scrollイベントを{std:,}件受信。複数の到達率を同じイベント名と識別パラメータで送る設計は許容する"
    return "warn", "スクロールを計測していない"


def _judge_site_search(ds: dict) -> tuple[str, str]:
    enhanced = _first(ds["property"], *[k for k in ds["property"] if k.startswith("enhanced_measurement")]) or {}
    if not enhanced.get("site_search_enabled"):
        return "warn", "サイト内検索の計測がオフ"
    if not ds["events"].get("events_30d") or not ds["pages"].get("pages"):
        return "warn", "イベントまたはページのデータが取れていない"
    hits = _events(ds["events"]).get("view_search_results", 0)
    pages = [p for p in ds["pages"].get("pages", []) if "search" in str(p.get("pagePath", "")).lower()]
    pv = sum(_int(p.get("screenPageViews")) for p in pages)
    if pv and hits < pv / SITE_SEARCH_DIVISOR:
        return "warn", f"パスにsearchを含むページは{pv:,}PV、検索イベントは{hits:,}件。検索結果ページかを確認し、該当する場合は実操作と設定を照合する"
    if not hits:
        return "warn", "検索計測の設定はオンだが検索イベントは0件。検索機能の有無・利用実績・実操作での受信は未確認"
    return "ok", f"検索イベントを{hits:,}件受信。検索語の内容と全検索方式への対応は未検証"


def _judge_form_measurement(ds: dict) -> tuple[str, str]:
    """フォーム到達を、ページ閲覧または入力開始で計測できているか。"""
    from measurement_design.review.health_checks import check_form_measurement_gap

    ev = _events(ds["events"])
    started = ev.get("form_start", 0)
    if started:
        return "ok", f"入力開始を{started:,}件記録している"
    viewed = sum(c for n, c in ev.items() if "form" in n.lower() or "フォーム" in n)
    if viewed:
        return "warn", f"名前にformを含むイベント等を{viewed:,}件受信。実際のフォーム操作との対応・発火条件は未確認"
    found = check_form_measurement_gap(ds["events"], [0])
    return _worst_judgement(found), found[0]["description"]


def _judge_retention(ds: dict) -> tuple[str, str]:
    months = (ds["property"].get("data_retention") or {}).get("event_data_retention", "")
    if months == "FOURTEEN_MONTHS":
        return "ok", "14ヶ月（上限）"
    return "warn", f"{months or '不明'}（上限の14ヶ月にできる）"


def _judge_locale(ds: dict) -> tuple[str, str]:
    prop = ds["property"].get("property") or {}
    tz, cur = prop.get("time_zone", ""), prop.get("currency_code", "")
    if tz and cur:
        return "ok", f"{tz}・{cur}"
    return "warn", "タイムゾーンまたは通貨が未設定"


def _judge_streams(ds: dict) -> tuple[str, str]:
    streams = ds["property"].get("data_streams") or []
    ids = [(s.get("web_stream_data") or {}).get("measurement_id", "") for s in streams]
    if len(streams) == 1:
        return "ok", f"1本（{ids[0]}）"
    if not streams:
        return "ng", "データストリームが無い"
    return "warn", f"{len(streams)}本（{'・'.join(i for i in ids if i)}）"


def _judge_enhanced_measurement(ds: dict) -> tuple[str, str]:
    """Webストリームごとの拡張計測の有効状態を要約する。

    個別機能はサイト要件によるため、オフであることだけを不備にはしない。拡張計測全体が
    無効なら要確認、取得できた場合はオン／オフの内訳を結果として示す。
    """
    settings = [
        value for key, value in ds["property"].items()
        if key.startswith("enhanced_measurement_") and isinstance(value, dict)
    ]
    if not settings:
        return "warn", "拡張計測機能の設定を取得できていない"
    if all(setting.get("error") for setting in settings):
        return "warn", "拡張計測機能の設定取得に失敗している"

    labels = {
        "page_changes_enabled": "ブラウザ履歴に基づくページ変更",
        "scrolls_enabled": "スクロール",
        "outbound_clicks_enabled": "離脱クリック",
        "site_search_enabled": "サイト内検索",
        "form_interactions_enabled": "フォーム操作",
        "video_engagement_enabled": "動画",
        "file_downloads_enabled": "ファイルダウンロード",
    }
    enabled: set[str] = set()
    disabled: set[str] = set()
    stream_enabled = False
    for setting in settings:
        if setting.get("error"):
            continue
        stream_enabled = stream_enabled or bool(setting.get("stream_enabled"))
        for key, label in labels.items():
            (enabled if setting.get(key) else disabled).add(label)

    on = "・".join(sorted(enabled)) or "なし"
    off = "・".join(sorted(disabled)) or "なし"
    state = f"有効: {on}。無効: {off}"
    return ("ok", state) if stream_enabled else ("warn", "拡張計測機能全体が無効。" + state)


def _judge_signals(ds: dict) -> tuple[str, str]:
    state = (ds["property"].get("google_signals") or {}).get("state", "")
    if state == "GOOGLE_SIGNALS_ENABLED":
        return "ok", "有効"
    return "warn", f"{state or '不明'}"


def _judge_user_provided_data(ds: dict) -> tuple[str, str]:
    settings = ds["property"].get("user_provided_data") or {}
    if settings.get("error"):
        return "warn", "ユーザー提供データの設定取得に失敗している"
    if "user_provided_data_collection_enabled" not in settings:
        return "warn", "ユーザー提供データの収集設定を取得できていない"
    enabled = bool(settings.get("user_provided_data_collection_enabled"))
    automatic = bool(settings.get("automatically_detected_data_collection_enabled"))
    if enabled:
        return "ok", f"有効（自動検出は{'有効' if automatic else '無効'}）"
    return "warn", "無効（利用要件・同意条件がある場合のみ有効化を検討）"


def _judge_reporting_identity(ds: dict) -> tuple[str, str]:
    settings = ds["property"].get("reporting_identity") or {}
    if settings.get("error"):
        return "warn", "レポート用識別子の設定取得に失敗している"
    identity = str(settings.get("reporting_identity", ""))
    descriptions = {
        "BLENDED": "User-ID、デバイスID、モデリングを順に使用",
        "OBSERVED": "User-ID、デバイスIDを順に使用",
        "DEVICE_BASED": "デバイスIDだけを使用",
    }
    normalized = next((key for key in descriptions if key in identity), "")
    if not normalized:
        return "warn", "レポート用識別子の設定を取得できていない"
    return "ok", f"{normalized}（{descriptions[normalized]}）"


def _judge_attribution(ds: dict) -> tuple[str, str]:
    a = ds["property"].get("attribution") or {}
    model = a.get("reporting_attribution_model", "")
    if model:
        window = a.get("other_conversion_event_lookback_window", "")
        acquisition = a.get("acquisition_conversion_event_lookback_window", "")
        acquisition_days = re.search(r"(\d+)_DAYS", acquisition)
        other_days = re.search(r"(\d+)_DAYS", window)
        acquisition_label = f"{acquisition_days.group(1)}日" if acquisition_days else (acquisition or "未取得")
        other_label = f"{other_days.group(1)}日" if other_days else (window or "未取得")
        return "ok", f"{'データドリブン' if 'DATA_DRIVEN' in model else model}。新規獲得イベントの参照期間{acquisition_label}、その他イベント{other_label}"
    return "warn", "アトリビューションの設定が取れていない"


def _tag_kind(tag: dict) -> str:
    """タグの種別を、GTM API形式と公開gtm.js形式のどちらでも同じ表記に正規化する。

    GTM API v2（`gtm.py`）はタグの種別を `type` にそのまま持つ（`"awct"` `"gaawe"`
    `"googtag"` `"html"` など）。公開 gtm.js（`gtm_public.py`）は `function` に
    `__` 始まりの関数名で持つ（`"__awct"` `"__gaawe"`）。

    **この2形式を取り違えると、片方の経路でしか動かない判定になる。**
    `_ad_conversion_tags` が実際にこれで壊れていた——`function` しか見ておらず、
    API経由で取得したデータ（`type` しか持たない）では常に0本と数えていた。
    以後はここで表記を揃え、同じ判定を各所に書き直さない。

    **公開gtm.jsの一時停止タグは元の種別を失う。** `gtm_public.py` の仕様上、
    一時停止タグは内容を取得できず `function` が `"__paused"` になる。
    この場合は元の種別が分からないため `"paused"` を返す（API形式の一時停止タグは
    `type` に元の種別が残るので、ここでは変換しない。停止の有無は別途
    `tag.get("paused")` の真偽値で見る）。
    """
    t = tag.get("type")
    if t:
        return str(t)
    fn = tag.get("function")
    if fn:
        fn = str(fn)
        return fn[2:] if fn.startswith("__") else fn
    return ""


def _ad_conversion_tags(ds: dict) -> int:
    """広告コンバージョンのタグ数。`counts` には入っていないのでタグの種類から数える。

    **`counts.ad_conversion_tags` は存在しないキーだった**（codex レビューで検出）。
    無いキーを見ていたため、実データで常に `ok` を返していた。

    **直した先も別スキーマだった。** `function == "__awct"` は公開gtm.js形式専用で、
    GTM API経由（`type == "awct"`）のデータでは相変わらず常に0本になっていた。
    `_tag_kind` で両形式を吸収する。
    """
    return sum(1 for t in ds["gtm"].get("tags") or [] if _tag_kind(t) == "awct")


def _measurement_ids(ds: dict) -> set[str]:
    """GTM の設定に出てくる GA4 の測定ID。

    公開 GTM JSON にトップレベルの `measurement_ids` は無く、各タグの `destination` に
    入っている（codex レビューで検出）。
    """
    ids: set[str] = set()
    for t in ds["gtm"].get("tags") or []:
        values = [t.get("destination")]
        params = t.get("parameters")
        if isinstance(params, dict):
            values.extend(params.values())
        elif isinstance(params, list):
            values.extend(params)
        for value in values:
            ids |= set(MEASUREMENT_ID_RE.findall(str(value or "")))
    return ids


def _judge_ads_links(ds: dict) -> tuple[str, str]:
    """Google広告とリンクされているか（GA4 Admin API の `property.ads_links` だけで判定できる）。

    **GTMのタグ数との突き合わせはこの項目の主眼ではない。** 見ているのは「リンクの有無」
    そのもので、それは `ads_links` だけで分かる。旧実装はGTM未取得（タグ数が確かめられない）
    ことを理由に、リンクがあっても常に△にしていた——GTMが関係ない論点をGTM未取得で
    落としており、リンクありの案件で無意味な△が付いていた（試用フィードバックで検出）。
    リンクがあれば○を確定させ、GTMのタグ数が取れているときだけ「タグ本数がリンク数を
    上回っている（漏れの疑い）」を追加で見る、という主従の順に直す。
    """
    if "ads_links" not in ds["property"]:
        return "warn", "Google広告リンクの一覧が取得できていない"
    links = ds["property"].get("ads_links") or []
    if not links:
        return "warn", "Google広告リンクは0件。広告運用の有無と連携要件を確認して要否を判断する"
    if not ds["gtm"].get("tags"):
        return "ok", f"{len(links)}アカウントとリンク済み"
    tags = _ad_conversion_tags(ds)
    return "ok", f"{len(links)}アカウントとリンク済み。広告タグ{tags}本とのアカウント対応・送信動作は未検証"


# ──────────────────────────────────────
# health_checks の実装済み検出を判定表の1行に変換する
#
# `_judge_url_variants`（見つかれば ng、無ければ ok）が前例。ここでは2点を
# 明文化して広げる。
#
# 1. **1つの検出関数が複数のseverityを返しうる。** 1行に潰すときは
#    Critical/High を ng、Medium/Low を warn に丸める（`_worst_judgement`）。
#    「そのままでよい／条件つきで直す／直す必要がある」の3段階のうち、
#    致命的〜要修正級は×、様子見〜軽微は△という切り方にした。
# 2. **対象がそもそも無い（イベント作成ルール0件・広告タグ0件など）を
#    「○問題なし」とだけ書くと、見て問題が無かったのか、見る対象自体が
#    無かったのかが分からない。** 状態の文に「対象なし」と明示し、
#    ○の意味を「見て問題なかった」と混同させない。
# ──────────────────────────────────────

_SEVERITY_JUDGEMENT = {"Critical": "ng", "High": "ng", "Medium": "warn", "Low": "warn"}


def _worst_judgement(findings: list[dict]) -> str:
    """findings の severity から判定を1つに決める。最悪のseverityを採る。"""
    rank = {"ok": 0, "warn": 1, "ng": 2}
    worst = "warn"  # findings が空でなければ ok を返さない（デフォルトの安全側）
    for f in findings:
        j = _SEVERITY_JUDGEMENT.get(f.get("severity", ""), "warn")
        if rank[j] > rank[worst]:
            worst = j
    return worst


def _event_create_rules_count(defs: dict) -> int:
    return sum(
        len(v) for k, v in defs.items()
        if k.startswith("event_create_rules") and isinstance(v, list)
    )


def _judge_duplicate_ad_conversion_labels(ds: dict) -> tuple[str, str]:
    """同じコンバージョンID・ラベルの組み合わせが複数の広告タグに設定されていないか
    （`check_duplicate_ad_conversion_labels`）。

    重複していると1回の成果が広告側で多重にカウントされ、入札の自動調整が
    実際より多い成果数を前提に動く。値が変数参照のときは定数まで解決できた
    ものだけを比較しており、解決できないものは○にせず「判定できない」と
    区別して出す（GTM APIで取得できたときのみ判定）。
    """
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels

    gtm = ds["gtm_api"]
    ad_tags = [t for t in gtm.get("tags") or [] if t.get("type") == "awct" and not t.get("paused")]
    if not ad_tags:
        return "ok", "稼働中の広告コンバージョンタグが無い（対象なし）"
    found = check_duplicate_ad_conversion_labels(gtm, [0])
    dups = [f for f in found if f["category"] == "多重計上"]
    unresolved = [f for f in found if f["category"] == "判定不能"]
    if dups:
        names = "、".join(sorted({f["target_name"] for f in dups}))
        # unresolvedの詳しい説明文はここに複製しない（check-report §5に同じ指摘が
        # 別途出るため）。対象だけ短く触れる。
        note = f"。ほかに判定できないものもある（{unresolved[0]['target_name']}）" if unresolved else ""
        return _worst_judgement(dups), (
            f"広告コンバージョンタグ{len(ad_tags)}本のうち{len(dups)}組で"
            f"コンバージョンID・ラベルが重複している（{names}）{note}"
        )
    if unresolved:
        return "warn", f"広告コンバージョンタグのコンバージョンID・ラベルが変数参照で判定できないものがある（{unresolved[0]['target_name']}）"
    return "ok", f"広告コンバージョンタグ{len(ad_tags)}本、コンバージョンID・ラベルの重複は見つからない"


def _judge_non_outcome_key_events(ds: dict) -> tuple[str, str]:
    """クリック型MCVを含むGA4キーイベントの発火範囲が広すぎないか。

    GTMの `gaawe` タグへ `eventName` で
    橋渡しできたキーイベントだけを判定し、**橋渡しできない（GTM経由でない）
    こと自体は異常として扱わない**（GA4管理画面のイベント作成ルール・gtag直書き・
    サイト側実装の可能性がある）。「対象なし」「GTMからは確認できない」
    「判定できない」「見て問題なかった」を区別する（GTM APIで取得できたときのみ判定）。
    """
    from measurement_design.review.health_checks import (
        check_non_outcome_key_events, resolve_gaawe_event_names,
    )

    key_events = [
        k.get("event_name", k.get("eventName", ""))
        for k in ds["events"].get("key_events") or []
    ]
    key_events = [k for k in key_events if k and k not in DEFAULT_NOISE_KEY_EVENTS]
    if not key_events:
        return "ok", "成果（キーイベント）が登録されていない（対象なし）"

    gtm = ds["gtm_api"]
    by_event, _ = resolve_gaawe_event_names(gtm)
    traced = [k for k in key_events if by_event.get(k)]
    not_traced = [k for k in key_events if not by_event.get(k)]

    found = check_non_outcome_key_events(ds["events"], gtm, [0])
    broad = [f for f in found if f["category"] == "発火範囲の確認"]
    unresolved = [f for f in found if f["category"] == "判定不能"]

    parts = [f"キーイベント{len(key_events)}件のうちGTMのGA4イベントタグから{len(traced)}件を追跡できた"]
    if not_traced:
        parts.append(
            f"残り{len(not_traced)}件（{'・'.join(not_traced[:3])}）はGTMからは確認できない"
            "（GA4管理画面のイベント作成ルール・gtag直書き・サイト側実装の可能性がある。異常ではない）"
        )
    if broad:
        names = "、".join(sorted({f["target_name"] for f in broad}))
        parts.append(f"追跡できた分のうち{len(broad)}件はクリック対象の絞り込み条件を確認できない（{names}）")
        return "warn", "。".join(parts)
    if unresolved:
        # unresolvedの詳しい説明文はここに複製しない（check-report §5に同じ指摘が
        # 別途出るため）。対象だけ短く触れる。
        parts.append(f"GA4イベントタグの `eventName` が変数参照で判定できないものがある（{unresolved[0]['target_name']}）")
        return "warn", "。".join(parts)
    parts.append("追跡できた分に発火範囲が広すぎる設定は見つからない" if traced else "GTM側からは判定できる範囲が無い")
    return "ok", "。".join(parts)


def _judge_ua_continuity(ds: dict) -> tuple[str, str]:
    """停止済みの Universal Analytics 経由でしか GA4 に届いていないおそれ
    （`check_universal_analytics_tags` と `check_ga4_via_ua_bridge`）。

    **×ではなく△で言い切る。** UAの残存は確認できても、「消すと
    GA4の計測が止まるか」は設定の静的な読み取りだけでは断定できない。

    判定根拠は GTM API だけに限定しない。登録済みのサイトURLから取った
    公開HTMLの `G-*` / `UA-*` と、公開 gtm.js の `__googtag` / `__gaawe` /
    `__ua` も証拠に使う。GTM API未取得という理由だけで一律に判定不能に
    しない。ただし、公開情報で分かるのは配信中の実装に限られる。
    """
    gtm_api = ds.get("gtm_api") or {}
    gtm = ds.get("gtm") or {}
    site = ds.get("site_implementation") or {}

    # `_load("09")` が API版を返したときは同じタグを2回数えない。
    public_tags = []
    if (gtm.get("source") or {}).get("method") == "public_gtm_js":
        public_tags = gtm.get("tags") or []
    site_tags = site.get("tags") or []
    api_tags = gtm_api.get("tags") or []

    ua_labels: list[str] = []
    for tag in api_tags:
        if _tag_kind(tag) == "ua":
            label = tag.get("name") or "UAタグ（GTM API）"
            if tag.get("paused"):
                label += "（停止中）"
            ua_labels.append(label)
    for tag in [*public_tags, *site_tags]:
        if _tag_kind(tag) == "ua":
            ua_labels.append(f"UAタグ（公開GTM {tag.get('container_id') or ''}）".replace("  ", " "))
    ua_labels.extend(site.get("universal_analytics_ids") or [])
    # 同じ公開コンテナを手動ダンプと自動スキャンの両方で取った場合に備える。
    ua_labels = list(dict.fromkeys(ua_labels))

    ga4_tag_found = any(
        _tag_kind(tag) in {"googtag", "gaawe"} and not tag.get("paused")
        for tag in [*api_tags, *public_tags, *site_tags]
    )
    direct_ga4_ids = site.get("ga4_measurement_ids") or []
    ga4_evidence = ga4_tag_found or bool(direct_ga4_ids)
    inspected = bool(gtm_api) or bool(public_tags) or bool(site)

    if ua_labels:
        names = "、".join(ua_labels[:4])
        if ga4_evidence:
            return "warn", (
                f"Universal Analytics の残存を確認（{names}）。"
                "GA4タグは別経路でも確認できるが、削除前に実機の送信経路を確認する"
            )
        measurement_ids = sorted({
            (stream.get("web_stream_data") or {}).get("measurement_id", "")
            for stream in (ds.get("property") or {}).get("data_streams") or []
        } - {""})
        target = "・".join(measurement_ids) or "GA4測定ID"
        return "warn", (
            f"Universal Analytics の残存を確認（{names}）。{target}のGoogleタグ / gtag.jsは"
            "確認できず、UA経由のみか別実装かを実機で確認する"
        )
    if inspected:
        if ga4_evidence:
            return "ok", (
                "取得した公開実装またはGTM APIの範囲でGA4タグを確認し、"
                "Universal Analyticsの残存は見つからない（対象なし）"
            )
        if gtm_api:
            return "ok", "GTM APIでUniversal Analyticsタグは見つからない（対象なし）"
        return "warn", "公開実装は取得したが、GA4 / Universal Analyticsの送信経路を特定できない"
    return "warn", (
        "GTM APIと公開サイトの計測実装がともに未取得。"
        "サイトURLから gtag.js・UA測定ID・公開GTMを確認する"
    )


# ──────────────────────────────────────
# イベント計測
# ──────────────────────────────────────

def _judge_event_names(ds: dict) -> tuple[str, str]:
    """イベント名の表記を検査する。

    判定基準は diagnoser.naming_severity に寄せている（判定基準を二重に持たない）。
    数字/アンダースコア始まり・40文字超など、実害の大きい仕様外表記は×とする。
    ハイフンと大文字は受信・分析を止める重大な問題ではないため、修正必須にせず△の参考情報とする。

    **`names` は取得上限（`health_checks.EVENTS_LIST_LIMIT`＝直近30日の上位100件）で
    切られていることがある。** 上限ちょうどの件数のときは「◯種のうち△件」の分母
    自体が実際のイベント種類数ではなく上限で、101件目以降が対象外になっている
    可能性がある。分母を鵜呑みにされないよう、上限に達しているときはその旨を
    状態文に注記する（分母を本文中で明示しない不備があった）。
    """
    from measurement_design.review.diagnoser import naming_severity
    from measurement_design.review.health_checks import EVENTS_LIST_LIMIT

    names = list(_events(ds["events"]))
    if not names:
        return "ng", "イベントが記録されていない"
    cap_note = (
        f"（イベント名の一覧は取得上限{EVENTS_LIST_LIMIT}件のため、"
        "実際にはさらに種類がある可能性がある）"
        if len(names) >= EVENTS_LIST_LIMIT else ""
    )
    high = [n for n in names if naming_severity(n) == "high"]
    medium = [n for n in names if naming_severity(n) == "medium"]
    low = [n for n in names if naming_severity(n) == "low"]
    if high:
        notes = []
        if medium:
            notes.append(f"データ連携上の修正対象が{len(medium)}件")
        if low:
            notes.append(f"仕様内の参考情報が{len(low)}件")
        note = "。ほかに" + "、".join(notes) if notes else ""
        return "ng", f"{len(names)}種のうち仕様外の名前が{len(high)}件（{'・'.join(high[:3])}）。受信記録と命名仕様への適合は別{note}{cap_note}"
    if medium:
        low_note = f"。ほかに大文字・ハイフンだけの参考情報が{len(low)}件" if low else ""
        return "warn", (
            f"{len(names)}種のうち日本語・全角文字を含む名前が{len(medium)}件"
            f"（{'・'.join(medium[:3])}）。外部ツールへのデータ連携でエラーや非対応になることがあるため修正する"
            f"{low_note}{cap_note}"
        )
    if low:
        return "warn", (
            f"{len(names)}種のうち大文字・ハイフンを含む名前が{len(low)}件。"
            f"受信・分析を止める重大な問題ではなく、既存名の修正は必須ではない{cap_note}"
        )
    return "ok", f"{len(names)}種に、修正が必要な表記は見つからなかった{cap_note}"


def _judge_micro_events(ds: dict) -> tuple[str, str]:
    """申込までの手前の行動（閲覧・検索・カート追加など）をどれだけ計測できているか。

    **×だけでは「意図的だが？」と読める（試用フィードバックで検出）。** 「2種しかない」
    という件数だけだと、それが何の問題につながるのかが分からない。手前の行動を
    計測していないと、申込に至らなかった人がどの段階で離脱したかを追えず、
    CVR改善の打ち手が「どこを直すべきか」ではなく当てずっぽうになる、という理由を
    state 側の文に必ず入れる。
    """
    names = list(_events(ds["events"]))
    found = [h for h in MICRO_EVENT_HINTS if any(h in n for n in names)]
    form_views = [n for n in names if "form" in n.lower() or "フォーム" in n]
    if form_views:
        return "warn", f"フォーム関連の名前を持つイベントを{len(form_views)}種受信。各フォームとの対応と必要な中間操作の網羅性は未確認"
    reason = "申込に至らなかった人がどの段階で離脱したか追えず、CVR改善の打ち手が絞れない"
    if len(found) >= MICRO_EVENT_ENOUGH:
        return "ok", f"申込の手前を{len(found)}種計測している"
    if found:
        return "ng", f"申込の手前の計測が{len(found)}種しかない（{'・'.join(found)}）。{reason}"
    return "ng", f"申込の手前を計測していない。{reason}"


def _judge_unused_events(ds: dict) -> tuple[str, str]:
    firing = {r.get("eventName", ""): _int(r.get("eventCount")) for r in ds["events"].get("key_event_firing", [])}
    key_events = [k.get("event_name", "") for k in ds["events"].get("key_events") or []]
    if not key_events:
        return "warn", "成果（キーイベント）の登録が取れていない"
    # purchase はどのプロパティにも既定で入るため、発火なしの判定からは除外する（ga4_defaults）
    dead = [k for k in key_events if k not in DEFAULT_NOISE_KEY_EVENTS and firing.get(k, 0) == 0]
    noise_dead = [k for k in key_events if k in DEFAULT_NOISE_KEY_EVENTS and firing.get(k, 0) == 0]
    if dead:
        note = (
            f"。なお {'・'.join(noise_dead)} は既定候補のため判定対象外だが、取得期間では発火0件"
            if noise_dead else ""
        )
        return "ng", f"発火のない成果が{len(dead)}件（{'・'.join(dead[:3])}）{note}"
    if noise_dead:
        return "ok", f"{'・'.join(noise_dead)}（既定候補のため対象外）を除き、登録した成果はすべて発火している"
    return "ok", "登録した成果はすべて発火している"


def _judge_file_video(ds: dict) -> tuple[str, str]:
    enhanced = _first(ds["property"], *[k for k in ds["property"] if k.startswith("enhanced_measurement")]) or {}
    on = [n for n, k in (("ファイル", "file_downloads_enabled"), ("動画", "video_engagement_enabled"),
                         ("外部リンク", "outbound_clicks_enabled")) if enhanced.get(k)]
    if len(on) >= 2:
        return "ok", "標準機能で有効（" + "・".join(on) + "）"
    return "warn", "ファイル・動画・外部リンクの計測が一部オフ"


def _judge_duplicate_event_rules(ds: dict) -> tuple[str, str]:
    """条件がまったく同じイベント作成ルールが複数無いか（`check_duplicate_event_rules`）。

    1回のページ表示から同時に生成されるため、条件に差が無いルールは
    多重計上になる（プラン別・店舗別などに分ける意図で作って条件が揃わなかった例）。
    """
    from measurement_design.review.health_checks import check_duplicate_event_rules

    total = _event_create_rules_count(ds["defs"])
    if total == 0:
        return "ok", "イベント作成ルールが0件（対象なし）"
    found = check_duplicate_event_rules(ds["defs"], [0])
    if found:
        names = "、".join(f["target_name"] for f in found)
        return _worst_judgement(found), f"{total}件のうち同一条件の重複が{len(found)}組ある（{names}）"
    return "ok", f"{total}件に条件が完全に同じ重複は無い"


# ──────────────────────────────────────
# 流入計測
# ──────────────────────────────────────

def _paid(ds: dict) -> list[dict]:
    return [
        r for r in ds["traffic"].get("campaigns", [])
        if str(r.get("sessionMedium", "")).lower() in {"cpc", "ppc", "paid", "paidsearch", "display", "cpm"}
    ]


def _judge_medium_values(ds: dict) -> tuple[str, str]:
    """GA4自身が既定チャネルへ分類できなかったsource / mediumが多いかを見る。

    関数名は従来の内部監査項目との互換のため残すが、独自のmedium辞書とは比較しない。
    `sessionDefaultChannelGroup` を取得していない旧データでは良否を推測しない。
    """
    from measurement_design.review.health_checks import check_unknown_medium_values

    rows = ds["traffic"].get("source_medium", [])
    if not rows:
        return "warn", "流入のデータが取れていない"
    found = check_unknown_medium_values(ds["traffic"], [0])
    if not found:
        if not any("sessionDefaultChannelGroup" in row for row in rows):
            return "warn", "既定チャネルの分類結果を取得していないため未確認"
        return "ok", "大量のUnassignedは見つからない"
    return _worst_judgement(found), found[0]["description"]


def _judge_campaign_values(ds: dict) -> tuple[str, str]:
    paid = _paid(ds)
    if not paid:
        return "warn", "有料流入が見つからない"
    numeric = [r for r in paid if NUMERIC_ONLY_RE.match(str(r.get("sessionCampaignName", "")))]
    names = {str(r.get("sessionCampaignName", "")) for r in paid}
    if numeric and len(numeric) / len(paid) > NUMERIC_CAMPAIGN_RATIO:
        return "warn", f"有料流入のキャンペーン名が数値ID（{len(numeric)}/{len(paid)}通り）。広告媒体側の名称・IDとの対応を確認する"
    missing = [r for r in paid if str(r.get("sessionCampaignName", "")) in ("", "(not set)")]
    if missing:
        n = sum(_int(r.get("sessions")) for r in missing)
        return "warn", f"有料流入のキャンペーン名が未設定の行を検出（{n:,}セッション）。広告設定・自動タグ・UTMを照合する"
    return "ok", f"キャンペーン名は{len(names)}種"


def _judge_internal_utm(ds: dict) -> tuple[str, str]:
    if not ds["traffic"].get("source_medium"):
        return "warn", "流入のデータが取れていない"
    rows = [r for r in ds["traffic"].get("source_medium", [])
            if INTERNAL_MEDIUM_RE.match(str(r.get("sessionMedium", "")))]
    if rows:
        n = sum(_int(r.get("sessions")) for r in rows)
        return "ng", f"サイト内の通知・ポップアップに印を付けている疑い（月{n:,}セッション）"
    return "ok", "取得したmediumに内部リンクを示唆する既定パターンは検出されない。実リンクのUTM付与は未確認"


def _judge_channel_groups(ds: dict) -> tuple[str, str]:
    rows = ds["traffic"].get("channel_performance", [])
    total = sum(_int(r.get("sessions")) for r in rows)
    un = sum(_int(r.get("sessions")) for r in rows
             if str(r.get("sessionDefaultChannelGroup", "")).lower() in {"unassigned", "(other)"})
    if not total:
        return "warn", "チャネルのデータが取れていない"
    if un / total > UNCLASSIFIED_SESSION_RATIO:
        return "ng", f"未分類が月{un:,}セッション（{un / total:.1%}）"
    return "ok", "未分類はほぼ無い"


# ──────────────────────────────────────
# ページ計測
# ──────────────────────────────────────

def _judge_content_groups(ds: dict) -> tuple[str, str]:
    groups = ds["pages"].get("content_groups") or []
    named = [g for g in groups if str(g.get("contentGroup", "")) not in ("", "(not set)")]
    pages = len({r.get("pagePath") for r in ds["pages"].get("pages") or [] if r.get("pagePath")})
    if not named:
        return "warn", f"取得したcontentGroupに名前付き分類がない。ページ一覧は{pages:,}種類のパス。分類の必要性と代替のカスタム定義を確認する"
    return "ok", f"名前付き分類を{len(named)}グループ受信。分類の正確性・網羅性は未検証"


def _judge_url_variants(ds: dict) -> tuple[str, str]:
    from measurement_design.review.health_checks import check_duplicate_page_urls

    if not ds["pages"].get("pages"):
        return "warn", "ページのデータが取れていない"
    found = check_duplicate_page_urls(ds["pages"], [0])
    if found:
        return "warn", found[0]["target_name"] + "に表記違いの候補を検出。内容の同一性・正規化方針は未確認"
    return "ok", "同じページのURL違いは見つからない"


def _judge_page_pii(ds: dict) -> tuple[str, str]:
    """ページパス・クエリパラメータに個人情報らしき値が記録されていないか。

    `check_page_pii` をそのまま呼ぶ（`_judge_url_variants` と同じ形）。
    判定は見つかった指摘の中で最悪のseverityを採る（`_worst_judgement`）。
    """
    from measurement_design.review.health_checks import check_page_pii

    if not ds["pages"].get("pages"):
        return "warn", "ページのデータが取れていない"
    found = check_page_pii(ds["pages"], [0])
    if not found:
        return "ok", "取得したページパスに検出対象の個人情報パターンは見つからない。URLクエリ・イベントパラメータ全体は未確認"
    return _worst_judgement(found), f"個人情報らしき値の疑いが{len(found)}件"


# ──────────────────────────────────────
# カスタム計測
# ──────────────────────────────────────

def _judge_dimensions(ds: dict) -> tuple[str, str]:
    dims = ds["defs"].get("custom_dimensions") or []
    if len(dims) <= 2:
        names = "・".join(d.get("display_name", "") for d in dims)
        return "warn", f"{len(dims)}件登録（{names or '登録なし'}）。件数だけでは不足を判定できないため計測要件と照合する"
    return "ok", f"{len(dims)}件を登録している。値の受信・定義の妥当性は未検証"


def _judge_metrics(ds: dict) -> tuple[str, str]:
    if "custom_metrics" not in ds["defs"]:
        return "warn", "カスタム定義のデータが取れていない"
    n = len(ds["defs"].get("custom_metrics") or [])
    return ("ok", "登録なし（必要性は計測要件による）") if n == 0 else ("ok", f"{n}件登録。値の受信・定義の妥当性は未検証")


def _gtm_method(ds: dict) -> str:
    """GTM データがどちらの経路で取れたかを判定する。

    フォールバック経路（`gtm_public.py`。閲覧権限が無く公開 gtm.js から復元）は
    `source.method` を明示的に持つが、**API 経路（`gtm.py`→`run_phase.run_phase3`）は
    このキーを持たない**（`live_version`/`tag_analysis`/`measurement_ids` を持つ）。
    このキーの有無だけで判定すると、API 経路のデータが常に「未取得」に見えてしまう
    （実際に GTM API で24タグ/18トリガー/50変数を取得できていても検出0件になったバグ）。
    """
    gtm = ds["gtm"]
    method = (gtm.get("source") or {}).get("method")
    if method:
        return method
    if "live_version" in gtm or "tag_analysis" in gtm:
        return "api"
    return ""


def _judge_tag_containers(ds: dict) -> tuple[str, str]:
    gtm = ds["gtm"]
    method = _gtm_method(ds)
    if method == "api":
        tags_list = gtm.get("tags") or []
        tags = len(tags_list)
        if not tags:
            return "warn", "タグマネージャーの設定を読めていない"
        ids = set(gtm.get("measurement_ids") or [])
        paused = sum(1 for t in tags_list if t.get("paused"))
        html = sum(1 for t in tags_list if str(t.get("type", "")) == "html")
    else:
        counts = gtm.get("counts") or {}
        tags = counts.get("tags")
        if not tags:
            return "warn", "タグマネージャーの設定を読めていない"
        ids = _measurement_ids(ds)
        paused = sum(1 for t in gtm.get("tags") or [] if t.get("function") == "__paused")
        html = sum(1 for t in gtm.get("tags") or [] if t.get("function") == "__html")
    if len(ids) > 1:
        return "warn", (
            f"タグ{tags}本、GA4の送信先が{len(ids)}種類（独自HTML {html}本・停止中 {paused}本）。"
            "複数プロパティへの送信が意図どおりか、各GA4タグの送信先を確認する。"
            "独自HTML・停止中タグは件数だけでは良否を判定しない"
        )
    return "warn", (
        f"タグ{tags}本（独自HTML {html}本・停止中 {paused}本）。"
        "件数だけでは良否を判定できないため、各GA4タグの送信先と重複発火の有無を確認する"
    )


# ──────────────────────────────────────
# その他推奨設定事項
# ──────────────────────────────────────

def _judge_bigquery(ds: dict) -> tuple[str, str]:
    if "bigquery_links" not in ds["property"]:
        return "warn", "連携の一覧が取れていない"
    links = ds["property"].get("bigquery_links")
    if links:
        return "warn", f"{len(links)}件のリンク設定あり。出力先テーブルの存在・最新日付・欠損は未確認"
    return "warn", "リンク設定なし。長期のイベント明細保存などの要件に応じて導入要否を判断する"


def _judge_gtm_access(ds: dict) -> tuple[str, str]:
    method = _gtm_method(ds)
    if method == "api":
        return "ok", "APIで設定を読めている"
    if method in {"public_gtm_js", "public_site_scan"}:
        return "ng", "閲覧権限が無く、公開ファイルから復元している（タグ名は読めない）"
    return "warn", "タグマネージャーの設定を取得していない"


def _judge_foreign_noise(ds: dict) -> tuple[str, str]:
    """海外からの機械的アクセスを、異常集中と複数の行動信号で疑う。

    判定を作る `check_foreign_noise` は国名だけで判定せず、セッション集中に加えて平均
    エンゲージメント時間・直帰率・キーイベント率の複数信号を見る。
    旧実装はここにしかロジックが無く、×でも指摘が作られず改善ロードマップに出ない
    不整合があった。
    """
    from measurement_design.review.health_checks import check_foreign_noise

    quality = ds["quality"]
    total = sum(_int(r.get("sessions")) for r in quality.get("countries") or [])
    if not total or not quality.get("country_environment"):
        return "warn", "国・環境別のデータが取れていない"
    found = check_foreign_noise(quality, [0])
    if not found:
        return "ok", "海外流入に、異常集中と行動品質の複数異常が重なるパターンは見つからない"
    return _worst_judgement(found), found[0]["description"]


# (領域, 項目, 判定関数)
# (領域, 項目, 判定関数, 判定に要るデータセット)
#
# **要るデータセットを宣言する。** 判定関数の中だけで欠損を見ていると、
# 「データが無い」を「問題なし」と返す経路が繰り返し生まれる（codex レビューで
# 3巡連続して同じ型の指摘が出た）。ここで宣言して `audit_matrix` が先に止める。
ITEMS: tuple[tuple[str, str, object, tuple[str, ...]], ...] = (
    ("GA4本体の設定", "成果（キーイベント）の登録", _judge_key_events, ("events",)),
    ("GA4本体の設定", "内部トラフィックの除外", _judge_internal_traffic, ("quality",)),
    ("GA4本体の設定", "参照元の除外", _judge_referral_exclusion, ("property", "traffic")),
    # traffic は複数ドメインのときだけ要る（単一ドメインなら判定関数の中で先に ok が返る）。
    # ここで両方を要ると宣言すると、単一ドメインで05が未取得のだけの案件まで
    # 「流入のデータが取れていない」という的外れな warn になる。
    ("GA4本体の設定", "クロスドメイン計測", _judge_cross_domain, ("quality",)),
    ("GA4本体の設定", "スクロールの計測", _judge_scroll, ("property", "events")),
    ("GA4本体の設定", "サイト内検索の設定", _judge_site_search, ("property", "events", "pages")),
    ("GA4本体の設定", "フォーム操作の計測", _judge_form_measurement, ("events",)),
    ("GA4本体の設定", "データ保持", _judge_retention, ("property",)),
    ("GA4本体の設定", "タイムゾーン・通貨", _judge_locale, ("property",)),
    ("GA4本体の設定", "データストリーム", _judge_streams, ("property",)),
    ("GA4本体の設定", "拡張計測機能", _judge_enhanced_measurement, ("property",)),
    ("GA4本体の設定", "Google シグナル", _judge_signals, ("property",)),
    ("GA4本体の設定", "ユーザー提供データの収集", _judge_user_provided_data, ("property",)),
    ("GA4本体の設定", "レポート用識別子", _judge_reporting_identity, ("property",)),
    ("GA4本体の設定", "アトリビューション", _judge_attribution, ("property",)),
    # `_judge_ads_links` は GTM データが無くても Admin API（`property.ads_links`）だけで
    # 「リンクされているか」を判定できる（関数内の `if not ds["gtm"].get("tags")` 分岐で
    # GTM未取得でも○/×を確定させ、GTMが取れているときだけタグ数の突き合わせを追加する）。
    # ここで "gtm" を要ると宣言すると、GTM未取得の実行では判定関数に処理が渡る前に
    # 「データが取れていない」に丸められ、そのフォールバック分岐が永久に実行されない
    # （試用フィードバックで検出）。
    ("広告連携", "Google広告とのリンク", _judge_ads_links, ("property",)),
    # 以下3項目は GA4 のデータだけでは判定できず、GTM（`gtm_api`）が要る。GA4側の実測値
    # からは「イベントが発火した事実」までしか分からず、それを発火させているGTM側の
    # トリガー構造・タグのパラメータまでは見えないため。GTM未取得のときの判定不能の
    # 理由は `_GTM_REQUIRED_REASONS` に項目ごとに書き、判定表の状態文に添える
    # （「GTMのデータが取れていない」とだけ書くと、読み手にはなぜGTMが要るのか
    # 伝わらないという試用フィードバックを受けた対応）。
    ("広告連携", "広告コンバージョンのラベル重複", _judge_duplicate_ad_conversion_labels, ("gtm_api",)),
    ("GTM", "キーイベントの発火条件", _judge_non_outcome_key_events, ("events", "gtm_api")),
    # GTM APIと公開サイト実装のいずれかで補完できるため、ここで
    # `gtm_api` を必須にしない。両方無い場合の説明は判定関数が返す。
    ("GTM", "UA経由の計測継続性", _judge_ua_continuity, ("property",)),
    ("イベント計測", "イベント名の表記", _judge_event_names, ("events",)),
    ("イベント計測", "申込の手前の計測", _judge_micro_events, ("events",)),
    ("イベント計測", "使われていないイベント", _judge_unused_events, ("events",)),
    ("イベント計測", "ファイル・動画・外部リンク", _judge_file_video, ("property",)),
    ("イベント計測", "イベント作成ルールの重複", _judge_duplicate_event_rules, ("defs",)),
    ("流入計測", "種類（medium）の値", _judge_medium_values, ("traffic",)),
    ("流入計測", "キャンペーン（campaign）の値", _judge_campaign_values, ("traffic",)),
    ("流入計測", "サイト内の移動への印", _judge_internal_utm, ("traffic",)),
    ("流入計測", "チャネルの分類", _judge_channel_groups, ("traffic",)),
    ("ページ計測", "ページの分類（コンテンツグループ）", _judge_content_groups, ("pages",)),
    ("ページ計測", "URLの表記ゆれ", _judge_url_variants, ("pages",)),
    ("ページ計測", "個人情報の混入", _judge_page_pii, ("pages",)),
    ("カスタム計測", "カスタムディメンション", _judge_dimensions, ("defs",)),
    ("カスタム計測", "カスタム指標", _judge_metrics, ("defs",)),
    ("カスタム計測", "タグマネージャーの構成", _judge_tag_containers, ("gtm",)),
    ("その他推奨設定事項", "生データの書き出し（BigQuery）", _judge_bigquery, ("property",)),
    ("その他推奨設定事項", "タグマネージャーの権限", _judge_gtm_access, ("gtm",)),
    ("その他推奨設定事項", "海外からの機械的アクセス（ノイズ）", _judge_foreign_noise, ("quality",)),
)

# データセットの呼び名（判定できないときの文に使う）
DATASET_LABELS = {
    "property": "プロパティの設定", "events": "イベント", "defs": "カスタム定義",
    "traffic": "流入", "pages": "ページ", "quality": "データ品質",
    "gtm": "タグマネージャー", "gtm_api": "タグマネージャー（APIで取得したもの）",
    "site_implementation": "公開サイトの計測実装",
}


def load_datasets(data_dir: Path) -> dict:
    """判定に使う観点別データセットをまとめて読む。"""
    from measurement_design.review.health_checks import load_gtm_api

    site_implementation = {}
    site_path = data_dir / "09-site-implementation.json"
    if site_path.exists():
        try:
            site_implementation = json.loads(site_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            site_implementation = {}

    return {
        "property": _load(data_dir, "01"),
        "events": _load(data_dir, "02"),
        "defs": _load(data_dir, "03"),
        "traffic": _load(data_dir, "05"),
        "pages": _load(data_dir, "06"),
        "quality": _load(data_dir, "07"),
        "gtm": _load(data_dir, "09"),
        # **`gtm` はAPI経路／公開gtm.js経路のどちらのファイルが取れているかで
        # 形式が違う**上、`_load` は辞書順で先に来るファイルを返すため、両方
        # 揃っていると公開gtm.js側を返すことがある。UA経由・広告コンバージョンの
        # キーイベント等の発火条件の判定はトリガー構造（`triggerId`/`variables`）までAPI形式が
        # 前提のため、専用に読み分ける `load_gtm_api`（公開gtm.js由来なら空）を
        # 別キーとして持つ。
        "gtm_api": load_gtm_api(data_dir),
        # GTM APIの有無にかかわらず、登録済みURLのHTMLと公開GTMから
        # 直接設置のGA4/UAと配信中タグを読む。
        "site_implementation": site_implementation,
    }


# GTM（`gtm`/`gtm_api`）が判定に要る項目のうち、「なぜGTMが要るか」を判定不能時の
# 状態文に添える。項目名（ITEMS の2番目の要素）をキーにする。ここに載っていない
# 項目は、GTMが要る理由の注記なしで従来どおり「〜のデータが取れていない」とだけ出す。
_GTM_REQUIRED_REASONS = {
    "広告コンバージョンのラベル重複": (
        "広告コンバージョンのコンバージョンID・ラベルはGTMのタグのパラメータを見ないと分からないため"
    ),
    "キーイベントの発火条件": (
        "クリック型MCVを含むキーイベントの発火範囲が広すぎないかは、"
        "GA4イベントタグ（gaawe）のトリガー構造をGTMで見ないと分からないため"
    ),
}


def audit_matrix(data_dir: Path) -> list[dict]:
    """監査項目ごとに {area, name, judgement, state} を返す。

    **判定関数が落ちても表は返す。** 1項目のデータ欠けで全体が出ないほうが困る。
    """
    ds = load_datasets(data_dir)
    rows = []
    for area, name, judge, needs in ITEMS:
        missing = [DATASET_LABELS.get(k, k) for k in needs if not ds.get(k)]
        if missing:
            # データが無いのは「問題なし」ではない。○にせず、取れていないことを書く
            judgement, state = "warn", f"{'・'.join(missing)}のデータが取れていない"
            reason = _GTM_REQUIRED_REASONS.get(name)
            if reason and any(k in needs for k in ("gtm", "gtm_api")):
                state += f"（{reason}）"
        else:
            try:
                judgement, state = judge(ds)
            except Exception as e:  # noqa: BLE001 — 1項目の欠けで表全体を落とさない
                judgement, state = "warn", f"判定できません（{type(e).__name__}）"
        rows.append({"area": area, "name": name, "judgement": judgement, "state": state})
    return rows


def counts(rows: list[dict]) -> dict[str, int]:
    out = {"ok": 0, "warn": 0, "ng": 0}
    for r in rows:
        out[r["judgement"]] = out.get(r["judgement"], 0) + 1
    return out


# ──────────────────────────────────────
# 判定表の項目と指摘の対応関係
#
# 判定表（このモジュール）と check-report の指摘一覧（diagnoser/health_checks）は
# 別の経路で計算される。そのままだと同じ内容を2回説明することになるため、
# **judge関数が指摘を作る check_* 関数をそのまま呼んでいる項目に限り**、どの指摘が
# どの判定表項目から見つかったものかを対応づける。
#
# 「同じ check_* 関数を直接呼んでいる」ことを条件にしたのは、別ロジックで似た結果を出す
# だけの項目（例: `_judge_internal_traffic` は `health_checks.check_non_production_hosts`
# と検出内容は近いが直接は呼んでおらず、しきい値が食い違えば判定表と指摘側で結論が
# ずれる）まで紐付けると、参照先の指摘が実は無い／逆の結論ということが起きかねないため。
# **紐付けられない項目はそのままでよい**（standards/audit-items.md の「目視」項目と同じで、
# 分からないものを分かるふりで書かない）。
#
# **この対応関係は判定表の本文（`state`）には書かない。** 以前の `add_violation_references`
# は×・△の行の `state` に対応する指摘IDをそのまま埋め込んでいたが、レポートの中で
# 最初に・一番目立つ形で読まれる表に指摘IDの羅列（`` `V-a1`・`V-b2`・`V-c3` など49件 ``）が
# 残ることになり、「指摘IDの羅列が多すぎる」「IDいらない」という試用フィードバックへの
# 対応が判定表にだけ及んでいなかった（§2〜§5・改善ロードマップからは先に外していた）。
# `violation_matrix_items` は同じ対応づけの計算だけを行い、書き込み先は
# 読者向けレポートにはIDを出さず、対応関係が必要な内部処理だけで使う。
# ──────────────────────────────────────


def _match_naming_event(v: dict) -> bool:
    """`_judge_event_names` と同じ `naming_severity()` 判定から作られた指摘（イベント名限定）。"""
    return v.get("category") == "命名規則" and v.get("target_kind") == "event"


def _match_duplicate_event_rules(v: dict) -> bool:
    """`_judge_duplicate_event_rules` が直接呼ぶ `check_duplicate_event_rules` の指摘（GA4側）。"""
    return v.get("category") == "多重計上" and v.get("location") != "GTM"


def _match_duplicate_page_urls(v: dict) -> bool:
    """`_judge_url_variants` が直接呼ぶ `check_duplicate_page_urls` の指摘。"""
    return v.get("category") == "レポートの分裂"


def _match_page_pii(v: dict) -> bool:
    """`_judge_page_pii` が直接呼ぶ `check_page_pii` の指摘。"""
    return v.get("category") == "個人情報の混入"


def _match_ua_continuity(v: dict) -> bool:
    """`_judge_ua_continuity` が直接呼ぶ `check_universal_analytics_tags`／
    `check_ga4_via_ua_bridge` の指摘（いずれもGTM側、カテゴリが異なる2種を両方含む）。"""
    return v.get("category") in ("設定の陳腐化", "計測の停止リスク") and v.get("location") == "GTM"


def _match_duplicate_ad_conversion_labels(v: dict) -> bool:
    """`_judge_duplicate_ad_conversion_labels` が直接呼ぶ `check_duplicate_ad_conversion_labels` の指摘。"""
    return v.get("category") == "多重計上" and v.get("location") == "GTM"


def _match_non_outcome_key_events(v: dict) -> bool:
    """`_judge_non_outcome_key_events` が直接呼ぶ `check_non_outcome_key_events` の指摘。

    カテゴリ「発火範囲の確認」のうち、キーイベント側の指摘だけを説明文で見分ける。
    """
    return v.get("category") == "発火範囲の確認" and "キーイベント「" in (v.get("description") or "")


def _match_non_production_hosts(v: dict) -> bool:
    """`_judge_internal_traffic` が直接呼ぶ `check_non_production_hosts` の指摘。"""
    return v.get("category") == "データ品質"


def _match_self_referral(v: dict) -> bool:
    """`_judge_referral_exclusion` が直接呼ぶ `check_self_referral` の指摘。"""
    return v.get("category") == "自己参照"


def _match_unknown_medium_values(v: dict) -> bool:
    """`_judge_medium_values` が直接呼ぶ `check_unknown_medium_values` の指摘。"""
    return v.get("category") == "流入分類"


def _match_foreign_noise(v: dict) -> bool:
    """`_judge_foreign_noise` が直接呼ぶ `check_foreign_noise` の指摘。"""
    return v.get("category") == "海外ノイズ"


def _match_form_measurement_gap(v: dict) -> bool:
    """`_judge_form_measurement` が直接呼ぶ `check_form_measurement_gap` の指摘。"""
    return v.get("category") == "フォーム未計測"


# 項目名（ITEMS の2番目の要素）→ 一致判定関数。ここに載っていない項目は紐付けの対象外。
_VIOLATION_MATCHERS: dict[str, object] = {
    "イベント名の表記": _match_naming_event,
    "イベント作成ルールの重複": _match_duplicate_event_rules,
    "URLの表記ゆれ": _match_duplicate_page_urls,
    "個人情報の混入": _match_page_pii,
    "UA経由の計測継続性": _match_ua_continuity,
    "広告コンバージョンのラベル重複": _match_duplicate_ad_conversion_labels,
    "キーイベントの発火条件": _match_non_outcome_key_events,
    "内部トラフィックの除外": _match_non_production_hosts,
    "参照元の除外": _match_self_referral,
    "種類（medium）の値": _match_unknown_medium_values,
    "海外からの機械的アクセス（ノイズ）": _match_foreign_noise,
    "フォーム操作の計測": _match_form_measurement_gap,
}


def violation_matrix_items(violations: list[dict] | None) -> dict[str, str]:
    """各指摘IDが、判定表（検査項目の一覧）のどの項目から見つかったものかを返す（id → 項目名）。

    対応する判定表項目が無い指摘（`_VIOLATION_MATCHERS` がカバーしない検出。予約語衝突・
    パラメータ命名規則・GTM残骸候補など、判定表に対応する機械判定項目自体が無いもの）は
    このdictに含まれない——呼び出し側は `.get(id, "—")` のように既定値を扱う。

    **判定表の項目のうち、state 文に対象名を出さないものがある。** 例えば「個人情報の混入」は
    `_judge_page_pii` が `f"個人情報らしき値の疑いが{len(found)}件"` としか書かず、対象の
    ページを判定表側の文からは特定できない。この対応表は内部検証で対応関係を確認するために使う。
    """
    if not violations:
        return {}
    out: dict[str, str] = {}
    for name, matcher in _VIOLATION_MATCHERS.items():
        for v in violations:
            vid = v.get("id")
            if vid and matcher(v):
                out[vid] = name
    return out


def render_matrix(rows: list[dict]) -> str:
    """領域ごとの表にする（レポートの章頭にそのまま置ける形）。"""
    out = []
    for area in AREAS:
        area_rows = [r for r in rows if r["area"] == area]
        if not area_rows:
            continue
        c = counts(area_rows)
        out.append(f"### {area}（{len(area_rows)}項目のうち ×{c['ng']} / △{c['warn']} / ○{c['ok']}）")
        out.append("")
        out.append("| 見た項目 | 判定 | いまの状態 |")
        out.append("|---|---|---|")
        for r in area_rows:
            out.append(f"| {r['name']} | {JUDGE_MARK[r['judgement']]} | {r['state']} |")
        out.append("")
    total = counts(rows)
    out.append(
        f"判定は ○確認範囲で問題なし／△要確認／×要修正。"
        f"**全{len(rows)}項目のうち ×{total['ng']} / △{total['warn']} / ○{total['ok']}。**"
    )
    out.append("")
    out.append("○は各行に記載した設定・受信データの確認範囲に限る。実操作での動作確認を終えた意味ではない。△には未取得・未検証・要件次第・不備の疑いを含み、各行に理由を示す。")
    out.append("")
    out.append(
        "データから判定できない項目（未使用のプロパティ・タグ名の重複・運用の有無など）は"
        "`standards/audit-items.md` に「目視」として一覧がある。"
    )
    return "\n".join(out)
