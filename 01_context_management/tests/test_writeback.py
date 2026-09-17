"""writeback.py の軽量受付フロー用API（ensure_client_registered / save_measurement_ids /
save_kpi_info）のユニットテスト。

観点:
  - 未登録クライアントに最小限の profile.yaml だけを作る（他項目は書かない）
  - 既存ファイル・既存キーを壊さない（追記・更新であり、全消し上書きにならない）
  - GA4/GTM ID・KPI・key_events を個別に保存できる
  - append_finding の既存挙動（後方互換）が壊れていないこと
"""
from pathlib import Path

import yaml

import pytest

from context_store.loader import load_context
from context_store.writeback import (
    append_finding,
    ensure_client_registered,
    save_brand_preferences,
    save_business_profile,
    save_external_ai_approval,
    save_kpi_info,
    save_measurement_ids,
    save_output_format_preference,
)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_external_ai_approval_is_recorded_once_per_client_and_provider(tmp_path):
    save_external_ai_approval("approval-client", "anthropic", approved_date="2026-09-01", context_dir=tmp_path)
    save_external_ai_approval("approval-client", "anthropic", approved_date="2026-09-02", context_dir=tmp_path)
    save_external_ai_approval("approval-client", "openai", approved_date="2026-09-02", context_dir=tmp_path)

    ctx = load_context("approval-client", context_dir=tmp_path)
    approvals = ctx.profile["preferences"]["external_ai_approvals"]
    assert approvals == [
        {"provider": "anthropic", "approved_date": "2026-09-01"},
        {"provider": "openai", "approved_date": "2026-09-02"},
    ]
    assert ctx.external_ai_approved("anthropic") is True
    assert ctx.external_ai_approved("google") is False


def test_external_ai_approval_rejects_invalid_provider(tmp_path):
    with pytest.raises(ValueError, match="不正な外部AI provider"):
        save_external_ai_approval("approval-client", "../provider", context_dir=tmp_path)


# ---- ensure_client_registered ---------------------------------------------

def test_ensure_client_registered_creates_minimal_profile(tmp_path):
    path = ensure_client_registered("new-client", "新規サンプル社", context_dir=tmp_path)

    assert path == tmp_path / "new-client" / "profile.yaml"
    data = _read_yaml(path)
    assert data["client"]["client_id"] == "new-client"
    assert data["client"]["name"] == "新規サンプル社"
    # 業種・ターゲット像などフル登録項目は書かない
    assert "industry" not in data["client"]
    assert "target" not in data["client"]
    assert data["aliases"] == []


