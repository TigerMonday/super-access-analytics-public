"""違反検出モジュール.

機械検出 (正規表現・予約語) + LLM (Claude API) による違反検出。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from measurement_design.review.violation_id import dedupe_ids, make_id


VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_EVENT_NAME_LEN = 40

# 使用可能文字（英字・数字・アンダースコア）以外を検出する。ハイフン・空白・記号がこれに当たる。
ASCII_INVALID_CHARS_RE = re.compile(r"[^A-Za-z0-9_]")

# Google予約のプレフィックス。イベント名・パラメータ名でこれらから始まる名前は使えない
# （利用者が新規に作る名前が対象）。
# 出典: https://support.google.com/analytics/answer/13316687
RESERVED_NAME_PREFIXES = ("firebase_", "ga_", "google_", "gtag.")

# GA4が自動収集するイベントパラメータのうち、そのままカスタムディメンションとして
# 登録することを Google 自身が想定している名前（GA4の管理画面にも登録候補として出る）。
# 利用者が作った名前ではなくGoogle自身が付けた名前のため、予約プレフィックス判定の
# 対象から外す（実データで `ga_session_number` を「予約プレフィックスに違反し記録されない」
# と誤検知した。実際は正常に記録され続けている既定の項目で、除外前は誤検知だった）。
GA4_AUTO_COLLECTED_PARAMS = frozenset({"ga_session_id", "ga_session_number"})

# GA4 が自分で送る／利用を意図している標準イベント名。
# これらは events_observed に現れて当然であり、「予約語衝突」ではない。
# 観測されても違反として扱わない（誤検知防止）。
GA4_AUTO_COLLECTED = frozenset({
    "page_view", "session_start", "first_visit", "user_engagement",
    "first_open", "app_remove", "app_update", "in_app_purchase", "app_exception",
})
GA4_ENHANCED_MEASUREMENT = frozenset({
    "scroll", "click", "view_search_results",
    "video_start", "video_progress", "video_complete",
    "file_download", "form_start", "form_submit",
})
GA4_RECOMMENDED = frozenset({
    "share", "search", "login", "sign_up", "generate_lead",
    "select_content", "select_item", "select_promotion",
    "view_item", "view_item_list", "view_cart", "view_promotion",
    "add_to_cart", "remove_from_cart", "add_to_wishlist",
    "begin_checkout", "add_payment_info", "add_shipping_info",
    "purchase", "refund",
})
# 観測されても予約語衝突として扱わない標準イベント名の総称
GA4_STANDARD_EVENTS = GA4_AUTO_COLLECTED | GA4_ENHANCED_MEASUREMENT | GA4_RECOMMENDED
_NAMING_CATEGORIES = frozenset({"命名規則", "表記ゆれ", "重複", "予約語衝突"})


NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")

# 機械的に導出できない場合に出す文言。無意味な候補を出すより手動命名に委ねる。
MANUAL_NAMING_REQUIRED = "（英数字の名称を別途決める。機械的な変換では導出できない）"


def to_snake_case(name: str) -> str:
    """イベント名・パラメータ名を有効な snake_case 候補へ正規化する.

    小文字化に加え、ハイフン・空白・記号などの不正文字を '_' に置換する。
    name.lower() だけだと 'contact_curious-about_form' のハイフンが残るため、
    修正案として成立しなかった (旧実装のバグ)。

    小文字化は camelCase の語境界を消してしまうため、**先に語境界へ '_' を挿入する**。
    これをしないと 'contactId' が 'contactid' になり、snake_case を要求する規約と
    矛盾した修正案を出してしまう (旧実装のバグ)。

    日本語などの非 ASCII を含む名前は機械的に音訳できない。ASCII 部分だけを残すと
    'Wスリム注射_予約フォーム送信完了' が 'w' になるなど無意味な候補になるため、
    導出を諦めて空文字を返す（呼び出し側で MANUAL_NAMING_REQUIRED を出す）。
    """
    if NON_ASCII_RE.search(name):
        return ""

    # camelCase / PascalCase の語境界に '_' を入れる（小文字化より前に行う）
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)   # contactId  -> contact_Id
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)    # HTTPServer -> HTTP_Server
    s = s.lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)   # 英数字と _ 以外を _ に
    s = re.sub(r"_+", "_", s).strip("_")  # 連続・前後の _ を整理
    s = re.sub(r"^[^a-z]+", "", s)        # 先頭は英字でなければ削る
    return s if VALID_NAME_RE.match(s) else ""


def suggest_name(name: str) -> str:
    """修正案の文字列を返す。導出できない場合は手動命名を促す文言を返す.

    **予約プレフィックス違反は snake_case 変換だけでは直らない。** `ga_client_id` は
    使用可能文字・大文字・先頭文字のいずれも既に正しいため `to_snake_case` を通しても
    そのまま `ga_client_id` が返り、「修正案が現状と同じ」という直しようのない候補に
    なっていた（試用フィードバックで検出）。予約プレフィックスが残る場合は、予約語衝突
    （`mechanical_checks` の `custom_{name}`）と同じ考え方で `custom_` を足し、
    先頭が予約プレフィックスから外れるようにする。
    """
    candidate = to_snake_case(name)
    if not candidate:
        return MANUAL_NAMING_REQUIRED
    prefix = next((p for p in RESERVED_NAME_PREFIXES if candidate.startswith(p)), None)
    if prefix and candidate not in GA4_AUTO_COLLECTED_PARAMS:
        candidate = f"custom_{candidate}"
    if candidate == name:
        # 変換しても元の名前と変わらない場合、そのまま出すと「直しようがない」修正案になる。
        # 機械的にこれ以上の案は作れないため、手動命名を促す。
        return MANUAL_NAMING_REQUIRED
    return candidate


def naming_reasons(name: str) -> list[str]:
    """`naming_severity` が 'high' を返す根拠を文の一覧で返す（実害の説明に使う）。"""
    reasons = []
    if ASCII_INVALID_CHARS_RE.search(name):
        reasons.append("使用可能文字（英字・数字・アンダースコア）以外を含む")
    if name[:1].isdigit():
        reasons.append("数字から始まっている")
    if name.startswith("_"):
        reasons.append("アンダースコアから始まっている")
    prefix = next((p for p in RESERVED_NAME_PREFIXES if name.startswith(p)), None)
    if prefix and name not in GA4_AUTO_COLLECTED_PARAMS:
        reasons.append(f"Google予約のプレフィックス '{prefix}' で始まっている")
    if len(name) > MAX_EVENT_NAME_LEN:
        reasons.append(f"{MAX_EVENT_NAME_LEN}文字を超えている（{len(name)}文字）")
    return reasons


def naming_severity(name: str) -> str | None:
    """イベント名・パラメータ名の命名を重要度別に分類する。

    数字/アンダースコア始まり・Google予約プレフィックス・40文字超・ハイフン以外の記号は
    'high'。ハイフンや大文字は受信・分析を止める重大な問題ではないため'low'。
    日本語などの非ASCIIはGA4への受信自体は可能だが、外部ツールへのデータ連携で
    エラーや非対応になりうるため 'medium' とする。大文字・ハイフンだけは修正必須にしない。
    （実データで `contact_curious-about_form` の
    ように仕様外の文字を含む名前がWeb経由では届いていた例もあるため、'high' の説明文では
    「拒否される」と断定しない）。

    出典:
      https://support.google.com/analytics/answer/13316687
      https://developers.google.com/analytics/devguides/collection/protocol/ga4/reference
      https://support.google.com/analytics/answer/9267744
      https://firebase.google.com/docs/analytics/errors
    """
    if not name:
        return None
    if NON_ASCII_RE.search(name):
        return "medium"
    reasons = naming_reasons(name)
    invalid_chars = ASCII_INVALID_CHARS_RE.findall(name)
    hyphen_only = bool(invalid_chars) and all(ch == "-" for ch in invalid_chars)
    reserved_prefix = any(name.startswith(p) for p in RESERVED_NAME_PREFIXES)
    has_high_reason = (
        (bool(invalid_chars) and not hyphen_only)
        or name[:1].isdigit()
        or name.startswith("_")
        or (reserved_prefix and name not in GA4_AUTO_COLLECTED_PARAMS)
        or len(name) > MAX_EVENT_NAME_LEN
    )
    if reasons and has_high_reason:
        return "high"
    if hyphen_only or re.search(r"[A-Z]", name):
        return "low"
    return None


def naming_high_description(name: str) -> str:
    reasons = "・".join(naming_reasons(name))
    return (
        f"イベント名 '{name}' は名前のルールに合っていません（{reasons}）。"
        "受信記録があっても命名仕様への適合とは別です。既存の集計・設定への依存を確認して修正します"
    )


def naming_low_description(name: str) -> str:
    details = []
    if "-" in name:
        details.append("ハイフン")
    if re.search(r"[A-Z]", name):
        details.append("大文字")
    label = "・".join(details) or "表記のばらつき"
    return (
        f"イベント名 '{name}' に{label}を含む。受信・分析を止める重大な問題ではなく、修正は必須ではない。"
        "同じ意味のイベントを別表記で追加すると集計が分かれるため、新規作成時の表記だけ揃える"
    )


def naming_medium_description(name: str) -> str:
    return (
        f"イベント名 '{name}' に日本語・全角文字が含まれています。GA4で受信できても、"
        "外部ツールへのデータ連携でエラーや非対応になることがあるため、英数字と"
        "アンダースコアを使う名称へ変更します"
    )


def mechanical_checks(review_data: dict, reserved_words: list[str]) -> list[dict]:
    """決定論的ルールによる違反検出."""
    violations: list[dict] = []

    events = review_data.get("ga4", {}).get("events_observed", [])
    # 予約語リストから GA4 標準イベント（自動収集・拡張計測・推奨）は除外する。
    # これらは観測されて当然であり、衝突として検出すると誤検知になる。
    reserved_set = set(reserved_words) - GA4_STANDARD_EVENTS

    for event in events:
        name = event.get("name", "")
        if not name or name.startswith("("):
            continue

        sev = naming_severity(name)
        if sev == "high":
            violations.append({
                "id": make_id("V-", "命名規則", "event", name, "GA4"),
                "severity": "High",
                "category": "命名規則",
                "target_kind": "event",
                "target_name": name,
                "location": "GA4",
                "description": naming_high_description(name),
                "suggested_fix": suggest_name(name),
            })
        elif sev == "medium":
            violations.append({
                "id": make_id("V-", "命名規則", "event", name, "GA4"),
                "severity": "Medium",
                "category": "命名規則",
                "target_kind": "event",
                "target_name": name,
                "location": "GA4",
                "description": naming_medium_description(name),
                "suggested_fix": MANUAL_NAMING_REQUIRED,
            })
        elif sev == "low":
            violations.append({
                "id": make_id("V-", "命名規則", "event", name, "GA4"),
                "severity": "Low",
                "category": "命名規則",
                "target_kind": "event",
                "target_name": name,
                "location": "GA4",
                "description": naming_low_description(name),
                "suggested_fix": "",
            })

        if name in reserved_set:
            violations.append({
                "id": make_id("V-", "予約語衝突", "event", name, "GA4"),
                "severity": "Critical",
                "category": "予約語衝突",
                "target_kind": "event",
                "target_name": name,
                "location": "GA4",
                "description": f"イベント名 '{name}' はGA4予約語と衝突します",
                "suggested_fix": f"custom_{name}",
            })

    return dedupe_ids(violations)


def drop_naming_findings_for_unnecessary_events(violations: list[dict]) -> list[dict]:
    """不要な送信と判定したイベントを、命名修正の対象から外す。

    `gtm.dom` などのGTM内部イベントは、名前を直して残すのではなく送信そのものを
    止める対象である。健全性の指摘を先に採用し、同じ対象の命名指摘を削ることで、
    読み手に無駄な改名作業を促さない。
    """
    unnecessary = {
        v.get("target_name")
        for v in violations
        if v.get("category") == "内部名の流出" and v.get("target_kind") == "event"
    }
    if not unnecessary:
        return violations
    return [
        v for v in violations
        if not (
            v.get("target_kind") == "event"
            and v.get("target_name") in unnecessary
            and v.get("category") in _NAMING_CATEGORIES
        )
    ]


# ──────────────────────────────────────
# GTM コンテナの機械検出（ルールベース・AI 判断なし）
# 詳しい考え方は standards/gtm-tag-consolidation.md を参照。
# ──────────────────────────────────────

# 残骸候補の強いシグナル。役目を終えたことを示す語。有効状態なら停止漏れの疑いが強い。
# 英単語は前後を「英字以外（_ ・空白・記号・日本語・文末）」で区切るトークンとして照合する。
# \b は _ を語の一部とみなすため "old_purchase" を取りこぼす。代わりに英字 lookaround を使う。
# 日本語の語は区切り不要でそのまま照合する。
ZOMBIE_STRONG_RE = re.compile(
    r"(?<![A-Za-z])(?:old|test(?:ing)?|copy|deprecated|backup|bk)(?![A-Za-z])"
    r"|旧|テスト|コピー|削除|不要|使わ(?:ない|なく)",
    re.IGNORECASE,
)
# 残骸候補の弱いシグナル。連番コピーらしき末尾。誤検知しやすいので候補（Low）どまり。
ZOMBIE_WEAK_RE = re.compile(r"(?:[ _\-]\(?[2-9]\)?$|999$|_copy$|のコピー$)")

# 同種タグがこの本数以上あれば「量産」とみなす（軸の特定が必要）。
MASS_DUPLICATION_THRESHOLD = 10

# 「同一トリガー×同種別×同イベント名で複数発火」を二重計測候補として見るのは、
# GTM が送信先を型として保証しているタグ種別（GA4イベントタグ・基盤タグ・広告コンバージョン等）
# に限る。カスタムHTML（`html`）はヒートマップ・チャット・A/Bテストなど外部SaaSのスニペットを
# 貼る用途が主で、全ページ（同一トリガー）で複数本発火するのが仕様として正常な状態
# （standards/third-party-tools.md）。カスタムHTMLの中身（宛先）はエクスポートに現れないため、
# 機械では「本当にGA4へ二重送信しているか」を判定できない。判定できないものを候補に混ぜると
# 実際の案件で「計測ツール系はオールページで発火するので指摘に入れなくていい」という
# 誤検知が常態化するため、この種別は候補生成そのものから外す。
# 残るリスク（カスタムHTMLの中にGA4送信コードを直書きしている本当の二重計測）は機械で
# 判定できないため、standards/audit-items.md の目視項目に回す。
DUPLICATE_FIRING_EXCLUDED_TYPES = {"html"}


def parameter_mechanical_checks(review_data: dict, reserved_words: list[str]) -> list[dict]:
    """登録済みカスタム定義（イベントパラメータ）の命名・重複をルールベース検出する.

    対象は GA4 のカスタムディメンション/メトリクス（= 登録パラメータ名）。
    イベント名と同様に snake_case・長さ・予約語・重複を機械的にチェックする。
    """
    # 注: パラメータの予約語チェックは行わない。GA4標準パラメータ（ga_session_number 等）を
    # カスタムディメンションに登録する運用は正当で、予約語衝突として出すと誤検知になるため。
    violations: list[dict] = []

    cd = review_data.get("ga4", {}).get("custom_definitions", {})
    defs = []
    for d in cd.get("dimensions", []):
        defs.append((d, "ディメンション"))
    for m in cd.get("metrics", []):
        defs.append((m, "メトリクス"))

    seen: dict[str, int] = {}
    for d, kind in defs:
        pname = d.get("parameter_name", "")
        scope = d.get("scope", "")
        if not pname:
            continue
        seen[pname] = seen.get(pname, 0) + 1

        sev = naming_severity(pname)
        if sev in ("high", "medium"):
            reasons = "・".join(naming_reasons(pname))
            if sev == "medium":
                reasons = "日本語・全角文字を含み、外部ツールへのデータ連携でエラーや非対応になることがある"
            violations.append({
                # kind（ディメンション/メトリクス）まで識別要素に含める。同名パラメータが
                # 両方に登録されている場合でも、別の指摘として別IDになるようにするため。
                "id": make_id("V-P-", "パラメータ命名規則", "parameter", pname, scope, kind),
                "severity": "High" if sev == "high" else "Medium", "category": "パラメータ命名規則",
                "target_kind": "parameter", "target_name": pname, "scope": scope, "location": "GA4",
                "description": (
                    f"パラメータ名 '{pname}'（{kind}）は名前のルールに合っていません（{reasons}）。"
                    "安定した計測のため修正が必要です"
                ),
                "suggested_fix": suggest_name(pname),
            })
        elif sev == "low" and "-" in pname:
            violations.append({
                "id": make_id("V-P-", "パラメータ命名規則", "parameter", pname, scope, kind),
                "severity": "Low", "category": "パラメータ命名規則",
                "target_kind": "parameter", "target_name": pname, "scope": scope, "location": "GA4",
                "description": (
                    f"パラメータ名 '{pname}'（{kind}）にハイフンが含まれています。"
                    "現在の分析は続けられ、修正は必須ではありません"
                ),
                "suggested_fix": "",
            })
    for pname, n in seen.items():
        if n > 1:
            violations.append({
                "id": make_id("V-P-", "パラメータ重複", "parameter", pname),
                "severity": "Medium", "category": "パラメータ重複",
                "target_kind": "parameter", "target_name": pname, "scope": "", "location": "GA4",
                "description": f"パラメータ名 '{pname}' が {n} 件重複登録されています",
                # 括弧で始める＝「具体的な新名称ではなく注記」という規約（`suggest_name` の
                # MANUAL_NAMING_REQUIRED と同じ書式）。ここを生の文のまま返すと、
                # renderer._roadmap_action_text が target_kind=="parameter" 用の
                # 「`名前` を `修正案` に変更する」という名前置換の文型に流し込み、
                # 「`utm_source` を `重複定義を1つに統合する` に変更する」という壊れた文に
                # なっていた（試用フィードバックで検出）。
                "suggested_fix": "（重複定義を1つに統合する）",
            })

    return dedupe_ids(violations)


def gtm_mechanical_checks(review_data: dict) -> list[dict]:
    """GTM コンテナのルールベース検出（残骸・二重計測・値の使い回し・量産）.

    すべて事実抽出に徹し、AI 判断は含まない。出てくるのは「断定」ではなく「候補」で、
    確定には standards/gtm-tag-consolidation.md の Q1–Q6 に沿った個別確認が要る。
    review_data に GTM セクション（phase3 由来）が無ければ何も返さない。
    """
    gtm = review_data.get("gtm")
    if not gtm:
        return []
    tags = gtm.get("tags_detail", [])
    if not tags:
        return []

    violations: list[dict] = []

    def add(severity: str, category: str, target_name: str,
            description: str, suggested_fix: str, extra: str = "") -> None:
        # extra: 同じカテゴリ・対象名でも別の指摘になり得る場合の追加識別子
        # （トリガーID・種別など、件数や比率のような変動する値は使わない）。
        violations.append({
            "id": make_id("V-G-", category, "tag", target_name, extra),
            "severity": severity,
            "category": category,
            "target_kind": "tag",
            "target_name": target_name,
            "location": "GTM",
            "description": description,
            "suggested_fix": suggested_fix,
        })

    active = [t for t in tags if not t.get("paused")]

    # 1. 残骸候補 — old / test / コピー 等を名前に含むタグ
    for t in tags:
        name = t.get("name", "")
        if not name:
            continue
        is_active = not t.get("paused")
        if ZOMBIE_STRONG_RE.search(name):
            if is_active:
                add("High", "残骸候補", name,
                    f"タグ '{name}' は名前から旧版・テスト用の可能性がある。"
                    "有効状態のため停止漏れ・本番混入の疑い。",
                    "役目を終えていれば削除可否を確認し、停止または削除する")
            else:
                add("Low", "残骸候補", name,
                    f"タグ '{name}' は名前から旧版・テスト用の可能性がある（現在は一時停止）。",
                    "不要であれば削除する")
        elif ZOMBIE_WEAK_RE.search(name) and is_active:
            add("Low", "残骸候補", name,
                f"タグ '{name}' は連番コピーの可能性がある（要確認）。",
                "重複であれば一本化する")

    # 2. 二重計測候補 — 同一トリガー × 同種別 × 同送信先 × 同イベント名で複数発火
    # カスタムHTMLは対象外（DUPLICATE_FIRING_EXCLUDED_TYPES を参照）。
    groups: dict = defaultdict(list)
    for t in active:
        if t.get("type", "") in DUPLICATE_FIRING_EXCLUDED_TYPES:
            continue
        event_name = str(t.get("event_name", "")).strip()
        # 動的なイベント名は実行時まで値が確定しない。変数を使うこと自体は正常な共通化で、
        # 同じ変数名のタグが複数あるだけでは二重計測と判断できない。
        if not event_name or "{{" in event_name or "}}" in event_name:
            continue
        params = t.get("params", {})
        destination = str(
            t.get("destination")
            or params.get("measurementIdOverride")
            or params.get("measurementId")
            or params.get("tagId")
            or ""
        ).strip()
        if not destination or "{{" in destination or "}}" in destination:
            continue
        for trig in t.get("firing_trigger_ids", []):
            groups[(trig, t.get("type", ""), destination, event_name)].append(t)
    for (trig, ttype, destination, ev), members in groups.items():
        if len(members) < 2:
            continue
        # ブロックトリガーが各タグで異なれば実際には重複しない可能性が高い。
        # ブロックトリガーが揃っているグループだけを候補にして誤検知を抑える。
        block_sets = {tuple(sorted(m.get("blocking_trigger_ids", []))) for m in members}
        if len(block_sets) > 1:
            continue
        # タグ名の並び順を固定する。`members` は `tags_detail` の並び順（＝GTM APIが
        # 返した順）に依存するため、そのまま join すると入力の並びが変わるたびに
        # 対象名の文字列（＝表示・IDの両方の素）が変わってしまう。
        members_sorted = sorted(members, key=lambda m: m.get("name", ""))
        names = "、".join(m.get("name", "") for m in members_sorted)
        label = members_sorted[0].get("type_label") or ttype
        ev_part = f"・イベント '{ev}'" if ev else ""
        # 同じタグ名の並びが別のトリガー/種別/イベントの組でも生じ得るため、
        # グループキー自体を識別子に加える。
        add("Medium", "二重計測", names,
            f"同一トリガー(ID {trig})から同じ送信先 `{destination}` へ同種タグ（{label}{ev_part}）が "
            f"{len(members)} 本発火している。二重計上の可能性。発火条件・ブロックトリガーの差を確認する。",
            "重複であればどちらかに一本化する。意図的なら発火条件で分ける",
            extra=f"{trig}|{ttype}|{destination}|{ev}")

    # 3. 値の使い回し候補 — 本来固有のはずの識別子的パラメータが複数タグで共有
    by_type: dict = defaultdict(list)
    for t in active:
        by_type[t.get("type", "")].append(t)
    for ttype, members in by_type.items():
        if len(members) < 4:
            continue
        keys: set = set()
        for m in members:
            keys.update(m.get("params", {}).keys())
        for key in sorted(keys):
            values = [m.get("params", {}).get(key, "") for m in members]
            # 空値・変数参照（{{...}}）は値の固有性を比較できないので除外。
            nonempty = [v for v in values if v and not str(v).startswith("{{")]
            if len(nonempty) < 4:
                continue
            distinct = set(nonempty)
            # ほぼ固有（タグごとに違うはず）の識別子的パラメータに絞る:
            #   distinct がほとんどユニーク（floor 3、母数の 60% 以上）。
            #   それでいて重複値がある = 使い回しの疑い。
            #   boolean / enum のような少値パラメータはここで除外される。
            if len(distinct) < max(3, len(nonempty) * 0.6):
                continue
            shared = {v: c for v, c in Counter(nonempty).items() if c >= 2}
            if not shared:
                continue
            label = members[0].get("type_label") or ttype
            shared_desc = "、".join(f"'{v}'×{c}" for v, c in shared.items())
            add("Medium", "値の使い回し", f"{label}:{key}",
                f"種別「{label}」のパラメータ '{key}' は本来タグごとに固有のはずだが、"
                f"同じ値が複数タグで共有されている（{shared_desc}）。合算・設定漏れの可能性。"
                "意図的な共通化か確認する。",
                "店舗・商品など軸ごとに固有値を割り当てる。意図的共通化なら据え置く")

    # 4. 量産（情報提供）— 同種タグが閾値以上。
    # 現在の review_data にはトリガー条件の中身（URL/dataLayer/クリック要素）が無く、
    # 入力変数の判別元まで特定できない。本数・タグ名・送信値だけで構成案を作ると、
    # 異なる役割のタグを誤ってまとめさせるため、ここでは観察と棚卸しに留める。
    for ttype, n in Counter(t.get("type", "") for t in active).items():
        if n < MASS_DUPLICATION_THRESHOLD:
            continue
        label = next(
            (t.get("type_label") for t in active
             if t.get("type") == ttype and t.get("type_label")),
            ttype,
        )
        description = (
            f"種別「{label}」が {n} 本ある。同じ役割のタグが複数ある可能性はあるが、"
            "現在の取得データだけでは、店舗・商品・地域などの共通軸と、その軸を判別する"
            "URL・dataLayer・クリック要素を特定できない。"
        )
        suggested_fix = (
            "タグ名・発火条件・送信先・送信値を一覧化し、同じ役割か確認する。"
            "共通軸・入力キー・値の対応表を特定できるまでは統合を勧めない"
        )
        add("Low", "GTMタグ量産", label, description, suggested_fix, extra=ttype)

    return dedupe_ids(violations)


def llm_diagnose(
    review_data: dict,
    naming_conventions_md: str,
    reserved_words_md: str,
    api_key: str,
) -> list[dict]:
    """LLMによる違反検出."""
    from measurement_design.llm_client import complete_json

    summary = {
        "events": [e["name"] for e in review_data.get("ga4", {}).get("events_observed", [])],
        "key_events": review_data.get("ga4", {}).get("key_events", []),
    }

    prompt = f"""以下のGA4計測データを分析し、命名規則違反・表記ゆれ・意味的問題を検出してください。

