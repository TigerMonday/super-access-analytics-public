"""クライアント向け計測チェック本文のユニットテスト。"""

from pathlib import Path

import pytest


TEMPLATES = Path(__file__).parent.parent.parent / "templates"
TEMPLATE_PATH = TEMPLATES / "check-report.template.md"

REVIEW_DATA = {
    "ga4": {
        "property": {
            "id": "123", "name": "テストサイト",
            "data_streams": [{"web_stream_data": {"measurement_id": "G-XXXXXXXXXX"}}],
        },
        "events_observed": [
            {"name": "session_start", "count": 100},
            {"name": "page_view", "count": 250},
            {"name": "generate_lead", "count": 8},
            {"name": "contact_complete", "count": 6},
        ],
    },
    "gtm": {
        "ga4_event_tags": [{
            "tag_name": "GA4 - 問い合わせ完了",
            "event_name": "contact_complete",
            "firing_trigger_names": ["問い合わせ完了ページ"],
            "destination": "G-XXXXXXXXXX",
        }],
    },
}

FIXED_ROWS = [
    {"area": "基本設定", "name": "拡張計測機能", "judgement": "ok", "state": "スクロール等が有効"},
    {"area": "基本設定", "name": "対象外ホスト・内部トラフィック", "judgement": "ok", "state": "対象外ホストの混入なし"},
    {"area": "基本設定", "name": "不要な参照元", "judgement": "ng", "state": "自社参照が12セッション"},
    {"area": "基本設定", "name": "クロスドメイン計測", "judgement": "ok", "state": "自己参照なし"},
    {"area": "基本設定", "name": "データ保持", "judgement": "ok", "state": "14か月"},
    {"area": "基本設定", "name": "Google シグナル", "judgement": "warn", "state": "利用目的を確認"},
    {"area": "基本設定", "name": "ユーザー提供データの収集", "judgement": "ok", "state": "有効"},
    {"area": "基本設定", "name": "レポート用識別子", "judgement": "ok", "state": "BLENDED"},
    {"area": "基本設定", "name": "アトリビューション", "judgement": "ok", "state": "データドリブン"},
    {"area": "連携", "name": "Google広告とのリンク", "judgement": "ok", "state": "1件"},
    {"area": "連携", "name": "BigQueryとのリンク", "judgement": "ok", "state": "1件"},
    {"area": "GTM", "name": "UA経由の計測継続性", "judgement": "ok", "state": "UAタグなし"},
    # 内部監査では保持するが公開本文には出さない行
    {"area": "内部", "name": "カスタムディメンション", "judgement": "ng", "state": "内部監査の指摘"},
]


def _render(violations=None, review_data=None, matrix_rows=None, **kwargs):
    from measurement_design.review.renderer import render_check_report

    return render_check_report(
        violations or [], review_data or REVIEW_DATA, TEMPLATE_PATH, "internal-client-id",
        matrix_rows=FIXED_ROWS if matrix_rows is None else matrix_rows, **kwargs,
    )


def test_report_uses_registered_display_name_and_url():
    result = _render(client_display_name="株式会社サンプル", site_url="https://example.jp/")  # leak-ok: テスト専用の架空社名
    assert result.startswith("# 株式会社サンプル 計測チェックレポート")  # leak-ok: 同上
    assert "**対象URL**: https://example.jp/" in result
    assert "internal-client-id" not in result


def test_public_report_has_only_three_reader_sections():
    result = _render()
    assert "## 1. 計測設定の確認結果" in result
    assert "## 2. 要対応・要確認" in result
    assert "## 3. 改善順" in result
    assert "固定チェック" not in result
    assert "固定8項目" not in result
    assert "ユーザーが判断に使う8項目" not in result
    assert "内部監査" not in result
    assert "指定期間の受信イベント" not in result
    for removed in ("KPIと計測イベントの対応", "パラメータ", "GTM設定の指摘", "GTMとGA4の不整合", "確認できなかったこと"):
        assert removed not in result