def test_ensure_client_registered_does_not_overwrite_existing_profile(tmp_path):
    client_dir = tmp_path / "existing"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump(
            {"client": {"client_id": "existing", "name": "既存社", "industry": "SaaS"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    ensure_client_registered("existing", "別の名前で呼ばれても上書きしない", context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert data["client"]["name"] == "既存社"  # 上書きされない
    assert data["client"]["industry"] == "SaaS"  # 既存キーも保持


def test_ensure_client_registered_fills_name_only_if_blank(tmp_path):
    client_dir = tmp_path / "blank-name"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "blank-name", "name": ""}}, allow_unicode=True),
        encoding="utf-8",
    )

    ensure_client_registered("blank-name", "後から埋める名前", context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert data["client"]["name"] == "後から埋める名前"


def test_ensure_client_registered_warns_on_blank_name(tmp_path, capsys):
    ensure_client_registered("no-name-given", "", context_dir=tmp_path)

    err = capsys.readouterr().err
    assert "name（サイト名）が空です" in err
    # 警告だけでエラーにはしない（書き込み自体は成功する）
    data = _read_yaml(tmp_path / "no-name-given" / "profile.yaml")
    assert data["client"]["client_id"] == "no-name-given"


def test_ensure_client_registered_warns_when_name_equals_client_id(tmp_path, capsys):
    ensure_client_registered("my-site", "my-site", context_dir=tmp_path)

    err = capsys.readouterr().err
    assert "client_id と同じ値" in err
    # 警告だけでエラーにはしない（指定した値はそのまま書き込まれる）
    data = _read_yaml(tmp_path / "my-site" / "profile.yaml")
    assert data["client"]["name"] == "my-site"


def test_ensure_client_registered_no_warning_for_proper_name(tmp_path, capsys):
    ensure_client_registered("proper-client", "ちゃんとしたサイト名", context_dir=tmp_path)

    err = capsys.readouterr().err
    assert err == ""


# ---- save_measurement_ids --------------------------------------------------

def test_save_measurement_ids_creates_new_file(tmp_path):
    path = save_measurement_ids(
        "c1", ga4_property_id="123456789", gtm_account_id="A1", gtm_container_id="GTM-X1",
        context_dir=tmp_path,
    )
    data = _read_yaml(path)
    assert data["ga4"]["property_id"] == "123456789"
    assert data["ga4"]["auth_method"] == "sa"
    assert data["gtm"]["gtm_account_id"] == "A1"
    assert data["gtm"]["gtm_container_id"] == "GTM-X1"


def test_search_console_and_form_pages_have_loader_shortcuts(tmp_path):
    save_measurement_ids(
        "search-client", search_console_site_url="sc-domain:example.invalid", context_dir=tmp_path,
    )
    save_kpi_info(
        "search-client",
        kpis=[{
            "kpi_id": "kpi_001",
            "events": ["generate_lead"],
            "form_pages": [{"path": "/contact/", "match_type": "exact"}],
        }],
        context_dir=tmp_path,
    )
    ctx = load_context("search-client", context_dir=tmp_path)
    assert ctx.search_console_site_url == "sc-domain:example.invalid"
    assert ctx.form_pages_by_event == {
        "generate_lead": [{"path": "/contact/", "match_type": "exact"}],
    }


def test_save_measurement_ids_saves_bigquery_connection(tmp_path):
    path = save_measurement_ids(
        "bq-client",
        bigquery_project_id="analytics-project",
        bigquery_dataset="analytics_123456789",
        context_dir=tmp_path,
    )

    data = _read_yaml(path)
    assert data["bigquery"] == {
        "project_id": "analytics-project",
        "dataset": "analytics_123456789",
    }


def test_save_measurement_ids_preserves_existing_bigquery_field(tmp_path):
    client_dir = tmp_path / "bq-client"
    client_dir.mkdir(parents=True)
    (client_dir / "measurement.yaml").write_text(
        yaml.safe_dump({"bigquery": {"project_id": "keep-project"}}), encoding="utf-8"
    )

    save_measurement_ids(
        "bq-client", bigquery_dataset="analytics_123456789", context_dir=tmp_path
    )

    data = _read_yaml(client_dir / "measurement.yaml")
    assert data["bigquery"] == {
        "project_id": "keep-project",
        "dataset": "analytics_123456789",
    }


def test_save_measurement_ids_preserves_other_blocks_and_fields(tmp_path):
    client_dir = tmp_path / "c2"
    client_dir.mkdir(parents=True)
    (client_dir / "measurement.yaml").write_text(
        yaml.safe_dump(
            {
                "ga4": {"property_id": "old", "auth_method": "oauth"},
                "search_console": {"site_url": "https://example.com/"},
                "bigquery": {"project_id": "proj", "dataset": "analytics_1"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    save_measurement_ids("c2", ga4_property_id="new-id", context_dir=tmp_path)

    data = _read_yaml(client_dir / "measurement.yaml")
    assert data["ga4"]["property_id"] == "new-id"
    assert data["ga4"]["auth_method"] == "oauth"  # 既存値を維持（新規デフォルトで上書きしない）
    assert data["search_console"]["site_url"] == "https://example.com/"  # 他ブロック保持
    assert data["bigquery"]["dataset"] == "analytics_1"


def test_save_measurement_ids_only_gtm_does_not_touch_ga4(tmp_path):
    client_dir = tmp_path / "c3"
    client_dir.mkdir(parents=True)
    (client_dir / "measurement.yaml").write_text(
        yaml.safe_dump({"ga4": {"property_id": "keep-me"}}, allow_unicode=True),
        encoding="utf-8",
    )

    save_measurement_ids("c3", gtm_account_id="A9", gtm_container_id="GTM-C9", context_dir=tmp_path)

    data = _read_yaml(client_dir / "measurement.yaml")
    assert data["ga4"]["property_id"] == "keep-me"
    assert data["gtm"]["gtm_account_id"] == "A9"
    assert data["gtm"]["gtm_container_id"] == "GTM-C9"


def test_save_measurement_ids_empty_args_are_noop_for_absent_blocks(tmp_path):
    path = save_measurement_ids("c4", context_dir=tmp_path)
    data = _read_yaml(path) or {}
    assert "ga4" not in data
    assert "gtm" not in data


# ---- save_kpi_info ----------------------------------------------------------

def test_save_kpi_info_appends_key_events_without_duplicates(tmp_path):
    client_dir = tmp_path / "c5"
    client_dir.mkdir(parents=True)
    (client_dir / "kpis.yaml").write_text(
        yaml.safe_dump({"key_events": ["contact_submit"]}, allow_unicode=True),
        encoding="utf-8",
    )

    save_kpi_info("c5", key_events=["contact_submit", "download_pdf"], context_dir=tmp_path)

    data = _read_yaml(client_dir / "kpis.yaml")
    assert data["key_events"] == ["contact_submit", "download_pdf"]  # 重複せず追記


def test_save_kpi_info_can_replace_key_events(tmp_path):
    client_dir = tmp_path / "c5-replace"
    client_dir.mkdir(parents=True)
    (client_dir / "kpis.yaml").write_text(
        yaml.safe_dump({"key_events": ["old_cv"]}, allow_unicode=True), encoding="utf-8",
    )

    save_kpi_info(
        "c5-replace", key_events=["new_cv", "new_cv"], replace_key_events=True,
        context_dir=tmp_path,
    )

    data = _read_yaml(client_dir / "kpis.yaml")
    assert data["key_events"] == ["new_cv"]


def test_save_kpi_info_upserts_kpi_by_id(tmp_path):
    client_dir = tmp_path / "c6"
    client_dir.mkdir(parents=True)
    (client_dir / "kpis.yaml").write_text(
        yaml.safe_dump(
            {"kpis": [{"kpi_id": "kpi_001", "name": "資料DL", "target_value": {"goal": 10}}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    save_kpi_info(
        "c6",
        kpis=[
            {"kpi_id": "kpi_001", "target_value": {"goal": 20}},  # 既存を更新
            {"kpi_id": "kpi_002", "name": "問い合わせ"},          # 新規追加
        ],
        context_dir=tmp_path,
    )

    data = _read_yaml(client_dir / "kpis.yaml")
    kpis = {k["kpi_id"]: k for k in data["kpis"]}
    assert kpis["kpi_001"]["name"] == "資料DL"  # 既存フィールドは維持
    assert kpis["kpi_001"]["target_value"]["goal"] == 20  # 指定フィールドは更新
    assert kpis["kpi_002"]["name"] == "問い合わせ"


# ---- save_output_format_preference ------------------------------------------

def test_output_formats_unset_returns_none_via_load_context(tmp_path):
    ensure_client_registered("no-pref", "未設定サンプル社", context_dir=tmp_path)

    ctx = load_context("no-pref", context_dir=tmp_path)

    # preferences 自体が無い → 「一度も聞いていない」。空リストと区別する。
    assert ctx.output_formats is None


def test_save_output_format_preference_md_only_is_explicit_empty_list(tmp_path):
    path = save_output_format_preference("c9", output_formats=[], context_dir=tmp_path)

    data = _read_yaml(path)
    assert data["preferences"]["output_formats"] == []

    ctx = load_context("c9", context_dir=tmp_path)
    assert ctx.output_formats == []  # None ではなく空リスト（聞き直さない）


def test_save_output_format_preference_multiple_formats(tmp_path):
    save_output_format_preference("c10", output_formats=["html", "pdf"], context_dir=tmp_path)

    ctx = load_context("c10", context_dir=tmp_path)
    assert ctx.output_formats == ["html", "pdf"]


def test_save_output_format_preference_preserves_other_keys(tmp_path):
    client_dir = tmp_path / "c11"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "client": {"client_id": "c11", "name": "既存社", "industry": "SaaS"},
                "aliases": ["old-c11"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    save_output_format_preference("c11", output_formats=["docx"], context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert data["client"]["name"] == "既存社"
    assert data["client"]["industry"] == "SaaS"
    assert data["aliases"] == ["old-c11"]
    assert data["preferences"]["output_formats"] == ["docx"]


def test_save_output_format_preference_overwrites_previous_choice(tmp_path):
    save_output_format_preference("c12", output_formats=[], context_dir=tmp_path)
    save_output_format_preference("c12", output_formats=["xlsx"], context_dir=tmp_path)

    ctx = load_context("c12", context_dir=tmp_path)
    assert ctx.output_formats == ["xlsx"]  # 追記ではなく置き換え


# ---- save_output_format_preference（gdoc/gsheet + URL） --------------------

def test_save_output_format_preference_gdoc_with_url_no_warning(tmp_path, capsys):
    ensure_client_registered("c13", "テスト社13", context_dir=tmp_path)
    save_output_format_preference(
        "c13",
        output_formats=["gdoc"],
        google_doc_url="https://docs.google.com/document/d/xxxx/edit",
        context_dir=tmp_path,
    )

    err = capsys.readouterr().err
    assert err == ""  # URLがあれば警告しない

    ctx = load_context("c13", context_dir=tmp_path)
    assert ctx.output_formats == ["gdoc"]
    assert ctx.google_doc_url == "https://docs.google.com/document/d/xxxx/edit"
    assert ctx.google_sheet_url is None  # gsheetは選んでいないので未設定のまま
    assert ctx.validate() == []


def test_save_output_format_preference_gdoc_without_url_warns(tmp_path, capsys):
    save_output_format_preference("c14", output_formats=["gdoc"], context_dir=tmp_path)

    err = capsys.readouterr().err
    assert "google_doc_url" in err

    ctx = load_context("c14", context_dir=tmp_path)
    assert ctx.google_doc_url is None
    assert any("google_doc_url" in w for w in ctx.validate())


def test_save_output_format_preference_gsheet_with_url(tmp_path, capsys):
    ensure_client_registered("c15", "テスト社15", context_dir=tmp_path)
    save_output_format_preference(
        "c15",
        output_formats=["html", "gsheet"],
        google_sheet_url="https://docs.google.com/spreadsheets/d/xxxx/edit",
        context_dir=tmp_path,
    )

    err = capsys.readouterr().err
    assert err == ""

    ctx = load_context("c15", context_dir=tmp_path)
    assert ctx.output_formats == ["html", "gsheet"]
    assert ctx.google_sheet_url == "https://docs.google.com/spreadsheets/d/xxxx/edit"
    assert ctx.validate() == []


def test_save_output_format_preference_unknown_value_warns(tmp_path, capsys):
    save_output_format_preference("c16", output_formats=["excel"], context_dir=tmp_path)

    err = capsys.readouterr().err
    assert "excel" in err

    ctx = load_context("c16", context_dir=tmp_path)
    assert any("excel" in w for w in ctx.validate())


def test_google_urls_unset_return_none_and_dont_break_load(tmp_path):
    # 既存クライアントの profile.yaml に google_doc_url / google_sheet_url が無い状態
    # （＝新しいキーを知らない旧データ）でも load_context() が落ちないことを固定する。
    ensure_client_registered("c17", "テスト社17", context_dir=tmp_path)
    save_output_format_preference("c17", output_formats=["html"], context_dir=tmp_path)

    ctx = load_context("c17", context_dir=tmp_path)
    assert ctx.google_doc_url is None
    assert ctx.google_sheet_url is None
    assert ctx.validate() == []  # htmlだけならURL不要で警告0件


def test_save_output_format_preference_preserves_url_when_not_passed(tmp_path):
    save_output_format_preference(
        "c18",
        output_formats=["gdoc"],
        google_doc_url="https://docs.google.com/document/d/first/edit",
        context_dir=tmp_path,
    )
    # URLを渡さずに再保存 → 既存URLは維持される（other save_* と同じ、渡した項目だけ更新する方式）
    save_output_format_preference("c18", output_formats=["gdoc", "html"], context_dir=tmp_path)

    ctx = load_context("c18", context_dir=tmp_path)
    assert ctx.output_formats == ["gdoc", "html"]
    assert ctx.google_doc_url == "https://docs.google.com/document/d/first/edit"


# ---- save_brand_preferences（差し色・ロゴ） --------------------------------

def test_brand_preferences_unset_returns_none_via_load_context(tmp_path):
    ensure_client_registered("no-brand", "未設定サンプル社", context_dir=tmp_path)

    ctx = load_context("no-brand", context_dir=tmp_path)

    # preferences.accent_color / logo_path 自体が無い → common/report_export の既定のまま
    assert ctx.accent_color is None
    assert ctx.logo_path is None


def test_save_brand_preferences_accent_color(tmp_path):
    path = save_brand_preferences("c13", accent_color="#1D4ED8", context_dir=tmp_path)

    data = _read_yaml(path)
    assert data["preferences"]["accent_color"] == "#1D4ED8"

    ctx = load_context("c13", context_dir=tmp_path)
    assert ctx.accent_color == "#1D4ED8"
    assert ctx.logo_path is None  # 指定していない項目はNoneのまま


def test_save_brand_preferences_logo_path(tmp_path):
    save_brand_preferences("c14", logo_path="assets/client-logo.svg", context_dir=tmp_path)

    ctx = load_context("c14", context_dir=tmp_path)
    assert ctx.logo_path == "assets/client-logo.svg"
    assert ctx.accent_color is None


def test_save_brand_preferences_rejects_invalid_hex(tmp_path):
    with pytest.raises(ValueError):
        save_brand_preferences("c15", accent_color="gold", context_dir=tmp_path)
    with pytest.raises(ValueError):
        save_brand_preferences("c15", accent_color="1D4ED8", context_dir=tmp_path)  # #無し


def test_save_brand_preferences_preserves_other_keys(tmp_path):
    client_dir = tmp_path / "c16"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "client": {"client_id": "c16", "name": "既存社"},
                "preferences": {"output_formats": ["html"]},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    save_brand_preferences("c16", accent_color="#059669", context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert data["client"]["name"] == "既存社"
    assert data["preferences"]["output_formats"] == ["html"]  # 既存のpreferencesキーを壊さない
    assert data["preferences"]["accent_color"] == "#059669"


def test_save_brand_preferences_overwrites_previous_choice(tmp_path):
    save_brand_preferences("c17", accent_color="#000000", context_dir=tmp_path)
    save_brand_preferences("c17", accent_color="#1D4ED8", context_dir=tmp_path)

    ctx = load_context("c17", context_dir=tmp_path)
    assert ctx.accent_color == "#1D4ED8"  # 追記ではなく置き換え


# ---- save_business_profile（サイトURL・役割・業種・toB/toC） ---------------

def test_business_profile_unset_returns_none_via_load_context(tmp_path):
    ensure_client_registered("no-biz", "未設定サンプル社", context_dir=tmp_path)

    ctx = load_context("no-biz", context_dir=tmp_path)

    client = ctx.profile.get("client", {})
    assert client.get("site_url") is None
    assert client.get("business_model") is None


def test_save_business_profile_saves_all_fields(tmp_path):
    path = save_business_profile(
        "c18",
        site_url="https://example.com",
        industry="SaaS",
        business="中小企業向け会計SaaSの開発・提供",
        business_model="toB",
        context_dir=tmp_path,
    )

    data = _read_yaml(path)
    assert data["client"]["site_url"] == "https://example.com"
    assert data["client"]["industry"] == "SaaS"
    assert data["client"]["business"] == "中小企業向け会計SaaSの開発・提供"
    assert data["client"]["business_model"] == "toB"

    ctx = load_context("c18", context_dir=tmp_path)
    assert ctx.profile["client"]["site_url"] == "https://example.com"


def test_save_business_profile_partial_update_keeps_other_fields(tmp_path):
    save_business_profile("c19", site_url="https://example.com", business_model="toB", context_dir=tmp_path)
    save_business_profile("c19", industry="人材", context_dir=tmp_path)

    ctx = load_context("c19", context_dir=tmp_path)
    client = ctx.profile["client"]
    assert client["site_url"] == "https://example.com"  # 既存値を保持
    assert client["business_model"] == "toB"  # 既存値を保持
    assert client["industry"] == "人材"  # 新規追加分だけ反映


def test_save_business_profile_preserves_name_and_other_top_level_keys(tmp_path):
    client_dir = tmp_path / "c20"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "client": {"client_id": "c20", "name": "既存社"},
                "aliases": ["old-c20"],
                "preferences": {"output_formats": ["html"]},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    save_business_profile("c20", site_url="https://example.jp", context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert data["client"]["name"] == "既存社"
    assert data["client"]["site_url"] == "https://example.jp"
    assert data["aliases"] == ["old-c20"]
    assert data["preferences"]["output_formats"] == ["html"]


def test_save_business_profile_empty_args_are_noop(tmp_path):
    client_dir = tmp_path / "c21"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "c21", "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )

    save_business_profile("c21", context_dir=tmp_path)

    data = _read_yaml(client_dir / "profile.yaml")
    assert "site_url" not in data["client"]
    assert data["client"]["name"] == "テスト社"


def test_save_business_profile_warns_on_unexpected_business_model(tmp_path, capsys):
    save_business_profile("c22", business_model="B2Bメイン・一部B2C", context_dir=tmp_path)

    err = capsys.readouterr().err
    assert "business_model が想定値" in err
    # 警告だけでエラーにはしない（自由記述のまま保存する）
    data = _read_yaml(tmp_path / "c22" / "profile.yaml")
    assert data["client"]["business_model"] == "B2Bメイン・一部B2C"


# ---- 統合: 軽量受付フローで作った内容を load_context で読める ----------------

def test_light_registration_roundtrip_via_load_context(tmp_path):
    ensure_client_registered("roundtrip", "ラウンドトリップサンプル社", context_dir=tmp_path)
    save_measurement_ids("roundtrip", ga4_property_id="123456789", context_dir=tmp_path)
    save_kpi_info("roundtrip", key_events=["cv_submit"], context_dir=tmp_path)

    ctx = load_context("roundtrip", context_dir=tmp_path)
    assert ctx.name == "ラウンドトリップサンプル社"
    assert ctx.ga4_property_id == "123456789"
    assert ctx.key_events == ["cv_submit"]
    # 軽量登録のみでも validate() は client.name があるので警告を出さない
    assert not any("client.name" in w for w in ctx.validate())


# ---- append_finding: リファクタ後も既存挙動が壊れていないこと ----------------

def test_append_finding_still_works_after_refactor(tmp_path):
    path = append_finding(
        "c7", "04_parameter_management", "監査完了", ["指摘1"], ["outputs/c7/report.md"],
        date="2026-08-22", context_dir=tmp_path,
    )
    data = _read_yaml(path)
    assert data["entries"][0]["agent"] == "04_parameter_management"
    assert data["entries"][0]["date"] == "2026-08-22"


def test_append_finding_recovers_from_broken_yaml(tmp_path):
    client_dir = tmp_path / "c8"
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "c8", "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )
    broken = client_dir / "analysis-history.yaml"
    broken.write_text("entries: [this is: not: valid: yaml", encoding="utf-8")

    path = append_finding("c8", "07_adhoc_analysis", "壊れたYAMLからの復旧", [], [], context_dir=tmp_path)

    data = _read_yaml(path)
    assert data["entries"][0]["agent"] == "07_adhoc_analysis"
    backups = list(client_dir.glob("analysis-history.yaml.broken-*"))
    assert len(backups) == 1
