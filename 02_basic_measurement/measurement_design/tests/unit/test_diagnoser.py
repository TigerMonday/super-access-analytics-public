"""diagnoser.py のユニットテスト."""
import pytest
from unittest.mock import patch


REVIEW_DATA = {
    "ga4": {
        "property": {"id": "123", "name": "Test", "timezone": "Asia/Tokyo", "currency": "JPY"},
        "key_events": ["purchase", "FormSubmit"],
        "custom_definitions": {"dimensions": [], "metrics": []},
        "events_observed": [
            {"name": "page_view", "count": 15000},
            {"name": "purchase", "count": 1200},
            {"name": "FormSubmit", "count": 300},  # 大文字 — 命名違反
            {"name": "click_CTA", "count": 500},   # 大文字 — 命名違反
            {"name": "error", "count": 10},         # 予約語衝突
        ],
    }
}

RESERVED_WORDS = ["error", "first_open", "first_visit", "ad_click"]


def test_mechanical_checks_detects_uppercase():
    from measurement_design.review.diagnoser import mechanical_checks
    violations = mechanical_checks(REVIEW_DATA, RESERVED_WORDS)
    names = [v["target_name"] for v in violations]
    assert "FormSubmit" in names
    assert "click_CTA" in names


def test_mechanical_checks_detects_reserved_word():
    from measurement_design.review.diagnoser import mechanical_checks
    violations = mechanical_checks(REVIEW_DATA, RESERVED_WORDS)
    reserved_violations = [v for v in violations if v["category"] == "予約語衝突"]
    assert any(v["target_name"] == "error" for v in reserved_violations)


def test_mechanical_checks_valid_event_not_flagged():
    from measurement_design.review.diagnoser import mechanical_checks
    violations = mechanical_checks(REVIEW_DATA, RESERVED_WORDS)
    names_flagged = [v["target_name"] for v in violations]
    assert "page_view" not in names_flagged
    assert "purchase" not in names_flagged


def test_mechanical_checks_ids_stable_across_rerun_and_reordering():
    """指摘IDが再取得のたびに振り直される不具合の再現条件そのものを固定する.

    `events_observed` の並び順は GA4 API が保証しないため、データを取り直すと
    順序が変わることがある。旧実装（通し番号）はこれで同じ指摘に別のIDが
    振られていた（実際に click_CTA / FormSubmit が入れ替わって再現した）。
    """
    from measurement_design.review.diagnoser import mechanical_checks

    events = REVIEW_DATA["ga4"]["events_observed"]
    reordered = {
        "ga4": {
            **REVIEW_DATA["ga4"],
            "events_observed": list(reversed(events)),
        }
    }

    v1 = mechanical_checks(REVIEW_DATA, RESERVED_WORDS)
    v2 = mechanical_checks(reordered, RESERVED_WORDS)

    id_by_target_1 = {v["target_name"]: v["id"] for v in v1}
    id_by_target_2 = {v["target_name"]: v["id"] for v in v2}
    assert id_by_target_1 == id_by_target_2
    assert id_by_target_1["FormSubmit"] != id_by_target_1["click_CTA"]


def test_mechanical_checks_returns_list_of_dicts():
    from measurement_design.review.diagnoser import mechanical_checks
    violations = mechanical_checks(REVIEW_DATA, RESERVED_WORDS)
    assert isinstance(violations, list)
    for v in violations:
        assert "id" in v
        assert "severity" in v
        assert "category" in v
        assert "target_name" in v
        assert "description" in v