## 現状のイベント名
{json.dumps(summary, ensure_ascii=False, indent=2)}

## 命名規則 (抜粋)
{naming_conventions_md[:2000]}

## 予約語 (抜粋)
{reserved_words_md[:1000]}

以下のJSON形式で違反を返してください（違反がなければ violations: [] ）:
{{
  "violations": [
    {{
      "id": "V-LLM-001",
      "severity": "Critical | High | Medium | Low",
      "category": "予約語衝突 | 表記ゆれ | 重複 | 命名規則 | 必須パラメータ不足 | 孤立 | 二重計測",
      "target_kind": "event | parameter | variable | tag | trigger",
      "target_name": "イベント名など",
      "location": "GA4 | GTM",
      "description": "違反の説明",
      "suggested_fix": "修正案"
    }}
  ]
}}"""

    try:
        raw = complete_json(prompt, model="claude-sonnet-4-6", max_tokens=2048, api_key=api_key)
        data = json.loads(raw)
        return data.get("violations", [])
    except (json.JSONDecodeError, KeyError, Exception):
        return []


def diagnose(
    review_data: dict,
    standards_dir: Path,
    api_key: str | None = None,
    data_dir: Path | None = None,
) -> list[dict]:
    """機械検出 + 実測ベースの健全性検出 + LLM 検出を合わせた違反リストを返す.

    data_dir を渡すと `health_checks` も実行する（セッション比・user_id の潰れ・
    検証環境の混入など、実測値の形から不備を逆算するチェック）。
    """
    reserved_words_file = standards_dir / "reserved-words.md"
    naming_file = standards_dir / "naming-conventions.md"

    reserved_words: list[str] = []
    reserved_md = ""
    if reserved_words_file.exists():
        reserved_md = reserved_words_file.read_text(encoding="utf-8")
        for line in reserved_md.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith(">") and " " not in line and ("_" in line or (line and line.isidentifier())):
                reserved_words.append(line)

    naming_md = ""
    if naming_file.exists():
        naming_md = naming_file.read_text(encoding="utf-8")

    violations = mechanical_checks(review_data, reserved_words)
    violations.extend(parameter_mechanical_checks(review_data, reserved_words))
    violations.extend(gtm_mechanical_checks(review_data))

    # 実測ベースの健全性検出。LLM より前に置く（数字で裏の取れた指摘を上に出す）。
    if data_dir is not None:
        from measurement_design.review.health_checks import health_checks
        violations.extend(health_checks(data_dir))

    if api_key:
        llm_violations = llm_diagnose(review_data, naming_md, reserved_md, api_key)
        # LLMの出力自体は呼び出しごとに変わり得るが、通し番号よりは指摘内容に
        # 沿ったIDのほうが実用上ましなので、他の検出と同じ方式に合わせる。
        for v in llm_violations:
            v["id"] = make_id(
                "V-LLM-", v.get("category", ""), v.get("target_kind", ""),
                v.get("target_name", ""), v.get("location", ""),
            )
        dedupe_ids(llm_violations)
        violations.extend(llm_violations)

    return drop_naming_findings_for_unnecessary_events(violations)
