from pathlib import Path

from report_quality_check import check_file, main, tables_without_intro


def test_markdown_reports_candidates_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    original = "# 分析\n\n本レポートでは、以下にまとめます。\n"
    path.write_text(original, encoding="utf-8")

    findings = check_file(path)

    assert {item.rule for item in findings} == {"generic-heading", "stock-phrase"}
    assert path.read_text(encoding="utf-8") == original


def test_html_ignores_css_and_script(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    path.write_text(
        "<style>.x{content:'本レポートでは'}</style>"
        "<script>const x='以下にまとめます'</script>"
        "<h2>結論</h2><p>数値を確認した。</p>",
        encoding="utf-8",
    )

    assert check_file(path) == []


def test_html_ignores_pictogram_labels_and_print_only_asset_license(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    path.write_text(
        '<div class="pictogram-title">課題</div>'
        '<p>確認できた事実です。</p>'
        '<div class="asset-license-print"><pre>' + "A" * 100 + ".</pre></div>",
        encoding="utf-8",
    )

    assert check_file(path) == []


def test_inline_html_markup_does_not_inflate_markdown_sentence_length(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text('<div class="visual-card"><div class="visual-title">結論</div></div>\n', encoding="utf-8")

    assert check_file(path) == []


def test_unprompted_meeting_and_appendix_headings_are_flagged(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("## 次の打ち合わせで決めること\n\n## 付録：根拠\n", encoding="utf-8")

    assert [item.rule for item in check_file(path)] == ["unprompted-section", "unprompted-section"]


def test_long_sentence_is_a_warning_but_exit_code_is_zero(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("あ" * 81 + "。", encoding="utf-8")

    findings = check_file(path)

    assert [item.rule for item in findings] == ["long-sentence"]
    assert main([str(path)]) == 0


def test_missing_file_is_error(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.md")]) == 2


def test_production_context_is_flagged_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    original = "AI分析だけに限定しません。\nご指摘を受けて変更しました。\n"
    path.write_text(original, encoding="utf-8")
    assert [item.rule for item in check_file(path)] == ["production-context"] * 2
    assert path.read_text(encoding="utf-8") == original


def test_scope_and_material_limitations_are_not_production_context(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("対象は国内法人向けの分析支援です。\n前期データが欠損しているため前年比は算出できません。\nヒアリング情報（2026年9月）です。\n", encoding="utf-8")
    assert check_file(path) == []


def test_production_context_in_visible_html(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    path.write_text("<style>/* ご指摘を受けて */</style><p>チャット内で決めた内容です。</p>", encoding="utf-8")
    assert [item.rule for item in check_file(path)] == ["production-context"]


def test_storage_explanations_are_flagged(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("保存済みファイルには日別の行がありません。\n分析の根拠から外します。", encoding="utf-8")
    assert [item.rule for item in check_file(path)] == ["production-context"] * 2


def test_basic_analysis_requires_plot_chart_marker(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text("# 基本分析レポート\n\n<!-- chart: table-bars; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n", encoding="utf-8")
    assert {item.rule for item in check_file(path)} == {
        "missing-plot-chart", "missing-pictogram-summary", "missing-required-basic-analysis-section",
    }


def test_basic_analysis_warns_when_summary_period_headers_are_implicit(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n| 指標 | 当期 | 前期 | 増減 |\n|---|---:|---:|---:|\n"
        "| セッション | 100 | 90 | +11.1% |\n",
        encoding="utf-8",
    )

    assert "missing-period-range-in-basic-analysis" in {item.rule for item in check_file(path)}


def test_basic_analysis_accepts_explicit_summary_period_headers(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n"
        "| 指標 | 当期（2025/9〜2026/8） | 前年同期（2024/9〜2025/8） | 増減 |\n"
        "|---|---:|---:|---:|\n| セッション | 100 | 90 | +11.1% |\n",
        encoding="utf-8",
    )

    assert "missing-period-range-in-basic-analysis" not in {item.rule for item in check_file(path)}

    path.write_text("# 基本分析レポート\n\n<!-- pictograms: issue,insight -->\n| A | B |\n|---|---|\n| x | y |\n\n<!-- chart: bar; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n", encoding="utf-8")
    assert {item.rule for item in check_file(path)} == {"missing-required-basic-analysis-section"}


def test_basic_analysis_html_requires_rendered_chart_and_no_markers(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.html"
    path.write_text("<h1>基本分析レポート</h1><!-- chart: bar --><table></table>", encoding="utf-8")
    assert {item.rule for item in check_file(path)} == {
        "missing-plot-chart", "missing-pictogram-summary", "unresolved-visual-marker",
        "missing-required-basic-analysis-section",
    }

    path.write_text('<h1>基本分析レポート</h1><div class="pictogram-grid"></div><div class="report-chart"><svg></svg></div>', encoding="utf-8")
    assert {item.rule for item in check_file(path)} == {"missing-required-basic-analysis-section"}


def test_basic_analysis_rejects_internal_audit_sections_in_markdown(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n<!-- pictograms: issue,insight -->\n| A | B |\n|---|---|\n| x | y |\n\n"
        "<!-- chart: bar; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n\n"
        "## 5. 流入パラメータの状態\n\n## 9. 流入元の表記ゆれ\n\n## 10. 計測対象のホスト名\n",
        encoding="utf-8",
    )
    findings = [item for item in check_file(path)
                if item.rule == "internal-audit-section-in-basic-analysis"]
    assert [item.snippet for item in findings] == [
        "5. 流入パラメータの状態", "9. 流入元の表記ゆれ", "10. 計測対象のホスト名",
    ]
    assert main([str(path)]) == 1


def test_basic_analysis_rejects_internal_audit_sections_in_html(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.html"
    path.write_text(
        '<div class="pictogram-grid"></div><div class="report-chart"><svg></svg></div>'
        '<h2>9. 流入元の表記ゆれ</h2><h2>10. 計測対象のホスト名</h2>',
        encoding="utf-8",
    )
    assert [item.rule for item in check_file(path)
            if item.rule == "internal-audit-section-in-basic-analysis"] == [
        "internal-audit-section-in-basic-analysis",
        "internal-audit-section-in-basic-analysis",
    ]


def test_basic_analysis_allows_only_the_fixed_client_facing_sections(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n<!-- pictograms: issue,insight -->\n| A | B |\n|---|---|\n| x | y |\n\n"
        "<!-- chart: bar; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n\n"
        "## 分析サマリー\n\n## 1. 月次推移\n\n> **考察:** テスト\n\n"
        "## 2. チャネル別パフォーマンス（前年同期比つき）\n\n> **考察:** テスト\n\n"
        "## 3. ランディングページ別（入口として機能しているページ）\n\n> **考察:** テスト\n\n"
        "## 4. ページ別（PV上位10件）\n\n> **考察:** テスト\n\n"
        "## 5. デバイス別（mobile / desktop / tablet）\n\n> **考察:** テスト\n\n"
        "## 6. 新規/リピーター別\n\n> **考察:** テスト\n\n"
        "## 7. フォーム通過率\n\n> **考察:** テスト\n\n"
        "## 8. 自然検索（Search Console）\n\n> **考察:** テスト\n\n"
        "## 9. 成果に至るページ遷移\n\n> **考察:** テスト\n\n"
        "## 分析の前提・制約\n",
        encoding="utf-8",
    )
    assert check_file(path) == []

    path.write_text(path.read_text(encoding="utf-8") + "\n## 優先して取り組む課題\n", encoding="utf-8")
    assert [item.rule for item in check_file(path)] == [
        "nonstandard-section-in-basic-analysis",
    ]


def test_basic_analysis_rejects_fixed_sections_in_the_wrong_order(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n<!-- pictograms: issue,insight -->\n| A | B |\n|---|---|\n| x | y |\n\n"
        "<!-- chart: bar; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n\n"
        "## 分析サマリー\n\n## 2. チャネル別パフォーマンス\n\n> **考察:** テスト\n\n"
        "## 1. 月次推移\n\n> **考察:** テスト\n\n"
        "## 3. ランディングページ別\n\n> **考察:** テスト\n\n"
        "## 4. ページ別\n\n> **考察:** テスト\n\n"
        "## 5. デバイス別\n\n> **考察:** テスト\n\n"
        "## 6. 新規/リピーター別\n\n> **考察:** テスト\n\n"
        "## 7. フォーム通過率\n\n> **考察:** テスト\n",
        encoding="utf-8",
    )
    assert [item.rule for item in check_file(path)] == ["basic-analysis-section-order"]


def test_basic_analysis_requires_an_insight_for_each_numeric_section(tmp_path: Path) -> None:
    path = tmp_path / "basic-analysis-report.md"
    path.write_text(
        "# 基本分析\n\n<!-- pictograms: issue,insight -->\n| A | B |\n|---|---|\n| x | y |\n\n"
        "<!-- chart: bar; title: 比較 -->\n| A | B |\n|---|---:|\n| x | 1 |\n\n"
        "## 分析サマリー\n\n"
        "## 1. 月次推移\n\n本文だけです。\n\n"
        "## 2. チャネル別パフォーマンス\n\n> **考察:** テスト\n\n"
        "## 3. ランディングページ別\n\n> **考察:** テスト\n\n"
        "## 4. ページ別\n\n> **考察:** テスト\n\n"
        "## 5. デバイス別\n\n> **考察:** テスト\n\n"
        "## 6. 新規/リピーター別\n\n> **考察:** テスト\n\n"
        "## 7. フォーム通過率\n\n> **考察:** テスト\n",
        encoding="utf-8",
    )
    assert [item.rule for item in check_file(path)] == [
        "missing-insight-in-basic-analysis-section",
    ]


def test_each_major_report_has_its_own_visual_contract(tmp_path: Path) -> None:
    cases = {
        "00_3c_persona_journey_report.md": "missing-pictogram-summary",
        "cvr-improvement-plan.md": "missing-pictogram-summary",
    }
    for name, expected_rule in cases.items():
        path = tmp_path / name
        path.write_text("# report\n", encoding="utf-8")
        assert [item.rule for item in check_file(path)] == [expected_rule]


def test_warns_when_narrative_follows_markdown_table(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "この結果から、相談導線を先に直します。\n",
        encoding="utf-8",
    )
    findings = [item for item in check_file(path) if item.rule == "narrative-after-table"]
    assert [(item.line, item.snippet) for item in findings] == [
        (7, "この結果から、相談導線を先に直します。"),
    ]


def test_allows_source_or_footnote_after_markdown_table(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "出典：GA4（2026年9月取得）\n",
        encoding="utf-8",
    )
    assert all(item.rule != "narrative-after-table" for item in check_file(path))


def test_requires_subheading_before_intro_for_the_next_table(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "次は施策候補を比較します。\n\n"
        "| 施策 | 優先度 |\n|---|---:|\n| 導線改善 | 1 |\n",
        encoding="utf-8",
    )
    assert [item.snippet for item in check_file(path)
            if item.rule == "narrative-after-table"] == ["次は施策候補を比較します。"]


def test_allows_subheading_before_intro_for_the_next_table(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "### 次の施策候補\n\n次は施策候補を比較します。\n\n"
        "| 施策 | 優先度 |\n|---|---:|\n| 導線改善 | 1 |\n",
        encoding="utf-8",
    )
    assert all(item.rule != "narrative-after-table" for item in check_file(path))


def test_finds_narrative_after_source_or_html_comment(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "出典：GA4\n\n<!-- 内部メモ -->\n\n- 次は相談導線を直します。\n",
        encoding="utf-8",
    )
    findings = [item for item in check_file(path) if item.rule == "narrative-after-table"]
    assert [(item.line, item.snippet) for item in findings] == [
        (11, "- 次は相談導線を直します。"),
    ]


def test_ignores_table_examples_inside_code_fence(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# レポート\n\n```markdown\n| 指標 | 値 |\n|---|---:|\n| 相談 | 10 |\n\n"
        "この文章もコード例です。\n```\n",
        encoding="utf-8",
    )
    assert all(item.rule != "narrative-after-table" for item in check_file(path))


def test_finds_major_report_table_without_intro() -> None:
    text = (
        "# 計測チェック\n\n## 確認結果\n\n"
        "| 項目 | 判定 |\n|---|---|\n| データ保持 | ○ |\n"
    )

    assert tables_without_intro(text) == [(5, "| 項目 | 判定 |")]


def test_major_report_table_with_intro_is_not_warned(tmp_path: Path) -> None:
    path = tmp_path / "check-report.md"
    path.write_text(
        "# 計測チェック\n\n## 確認結果\n\n"
        "主要設定の状態と確認根拠をまとめます。\n\n"
        "| 項目 | 判定 |\n|---|---|\n| データ保持 | ○ |\n",
        encoding="utf-8",
    )

    assert all(item.rule != "table-without-intro" for item in check_file(path))


def test_missing_required_visual_is_a_blocking_error(tmp_path: Path) -> None:
    path = tmp_path / "cvr-improvement-plan.md"
    path.write_text("# サイト改善\n", encoding="utf-8")
    assert main([str(path)]) == 1


def test_client_report_rejects_internal_labels(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "# 顧客理解\n\n### 立上げ補完型（会社側仮説）\n\n"
        "利用者未確認です。`persona_basis: service_derived`\n",
        encoding="utf-8",
    )
    findings = [item for item in check_file(path) if item.rule == "internal-label-in-client-report"]
    assert len(findings) == 2
    assert main([str(path)]) == 1


def test_internal_artifacts_may_keep_internal_labels(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "evidence.md"
    path.write_text("persona_basis: service_derived\n会社側仮説\n", encoding="utf-8")
    assert all(item.rule != "internal-label-in-client-report" for item in check_file(path))


def test_market_report_requires_polite_style(tmp_path: Path) -> None:
    path = tmp_path / "00_3c_persona_journey_report.md"
    path.write_text(
        "# 市場・顧客理解\n\n<!-- pictograms: insight,analysis,target -->\n"
        "市場は拡大している。競合との差を検証する。\n",
        encoding="utf-8",
    )
    findings = [item for item in check_file(path) if item.rule == "market-report-non-polite-style"]
    assert len(findings) == 1
    assert main([str(path)]) == 1

    path.write_text(
        "# 市場・顧客理解\n\n<!-- pictograms: insight,analysis,target -->\n"
        "市場は拡大しています。競合との差を検証します。\n",
        encoding="utf-8",
    )
    assert all(item.rule != "market-report-non-polite-style" for item in check_file(path))