def test_ga4_standard_events_not_flagged_as_reserved():
    """自動収集・拡張計測・推奨イベントは予約語衝突として検出しない (誤検知防止)."""
    from measurement_design.review.diagnoser import mechanical_checks

    review = {
        "ga4": {
            "events_observed": [
                {"name": "scroll", "count": 34000},          # 拡張計測
                {"name": "page_view", "count": 22000},       # 自動収集
                {"name": "session_start", "count": 17000},   # 自動収集
                {"name": "user_engagement", "count": 13000}, # 自動収集
                {"name": "first_visit", "count": 12000},     # 自動収集
                {"name": "file_download", "count": 1},        # 拡張計測
                {"name": "share", "count": 9},                # 推奨
            ]
        }
    }
    # これらがすべて予約語リストに載っていても衝突として扱わない
    reserved = ["scroll", "page_view", "session_start", "user_engagement",
                "first_visit", "file_download", "share"]
    violations = mechanical_checks(review, reserved)
    assert violations == []


def test_hyphen_is_low_and_does_not_prompt_a_fix():
    from measurement_design.review.diagnoser import mechanical_checks, to_snake_case

    review = {"ga4": {"events_observed": [
        {"name": "contact_curious-about_form", "count": 4},
    ]}}
    violations = mechanical_checks(review, [])
    assert len(violations) == 1
    assert violations[0]["severity"] == "Low"
    assert violations[0]["suggested_fix"] == ""

    assert to_snake_case("click_CTA") == "click_cta"
    assert to_snake_case("Form Submit!") == "form_submit"


def test_to_snake_case_splits_camel_case():
    """小文字化より先に camelCase の語境界へ '_' を入れる (旧: contactId -> contactid).

    旧実装は name.lower() を先に行っており、語境界が消えて snake_case を要求する
    規約と矛盾した修正案（contactid）を出していた。
    """
    from measurement_design.review.diagnoser import to_snake_case

    assert to_snake_case("contactId") == "contact_id"
    assert to_snake_case("AddToCart") == "add_to_cart"
    assert to_snake_case("userID") == "user_id"
    assert to_snake_case("HTTPServer") == "http_server"
    # すでに snake_case のものは変えない
    assert to_snake_case("contact_id") == "contact_id"
    assert to_snake_case("cv_reserve") == "cv_reserve"


def test_to_snake_case_gives_up_on_non_ascii():
    """日本語を含む名前は機械的に導出せず、手動命名を促す.

    旧実装は ASCII 部分だけを残していたため 'Wスリム注射_予約フォーム送信完了' が
    'w' に、日本語のみの名前が 'custom_event' になっていた（いずれも無意味な候補）。
    """
    from measurement_design.review.diagnoser import (
        MANUAL_NAMING_REQUIRED, suggest_name, to_snake_case,
    )

    assert to_snake_case("Wスリム注射_予約フォーム送信完了") == ""
    assert to_snake_case("コラムページ到達") == ""
    assert to_snake_case("tel_yokohama_4580含む") == ""

    assert suggest_name("コラムページ到達") == MANUAL_NAMING_REQUIRED
    assert suggest_name("contactId") == "contact_id"


def test_suggest_name_does_not_repeat_reserved_prefix_as_the_fix():
    """予約プレフィックス違反は snake_case 変換だけでは直らない (試用フィードバックで検出).

    `ga_client_id` は使用可能文字・先頭文字ともに既に正しいため、旧実装の
    `to_snake_case` だけを通すと入力と同じ `ga_client_id` がそのまま返っていた
    （「修正案 ga_client_id → ga_client_id」という直しようのない候補）。
    予約語衝突（`custom_{name}`）と同じ考え方で `custom_` を足し、予約プレフィックスの
    外に出す。既にプレフィックス以外の理由で候補が変わる場合はそのまま使う。
    """
    from measurement_design.review.diagnoser import suggest_name

    fix = suggest_name("ga_client_id")
    assert fix != "ga_client_id"
    assert fix == "custom_ga_client_id"

    for name in ("firebase_screen", "google_tag_data", "gtag.event"):
        fix = suggest_name(name)
        assert fix != name
        assert not fix.startswith(("firebase_", "ga_", "google_", "gtag."))