def test_measurement_settings_projection_shows_complete_public_settings_table():
    result = _render()
    section = result.split("## 1. 計測設定の確認結果", 1)[1].split("## 2.", 1)[0]
    for name in (
        "拡張計測機能", "Google タグの管理：ページ上の設定の重複インスタンスを無視します",
        "計測対象ホスト", "クロスドメイン設定", "内部トラフィックの定義",
        "除外する参照のリスト", "セッションのタイムアウト", "Google シグナル",
        "ユーザー提供データの収集", "地域とデバイスに関する詳細なデータの収集",
        "イベントデータの保持", "Internal Traffic", "現在の設定と定義",
        "モデルとルックバック期間", "Google広告とのリンク", "BigQueryとのリンク",
        "UA経由の計測継続性",
    ):
        assert section.count(f"| {name} |") == 1
    assert "| カテゴリ | 確認項目 | 判定 | 結果 | 対応事項 |" in section
    assert "### 管理画面でまとめて目視確認" in section
    assert "| 目視確認項目 | 確認すること |" in section
    automatic_part, manual_part = section.split("### 管理画面でまとめて目視確認", 1)
    assert "Google タグの管理：ページ上の設定の重複インスタンスを無視します" not in automatic_part
    assert "Google タグの管理：ページ上の設定の重複インスタンスを無視します" in manual_part
    assert "カスタムディメンション" not in section
    assert "内部監査の指摘" not in result
    assert "| Search Console連携 |" in manual_part


def test_legacy_internal_names_are_mapped_to_public_labels():
    result = _render(matrix_rows=[
        {"name": "内部トラフィックの除外", "judgement": "ok", "state": "混入なし"},
        {"name": "参照元の除外", "judgement": "ok", "state": "自己参照なし"},
        {"name": "生データの書き出し（BigQuery）", "judgement": "ok", "state": "連携あり"},
    ])
    assert "| データストリーム | 計測対象ホスト | ○ | 混入なし |" in result
    assert "| データストリーム | 除外する参照のリスト | ○ | 自己参照なし |" in result
    assert "| 連携 | BigQueryとのリンク | ○ | 連携あり |" in result


def test_received_event_inventory_is_not_a_public_section():
    review = {"ga4": {"property": {"name": "t"}, "events_observed": [
        {"name": "session_start", "count": 100},
        {"name": "page_view", "count": 250},
        {"name": "generate_lead", "count": 8},
        {"name": "view_article", "count": 20},
        {"name": "contact_form", "count": 10},
        {"name": "bot_access", "count": 5},
    ]}}
    result = _render(review_data=review)
    for removed in (
        "指定期間の受信イベント", "標準イベント", "session_start", "page_view",
        "generate_lead", "view_article", "contact_form", "bot_access",
    ):
        assert removed not in result


def test_confirmed_conversion_points_are_summarized_without_inventory():
    result = _render(kpi_rows=[
        {"kpi_name": "予約完了", "event": "reserve_complete", "source": "registered", "count": 12},
        {"kpi_name": "購入完了", "event": "purchase_complete", "source": "registered", "count": 3},
    ])

    assert "コンバージョンイベントは2件中2件で" in result
    assert "reserve_complete" not in result
    assert "purchase_complete" not in result


def test_confirmed_conversion_point_with_zero_events_becomes_a_finding():
    result = _render(
        kpi_rows=[{
            "kpi_name": "予約完了", "event": "reserve_complete", "source": "registered", "count": 0,
        }],
        kpi_name_mismatches=[{
            "registered_event": "reserve_complete",
            "candidates": [{"event": "reservation_complete", "count": 18}],
        }],
    )

    assert "コンバージョンイベントは1件中0件で" in result
    assert "予約完了（reserve_complete）" in result
    assert "reservation_complete" in result
    assert "実際に成果が無かったのか" in result


def test_unverified_conversion_count_is_not_reported_as_zero():
    result = _render(kpi_rows=[{
        "kpi_name": "予約完了", "event": "reserve_complete", "source": "registered", "count": None,
    }])

    assert "全イベント件数を取得できていないため未確認" in result
    assert "0件とは判定していません" in result
    assert "直近30日で0件" not in result
    assert "予約完了（reserve_complete）" not in result


def test_inferred_conversion_candidate_is_not_treated_as_confirmed():
    result = _render(kpi_rows=[{
        "kpi_name": "予約完了", "event": "generate_lead", "source": "candidate", "count": 0,
    }])

    assert "事前に確認したコンバージョンポイントが無い" in result
    assert "generate_lead" not in result


