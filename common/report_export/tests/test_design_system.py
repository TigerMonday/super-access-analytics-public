"""design_system/design-system.md への準拠を検証するテスト。

- 旧デザイン(青トークン#1f6feb)が完全に無くなっていること
- 新デザインのトークン(--gold/#D4AF37)・共通部品(table.s-table等)が使われていること
- 角丸を使っていないこと
- ロゴがdata URIとして埋め込まれていること
- 表の数値列に class="r" が付与され、数値でない列には付かないこと
- 引用が.calloutへ、見出しが.section-title/.sub-titleへ変換されること
- report-template.htmlが実在し、コアCSSを含むこと
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest

from report_export.html_export import build_html
from report_export.html_components import style_tables

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
DESIGN_SYSTEM_DIR = Path(__file__).resolve().parent.parent / "design_system"


def _build(md_name: str, *, logo_path: Path | None = None) -> str:
    md_path = FIXTURES_DIR / md_name
    md_text = md_path.read_text(encoding="utf-8")
    full_html, _ = build_html(md_text, md_path, logo_path=logo_path)
    return full_html


# ---------------------------------------------------------------------------
# 旧デザイン(青)が残っていないこと / 新トークンが使われていること
# ---------------------------------------------------------------------------


def test_old_blue_primary_token_is_gone():
    html = _build("with_tables.md")
    assert "#1f6feb" not in html
    assert "--primary" not in html


def test_gold_token_and_core_components_present():
    html = _build("with_tables.md")
    assert "--gold" in html
    assert "#D4AF37" in html
    assert "table.s-table" in html
    assert ".callout" in html
    assert ".section-title" in html
    assert ".kpi-box" in html
    assert ".finding-card" in html


def test_semantic_colors_are_limited_to_good_and_bad_results():
    html = _build("with_tables.md")
    assert "--red:#b91c1c" in html
    assert "--green:#15803d" in html
    assert "--orange" not in html
    assert ".kpi-box .kpi-sub.up,.metric-good{ color:var(--green); }" in html
    assert ".kpi-box .kpi-sub.down,.metric-bad{ color:var(--red); }" in html


def test_cards_do_not_use_decorative_top_or_side_borders():
    html = _build("with_tables.md")
    for selector in (".kpi-box", ".insight-box", ".visual-card", ".journey-step", ".priority-step", ".report-nav"):
        match = re.search(re.escape(selector) + r"\{([^}]*)\}", html)
        assert match is not None
        rule = match.group(1)
        assert "border-top" not in rule
        assert "border-left" not in rule


def test_border_radius_is_not_used():
    html = _build("with_tables.md")
    assert "border-radius" not in html


# ---------------------------------------------------------------------------
# ロゴのdata URI埋め込み
# ---------------------------------------------------------------------------


def test_logo_data_uri_is_embedded_when_logo_path_given():
    """--logo(logo_path)を指定したときだけ、data URIとして埋め込まれる。"""
    logo_path = DESIGN_SYSTEM_DIR / "logo-placeholder.svg"
    html = _build("with_tables.md", logo_path=logo_path)
    assert "data:image/svg+xml;base64," in html
    assert 'class="cover-logo"' in html

    logo_bytes = logo_path.read_bytes()
    expected_b64 = base64.b64encode(logo_bytes).decode("ascii")
    assert expected_b64 in html


def test_cover_logo_is_absent_by_default():
    """logo_path未指定(既定)では、ロゴのCSSも要素も出ない(固定サイズの空箱を残さない)。"""
    html = _build("with_tables.md")
    assert "data:image/svg+xml;base64," not in html
    assert "cover-logo" not in html


def test_report_template_exists_and_contains_core_css():
    template = (DESIGN_SYSTEM_DIR / "report-template.html").read_text(encoding="utf-8")
    assert "--gold:#D4AF37" in template
    assert "table.s-table" in template
    assert ".callout{" in template
    assert ".kpi-box{" in template
    assert "__TITLE__" in template
    assert "__BODY__" in template
    assert "__TOC__" in template
    assert "__COVER_LOGO_CSS__" in template
    assert "__COVER_LOGO_HTML__" in template


# ---------------------------------------------------------------------------
# 表: 数値列の右寄せ(class="r")判定
# ---------------------------------------------------------------------------


def test_numeric_columns_get_class_r_non_numeric_do_not():
    html = _build("with_tables.md")

    # チャネル別サマリー: チャネル(非数値)/セッション数/CV数/CVR(数値)
    table_m = re.search(r"<table[^>]*>.*?チャネル.*?</table>", html, re.DOTALL)
    assert table_m is not None
    table_html = table_m.group(0)

    assert '<th>チャネル</th>' in table_html  # 非数値列: class="r"を付けない
    assert '<th class="r">セッション数</th>' in table_html
    assert '<th class="r">CV数</th>' in table_html
    assert '<th class="r">CVR</th>' in table_html

    assert '<td class="r">12,340</td>' in table_html
    assert '<td>Organic Search</td>' in table_html
    # 空セルでも数値列の判定(この行はCV数が空)は崩れず class="r" が付く
    assert '<td class="r"></td>' in table_html


def test_first_column_has_min_width_to_avoid_deep_wrapping():
    """1列目に下限幅がある(3列目の説明文が長い表で項目名が縦に何行も割れる不具合の再修正)。
    URL等で元から幅が広い列には影響しない min-width であること(auto layoutの下限なので、
    自然幅がそれを上回る列では無風)。"""
    html = _build("with_tables.md")
    assert "table.s-table td:first-child{ min-width:10em; }" in html


def test_report_template_first_column_min_width_matches_design_system():
    # design-system.md のコアCSSはreport-template.htmlへ丸ごと埋め込む決まりのため、
    # 1列目の下限幅も両方に同じ値で存在すること。
    template = (DESIGN_SYSTEM_DIR / "report-template.html").read_text(encoding="utf-8")
    assert "table.s-table td:first-child{ min-width:10em; }" in template


def test_action_table_gets_pdf_safe_column_layout():
    raw = (
        "<table><thead><tr><th>対象</th><th>内容</th><th>修正案</th><th>重要度</th></tr></thead>"
        "<tbody><tr><td>URL</td><td>長い説明</td><td>長い修正案</td><td>Low</td></tr></tbody></table>"
    )
    styled = style_tables(raw)

    assert '<table class="s-table action-table">' in styled
    template = (DESIGN_SYSTEM_DIR / "report-template.html").read_text(encoding="utf-8")
    design_system = (DESIGN_SYSTEM_DIR / "design-system.md").read_text(encoding="utf-8")
    for source in (template, design_system):
        assert "table.s-table.action-table{ table-layout:fixed; }" in source
        assert "table.s-table.action-table th:nth-child(3){ width:25%; }" in source
        assert "table.s-table.action-table td:nth-child(-n+3) code{ white-space:normal; overflow-wrap:anywhere; }" in source
        assert "table.s-table.action-table td:last-child{ white-space:nowrap; }" in source


def test_non_action_table_does_not_get_action_layout_class():
    raw = (
        "<table><thead><tr><th>対象</th><th>内容</th><th>件数</th><th>状態</th></tr></thead>"
        "<tbody><tr><td>URL</td><td>説明</td><td>1</td><td>確認</td></tr></tbody></table>"
    )

    assert '<table class="s-table action-table">' not in style_tables(raw)


def test_table_bars_use_pdf_safe_solid_fill_instead_of_gradient_edge():
    """PDF印刷で境界だけが縦線になるため、セル内バーにグラデーションを使わない。"""
    template = (DESIGN_SYSTEM_DIR / "report-template.html").read_text(encoding="utf-8")
    assert ".table-bar-cell::before" in template
    assert "width:var(--bar-width); background:var(--gold-soft)" in template
    assert "linear-gradient(to left,var(--gold-soft)" not in template


# ---------------------------------------------------------------------------
# 引用 -> .callout / 見出し -> .section-title
# ---------------------------------------------------------------------------


def test_blockquote_becomes_callout_with_icon():
    html = _build("with_tables.md")
    assert '<div class="callout"><div class="callout-icon">!</div>' in html
    assert "<blockquote>" not in html


def test_headings_get_section_title_class():
    html = _build("with_tables.md")
    assert '<h2 id="_1" class="section-title">エグゼクティブサマリー</h2>' in html


def test_html_has_sticky_toc_and_section_tracking():
    html = _build("with_tables.md")
    assert '<aside class="report-nav" aria-label="目次">' in html
    assert 'href="#_1" data-section="_1"' in html
    assert "IntersectionObserver" in html
    assert 'Content-Security-Policy' in html
    assert "connect-src 'none'" in html


def test_inline_script_matches_csp_hash():
    html = _build("with_tables.md")
    script = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    allowed = re.search(r"script-src 'sha256-([^']+)'", html)
    assert script is not None and allowed is not None
    actual = base64.b64encode(hashlib.sha256(script.group(1).encode()).digest()).decode()
    assert actual == allowed.group(1)


def test_report_uses_fixed_16_9_slides_with_semantic_pagination():
    html = _build("with_tables.md")
    assert "scroll-snap-align:start" in html
    assert "--report-slide-width:1280px" in html
    assert "--report-slide-height:720px" in html
    assert "width:var(--report-slide-width); height:var(--report-slide-height)" in html
    assert "const semanticGroups = source =>" in html
    assert "const applyReadableDensity = sheet =>" in html
    assert "density-roomy" in html
    assert "density-comfortable" in html
    assert "1スライドに収まらない意味単位があります" in html
    assert "tbody" not in re.search(r"<script>(.*?)</script>", html, re.DOTALL).group(1)
    assert "@media screen and (max-width:1100px)" in html


def test_report_template_supports_qualitative_comparison_and_journey_visuals():
    """市場・顧客レポートの定性情報を、疑似数値グラフにせず図解できること。"""
    html = _build("with_tables.md")
    assert ".visual-grid{" in html
    assert ".visual-card.customer,.visual-card.competitor,.visual-card.company{" in html
    assert ".journey-flow{" in html
    assert ".journey-barrier{" in html
    assert ".journey-stimulus{" in html
    assert ".evidence-status.hypothesis{" in html
    assert ".status-card.action{" in html
    assert ".priority-flow{" in html
    assert ".priority-step.now,.priority-step.next,.priority-step.later{" in html
    assert ".journey-flow{ grid-template-columns:repeat(5,minmax(0,1fr));" in html


def test_consideration_block_is_visually_separated():
    html = _build("with_tables.md")
    assert '<div class="insight-box">今月のセッション数' in html
    assert '<strong>考察:</strong>' not in html


def test_chart_marker_builds_inline_svg_and_keeps_source_table():
    html = _build("with_tables.md")
    assert '<div class="report-chart"><svg' in html
    assert 'aria-label="チャネル別セッション"' in html
    assert '<rect ' in html
    assert '<table class="s-table">' in html
    assert html.index('<div class="table-scroll"><table class="s-table">') < html.index('<div class="report-chart">')


def test_chart_with_insight_is_ordered_table_then_text_then_chart():
    md = """# 月次レポート