def test_mechanical_checks_flags_japanese_event_names_for_data_integration():
    """日本語イベント名はデータ連携上の修正対象にする。"""
    from measurement_design.review.diagnoser import mechanical_checks

    review = {"ga4": {"events_observed": [{"name": "コラムページ到達", "count": 218259}]}}
    violations = mechanical_checks(review, [])

    assert len(violations) == 1
    assert violations[0]["severity"] == "Medium"
    assert "データ連携" in violations[0]["description"]
    assert violations[0]["suggested_fix"].startswith("（")


def test_naming_severity_tiers():
    """命名の分類: 支障のある仕様外(High) / 参考情報(Low) / 対象外(None)."""
    from measurement_design.review.diagnoser import naming_severity

    # Low: ハイフンと大文字は既存名の修正を必須にしない
    assert naming_severity("contact_curious-about_form") == "low"
    # High: ハイフン以外の記号・数字始まり・アンダースコア始まり・40文字超
    assert naming_severity("contact form") == "high"
    assert naming_severity("10percent") == "high"
    assert naming_severity("_internal_event") == "high"
    assert naming_severity("a" * 41) == "high"
    # Low: 大文字を含むだけ（実害は分裂のおそれのみで、GA4の仕様には違反しない）
    assert naming_severity("click_CTA") == "low"
    assert naming_severity("FormSubmit") == "low"
    # Medium: GA4で受信できても外部データ連携に支障が出る日本語・全角文字
    assert naming_severity("コラムページ到達") == "medium"
    assert naming_severity("click_ボタン") == "medium"
    # 問題なし
    assert naming_severity("click_cta") is None


def test_naming_severity_exempts_ga4_auto_collected_session_params():
    """`ga_session_number` 等はGoogle自身が付けた自動収集パラメータ名で、利用者が
    作った名前ではない。予約プレフィックス違反として誤検知しない
    （実データで `ga_session_number` を「記録されない」と誤検知した実例あり。
    実際は正常に記録され続けている既定の項目だった）。
    """
    from measurement_design.review.diagnoser import naming_severity

    assert naming_severity("ga_session_number") is None
    assert naming_severity("ga_session_id") is None
    # 利用者が新規に付けた ga_ 始まりの名前は、引き続き仕様外として検出する
    assert naming_severity("ga_custom_flag") == "high"


def test_mechanical_checks_flags_uppercase_as_low_not_violation():
    """大文字を含むだけの名前は Low（注意）とし、「違反」と書かない."""
    from measurement_design.review.diagnoser import mechanical_checks

    review = {"ga4": {"events_observed": [{"name": "click_CTA", "count": 500}]}}
    violations = mechanical_checks(review, [])

    assert len(violations) == 1
    assert violations[0]["severity"] == "Low"
    assert "違反" not in violations[0]["description"]
    assert violations[0]["suggested_fix"] == ""


def test_mechanical_checks_treats_hyphen_as_low_reference_only():
    from measurement_design.review.diagnoser import mechanical_checks

    review = {"ga4": {"events_observed": [{"name": "form-submit", "count": 50}]}}
    violations = mechanical_checks(review, [])

    assert len(violations) == 1
    assert violations[0]["severity"] == "Low"
    assert "修正は必須ではない" in violations[0]["description"]
    assert violations[0]["suggested_fix"] == ""


def test_unnecessary_gtm_internal_event_is_removed_from_naming_findings():
    from measurement_design.review.diagnoser import drop_naming_findings_for_unnecessary_events

    naming = {
        "id": "V-N", "severity": "High", "category": "命名規則",
        "target_kind": "event", "target_name": "gtm.dom", "location": "GA4",
        "description": "名前のルール外", "suggested_fix": "gtm_dom",
    }
    health = {
        "id": "V-H", "severity": "High", "category": "内部名の流出",
        "target_kind": "event", "target_name": "gtm.dom", "location": "GA4",
        "description": "GTM内部イベントを送信している", "suggested_fix": "送信を止める",
    }

    assert drop_naming_findings_for_unnecessary_events([naming, health]) == [health]