def test_url_variant_inventory_is_not_a_client_finding():
    finding = {
        "id": "url", "severity": "Low", "category": "レポートの分裂",
        "target_kind": "page", "target_name": "52組のURL", "location": "GA4",
        "description": "末尾スラッシュ違い", "suggested_fix": "正規化する",
    }
    result = _render([finding])
    assert "52組のURL" not in result
    assert "末尾スラッシュ違い" not in result


def test_parameter_findings_are_internal_only_and_never_return_in_roadmap():
    finding = {
        "id": "p", "severity": "High", "category": "パラメータ命名規則",
        "target_kind": "parameter", "target_name": "userId", "location": "GA4",
        "description": "パラメータを修正", "suggested_fix": "user_id",
    }
    result = _render([finding])
    assert "userId" not in result
    assert "パラメータを修正" not in result


def test_vague_gtm_inventory_finding_is_internal_only():
    finding = {
        "id": "g", "severity": "Low", "category": "GTMタグ量産",
        "target_kind": "tag", "target_name": "41本", "location": "GTM",
        "description": "41本を一本化する", "suggested_fix": "一本化する",
    }
    result = _render([finding])
    assert "41本を一本化" not in result
    assert "一本化する" not in result


def test_dynamic_gtm_event_name_is_not_an_anomaly():
    review = {
        "ga4": {"property": {"name": "t"}, "events_observed": [{"name": "scroll", "count": 5}]},
        "gtm": {"ga4_event_tags": [{"tag_name": "可変イベント", "event_name": "{{event_name}}"}]},
    }
    finding = {
        "id": "dynamic", "severity": "Low", "category": "判定不能", "target_kind": "tag",
        "target_name": "{{event_name}}", "location": "GTM", "description": "イベント名が変数で判定不能",
        "suggested_fix": "変数を確認する",
    }
    result = _render([finding], review_data=review)
    assert "イベント名が変数で判定不能" not in result
    assert "変数を確認する" not in result


def test_uppercase_and_hyphen_are_low_reference_and_not_in_roadmap():
    finding = {
        "id": "n", "severity": "High", "category": "命名規則", "target_kind": "event",
        "target_name": "Click-CTA", "location": "GA4",
        "description": "イベント名 'Click-CTA' に大文字・ハイフンがある",
        "suggested_fix": "click_cta",
    }
    result = _render([finding])
    findings = result.split("## 2. 要対応・要確認", 1)[1].split("## 3.", 1)[0]
    roadmap = result.split("## 3. 改善順", 1)[1]
    assert "Low（参考）" in findings
    assert "対応は不要" in findings
    assert "Click-CTA" not in roadmap


def test_japanese_event_name_is_medium_and_actionable():
    finding = {
        "id": "jp", "severity": "Low", "category": "命名規則", "target_kind": "event",
        "target_name": "資料請求完了", "location": "GA4",
        "description": "日本語のイベント名は外部連携で扱えない場合がある",
        "suggested_fix": "document_request_complete",
    }
    result = _render([finding])
    assert "| Medium |" in result
    assert "資料請求完了" in result.split("## 3. 改善順", 1)[1]


def test_actual_health_and_gtm_duplicate_findings_are_public():
    findings = [
        {"id": "spa", "severity": "High", "category": "SPA計測ギャップ", "target_kind": "measurement",
         "target_name": "ページタイトル", "location": "GA4", "description": "URL遷移後も同じタイトル",
         "suggested_fix": "画面遷移ごとにタイトルを更新する"},
        {"id": "dup", "severity": "High", "category": "多重発火", "target_kind": "tag",
         "target_name": "purchaseタグ2本", "location": "GTM", "description": "同じ条件で同じイベントを送る",
         "suggested_fix": "プレビューで同時発火を確認する"},
    ]
    result = _render(findings)
    assert "URL遷移後も同じタイトル" in result
    assert "同じ条件で同じイベントを送る" in result
    assert "purchaseタグ2本" in result.split("## 3. 改善順", 1)[1]


def test_unknown_medium_list_is_hidden_but_unassigned_is_public():
    medium = {"id": "m", "severity": "Medium", "category": "流入分類", "target_kind": "measurement",
              "target_name": "medium値", "location": "GA4", "description": "既定の語彙に無い値が3種類",
              "suggested_fix": "確認する"}
    unassigned = {"id": "u", "severity": "High", "category": "流入分類", "target_kind": "measurement",
                  "target_name": "Unassigned", "location": "GA4", "description": "Unassignedが12%ある",
                  "suggested_fix": "公式のチャネル定義と照合する"}
    result = _render([medium, unassigned])
    assert "既定の語彙に無い値" not in result
    assert "Unassignedが12%" in result


