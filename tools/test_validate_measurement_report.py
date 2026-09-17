from validate_measurement_report import (
    PUBLIC_AUTOMATIC_ITEMS,
    PUBLIC_MANUAL_ITEMS,
    PUBLIC_SETTING_ITEMS,
    expected_internal_items,
    validate,
    validate_internal_contract,
    validate_public_report,
)


def _complete_public_report(items=PUBLIC_SETTING_ITEMS):
    automatic = [item for item in items if item in PUBLIC_AUTOMATIC_ITEMS]
    manual = [item for item in items if item in PUBLIC_MANUAL_ITEMS]
    fixed = "\n".join(f"| 設定 | {item} | △ | 未確認：設定未取得 | 必要事項を確認 |" for item in automatic)
    manual_rows = "\n".join(f"| {item} | GA4管理画面で手動確認 |" for item in manual)
    return f"""# 計測チェックレポート

## 基本設定

| カテゴリ | 確認項目 | 判定 | 結果 | 対応事項 |
|---|---|---|---|---|
{fixed}

### 管理画面でまとめて目視確認

| 目視確認項目 | 確認すること |
|---|---|
{manual_rows}

## 要対応・要確認

異常がある項目だけを掲載します。

## 改善順

依存関係の順に対応します。
"""


def test_internal_inventory_is_preserved_but_not_required_in_public_copy():
    assert len(expected_internal_items()) == 56
    assert validate_internal_contract() == []
    report = _complete_public_report()
    assert validate(report) == []
    assert "成果（キーイベント）の登録" not in report


def test_public_fixed_rows_must_appear_once():
    complete = _complete_public_report()
    missing = complete.replace(f"| 設定 | {PUBLIC_SETTING_ITEMS[0]} | △ | 未確認：設定未取得 | 必要事項を確認 |\n", "")
    assert any(PUBLIC_SETTING_ITEMS[0] in error for error in validate_public_report(missing))
    duplicate = complete + f"\n| 設定 | {PUBLIC_SETTING_ITEMS[0]} | △ | 未確認：設定未取得 | 必要事項を確認 |"
    assert any("現在2回" in error for error in validate_public_report(duplicate))


def test_old_chapters_and_unexpanded_templates_are_rejected():
    report = _complete_public_report() + "\n## 1. KPIと計測イベントの対応\n\n{{kpi_result}}\n"
    errors = validate_public_report(report)
    assert any("KPIと計測イベントの対応" in error for error in errors)
    assert any("未展開" in error for error in errors)


def test_custom_event_inventory_heading_is_rejected():
    report = _complete_public_report() + "\n### カスタムイベント（フォーム・成果導線）\n\n| イベント名 | 件数 |\n|---|---:|\n"
    errors = validate_public_report(report)
    assert any("カスタムイベント" in error for error in errors)


def test_standard_event_inventory_heading_is_rejected():
    report = _complete_public_report() + "\n## 指定期間の受信イベント\n\nイベント一覧\n"
    errors = validate_public_report(report)
    assert any("指定期間の受信イベント" in error for error in errors)


def test_gtm_variable_is_not_mistaken_for_template_placeholder():
    report = _complete_public_report() + "\nイベント名は `{{event_name}}` で動的に決まります。\n"
    assert not any("未展開" in error for error in validate_public_report(report))


def test_search_console_must_be_identified_as_manual():
    report = _complete_public_report().replace(
        "| Search Console連携 | GA4管理画面で手動確認 |",
        "| Search Console連携 | 連携済み |",
    )
    assert any("手動確認" in error for error in validate_public_report(report))


def test_tag_count_alone_must_not_drive_consolidation():
    report = _complete_public_report() + "\nGA4イベントタグが41本あるため一本化を推奨します。\n"
    assert any("タグ本数" in error for error in validate_public_report(report))


def test_consolidation_with_a_concrete_axis_is_allowed():
    report = _complete_public_report() + (
        "\nGA4イベントタグが41本あります。タグ名の共通部分で店舗を束ねる軸を特定し、"
        "店舗ID変数とルックアップ対応表を作って一本化します。\n"
    )
    assert not any("タグ本数" in error for error in validate_public_report(report))


def test_business_analysis_is_not_a_measurement_audit():
    assert any("範囲外" in error for error in validate_public_report("フォーム通過率は20%", []))