## 月次推移

> **考察:** セッション減に対してCVRは維持しています。

<!-- chart: combo; title: 月次のセッション・CV数・CVR -->
| 月 | セッション | 問い合わせ数 | 問い合わせCVR |
|---|---:|---:|---:|
| 2026-08 | 100 | 2 | 2.00% |
"""
    html, _ = build_html(md, Path("monthly-report.md"))
    table_position = html.index('<div class="table-scroll"><table class="s-table">')
    insight_position = html.index('<div class="insight-box">', table_position)
    chart_position = html.index('<div class="report-chart report-chart-combo">', insight_position)

    assert table_position < insight_position < chart_position


def test_summary_period_headers_use_metadata_ranges():
    md = """# 期間表示

| 項目 | 内容 |
|---|---|
| 分析期間 | 2025年9月1日〜2026年8月31日 |
| 比較期間 | 2024年9月1日〜2025年8月31日 |

## サマリー

| 指標 | 当期 | 前年同期 | 増減 |
|---|---:|---:|---:|
| セッション | 100 | 90 | +11.1% |
"""
    html, _ = build_html(md, Path("period-report.md"))

    assert "当期（2025/9〜2026/8）" in html
    assert "前年同期（2024/9〜2025/8）" in html


def test_pictogram_marker_builds_accessible_summary_grid():
    html = _build("with_pictograms.md")
    assert '<div class="pictogram-grid">' in html
    assert html.count('class="pictogram-item"') == 3
    assert html.count('class="pictogram-icon"') == 3
    assert 'aria-hidden="true"' in html
    assert "自然検索の減少" in html
    assert "<table" not in html
    assert '<div class="asset-credit">' in html
    assert "Material Symbols Rounded (Google)" in html
    assert '<div class="asset-license-print"' in html
    assert "Apache License" in html
    assert ".asset-license-print{" in html
    assert "break-before:page" in html


def test_asset_credit_is_not_added_when_pictograms_are_unused():
    html = _build("with_tables.md")
    assert 'class="asset-credit"' not in html
    assert 'class="asset-license-print"' not in html


def test_report_has_optional_next_sheet_control_and_reduced_motion_support():
    html = _build("with_tables.md")
    assert '<button class="next-sheet" type="button" aria-label="次の面へ">' in html
    assert "frames[current + 1].scrollIntoView" in html
    assert "@media (prefers-reduced-motion:reduce)" in html
    assert ".next-sheet{ display:none; }" in html


# ---------------------------------------------------------------------------
# PDFのサイズはtest_exports_integrationで生成結果から検証する
# ---------------------------------------------------------------------------


def test_pdf_uses_same_fixed_slide_size_and_dom_footer():
    from report_export.pdf_export import _PDF_HEIGHT, _PDF_WIDTH

    assert _PDF_WIDTH == "13.333333in"
    assert _PDF_HEIGHT == "7.5in"
    html = _build("with_tables.md")
    assert 'content:"CONFIDENTIAL"' in html
    assert "content:counter(report-slide)" in html