def test_missing_static_gtm_events_are_not_a_public_custom_event_check():
    review = {
        "ga4": {
            "property": {"name": "t", "data_streams": [{"web_stream_data": {"measurement_id": "G-XXXXXXXXXX"}}]},
            "events_observed": [{"name": "page_view", "count": 10}],
        },
        "gtm": {"ga4_event_tags": [
            {"tag_name": f"tag-{i}", "event_name": f"custom_{i}", "destination": "G-XXXXXXXXXX"}
            for i in range(8)
        ]},
    }
    result = _render(review_data=review)
    findings = result.split("## 2. 要対応・要確認", 1)[1].split("## 3.", 1)[0]
    assert "静的な送信設定があるイベント" not in findings
    assert "GTM・GA4突合" not in findings
    assert "custom_0" not in findings


def test_missing_event_check_ignores_paused_other_destination_and_unknown_destination():
    review = {
        "ga4": {
            "property": {"name": "t", "data_streams": [{"web_stream_data": {"measurement_id": "G-XXXXXXXXXX"}}]},
            "events_observed": [{"name": "page_view", "count": 10}],
        },
        "gtm": {"ga4_event_tags": [
            {"tag_name": "停止中", "event_name": "paused_event", "destination": "G-XXXXXXXXXX", "paused": True},
            {"tag_name": "別送信先", "event_name": "other_event", "destination": "G-OTHER"},
            {"tag_name": "送信先不明", "event_name": "unknown_event", "destination": ""},
        ]},
    }
    result = _render(review_data=review)
    assert "GTM・GA4突合" not in result
    assert "paused_event" not in result
    assert "other_event" not in result
    assert "unknown_event" not in result


def test_no_removed_placeholder_or_valid_gtm_variable_is_stripped(tmp_path):
    original = TEMPLATE_PATH.read_text(encoding="utf-8") + "\nGTM例: {{event_name}}\n"
    path = tmp_path / "template.md"
    path.write_text(original.replace("\n", "\r\n"), encoding="utf-8")
    from measurement_design.review.renderer import render_check_report
    result = render_check_report([], REVIEW_DATA, path, "c", matrix_rows=FIXED_ROWS)
    assert "{{public_summary}}" not in result
    assert "{{fixed_check_table}}" not in result
    assert "{{event_name}}" in result


def test_save_and_notes_files(tmp_path):
    from measurement_design.review.renderer import ensure_check_report_notes, save_check_report
    report = save_check_report("report", tmp_path)
    assert report.read_text(encoding="utf-8") == "report"
    notes, created = ensure_check_report_notes(tmp_path, "client")
    assert created is True
    notes.write_text("手書き", encoding="utf-8")
    same, created_again = ensure_check_report_notes(tmp_path, "client")
    assert created_again is False
    assert same.read_text(encoding="utf-8") == "手書き"


def test_archive_moves_generated_outputs_but_not_notes(tmp_path):
    from measurement_design.review.renderer import archive_check_report_before_overwrite
    (tmp_path / "check-report.md").write_text("md", encoding="utf-8")
    (tmp_path / "check-report.html").write_text("html", encoding="utf-8")
    (tmp_path / "check-report-notes.md").write_text("notes", encoding="utf-8")
    archived = archive_check_report_before_overwrite(tmp_path)
    assert len(archived) == 2
    assert (tmp_path / "check-report-notes.md").exists()
    assert {p.suffix for p in archived} == {".md", ".html"}


@pytest.mark.parametrize("legacy", ["V-001", "V-P-010", "V-H-001", "V-G-003", "V-LLM-001"])
def test_notes_file_has_legacy_ids(tmp_path, legacy):
    from measurement_design.review.renderer import notes_file_has_legacy_ids
    path = tmp_path / "notes.md"
    path.write_text(legacy, encoding="utf-8")
    assert notes_file_has_legacy_ids(path) is True
    path.write_text("V-a1b2c3", encoding="utf-8")
    assert notes_file_has_legacy_ids(path) is False