def test_parameter_checks_ignore_uppercase_only():
    """パラメータ名の大文字だけは指摘しない。"""
    from measurement_design.review.diagnoser import parameter_mechanical_checks

    review = {"ga4": {"custom_definitions": {
        "dimensions": [{"parameter_name": "contactId", "scope": "EVENT"}],
        "metrics": [],
    }}}
    violations = parameter_mechanical_checks(review, [])

    naming = [v for v in violations if v["category"] == "パラメータ命名規則"]
    assert naming == []


def test_parameter_checks_ids_unaffected_by_other_violations_count():
    """他の指摘が増減しても、対象の指摘のIDが変わらないことを確認する."""
    from measurement_design.review.diagnoser import parameter_mechanical_checks

    base = {"ga4": {"custom_definitions": {
        "dimensions": [{"parameter_name": "日本語項目", "scope": "EVENT"}],
        "metrics": [],
    }}}
    more = {"ga4": {"custom_definitions": {
        "dimensions": [
            {"parameter_name": "日本語項目", "scope": "EVENT"},
            {"parameter_name": "別項目", "scope": "EVENT"},
        ],
        "metrics": [],
    }}}

    v_base = parameter_mechanical_checks(base, [])
    v_more = parameter_mechanical_checks(more, [])

    id_base = next(v["id"] for v in v_base if v["target_name"] == "日本語項目")
    id_more = next(v["id"] for v in v_more if v["target_name"] == "日本語項目")
    assert id_base == id_more
    # 増えた指摘は別のIDになる（衝突しない）
    other_id = next(v["id"] for v in v_more if v["target_name"] == "別項目")
    assert other_id != id_more


def test_llm_diagnose_returns_violations():
    """llm_diagnose は LLM(complete_json) の JSON を解釈して違反リストを返す."""
    from measurement_design.review.diagnoser import llm_diagnose

    llm_json = '{"violations": [{"id": "V-LLM-001", "severity": "High", "category": "表記ゆれ", "target_kind": "event", "target_name": "cv_signup", "location": "GA4", "description": "signup_cv と表記ゆれ", "suggested_fix": "signup に統一"}]}'

    with patch("measurement_design.llm_client.complete_json", return_value=llm_json):
        result = llm_diagnose(REVIEW_DATA, "naming rules", "reserved words", "fake-key")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["category"] == "表記ゆれ"


def test_llm_diagnose_handles_invalid_json():
    from measurement_design.review.diagnoser import llm_diagnose

    with patch("measurement_design.llm_client.complete_json", return_value="invalid json"):
        result = llm_diagnose(REVIEW_DATA, "naming", "reserved", "fake-key")

    assert isinstance(result, list)
    assert len(result) == 0


def test_diagnose_mechanical_only(tmp_path):
    from measurement_design.review.diagnoser import diagnose

    reserved_file = tmp_path / "reserved-words.md"
    reserved_file.write_text("# Reserved\nerror\nfirst_open", encoding="utf-8")

    result = diagnose(REVIEW_DATA, tmp_path)

    assert isinstance(result, list)
    assert len(result) > 0
    assert any(v["target_name"] == "FormSubmit" for v in result)


def test_diagnose_with_llm_api(tmp_path):
    from measurement_design.review.diagnoser import diagnose

    reserved_file = tmp_path / "reserved-words.md"
    reserved_file.write_text("# Reserved\nerror", encoding="utf-8")

    naming_file = tmp_path / "naming-conventions.md"
    naming_file.write_text("# Naming\nsmall letters only", encoding="utf-8")

    llm_json = '{"violations": [{"id": "V-LLM-001", "severity": "High", "category": "表記ゆれ", "target_kind": "event", "target_name": "test", "location": "GA4", "description": "test", "suggested_fix": "test"}]}'

    with patch("measurement_design.llm_client.complete_json", return_value=llm_json):
        result = diagnose(REVIEW_DATA, tmp_path, api_key="test-key")

    assert isinstance(result, list)
    assert any(v["id"].startswith("V-LLM") for v in result)
