"""profile.yaml の preferences.output_formats（成果物の書き出し先）のテスト。

背景: 試用フィードバックで「HTMLだと更新しづらいので、Googleドキュメント/スプレッドシートの
ように更新・版管理できる形で運用したい」という指摘があった。既存の `output_formats`
（html/pdf/docx/xlsx）に `gdoc` / `gsheet` を追加する形で対応する——同じ「どの形式で
出すか」という問いに答える場所を2つ作ると、どちらが正か分からなくなるため、新しいファイルは
作らず既存の器を拡張する（`kpis[].priority` の `primary_kpi` と同じ考え方）。

観点:
  - `schema.validate_output_format_preference` が未知の値・URL欠落を警告する
  - 未設定（output_formats キー自体が無い）は警告0件（他のvalidate_*と同じ方針）
  - gdoc/gsheetを選ばない既存クライアント（html等）は許容値を増やしても警告が増えない
    （tsuushi-check のような実クライアントの `output_formats: [html]` を壊さないことの確認）
"""
from context_store.schema import OUTPUT_FORMATS, validate_output_format_preference


def test_unset_output_formats_returns_no_warnings():
    assert validate_output_format_preference({}) == []
    assert validate_output_format_preference({"accent_color": "#111111"}) == []


def test_existing_formats_still_valid_after_extension():
    # 既存クライアント（例: html のみ）は許容値を gdoc/gsheet に広げても警告が増えないこと
    for existing in (["html"], ["html", "pdf"], ["docx"], ["xlsx"], []):
        assert validate_output_format_preference({"output_formats": existing}) == []
        assert set(existing) <= set(OUTPUT_FORMATS)


def test_unknown_format_value_warns():
    warnings = validate_output_format_preference({"output_formats": ["excel"]})
    assert len(warnings) == 1
    assert "excel" in warnings[0]


def test_gdoc_without_url_warns():
    warnings = validate_output_format_preference({"output_formats": ["gdoc"]})
    assert len(warnings) == 1
    assert "google_doc_url" in warnings[0]


def test_gdoc_with_url_no_warning():
    warnings = validate_output_format_preference(
        {"output_formats": ["gdoc"], "google_doc_url": "https://docs.google.com/document/d/x/edit"}
    )
    assert warnings == []


def test_gsheet_without_url_warns():
    warnings = validate_output_format_preference({"output_formats": ["gsheet"]})
    assert len(warnings) == 1
    assert "google_sheet_url" in warnings[0]


def test_gsheet_with_url_no_warning():
    warnings = validate_output_format_preference(
        {
            "output_formats": ["html", "gsheet"],
            "google_sheet_url": "https://docs.google.com/spreadsheets/d/x/edit",
        }
    )
    assert warnings == []


def test_both_gdoc_and_gsheet_missing_urls_warns_twice():
    warnings = validate_output_format_preference({"output_formats": ["gdoc", "gsheet"]})
    assert len(warnings) == 2
