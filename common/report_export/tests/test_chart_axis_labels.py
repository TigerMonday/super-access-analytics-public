"""グラフの横軸ラベルの折り返し・拡幅のテスト(report_export.html_components)。

以前は `label = row[0][:12]` で12文字に機械的に切っていたため、週次の日付レンジ表記
(例: "2026/08/02〜08/08"、16文字)やチャネル名(例: "Organic Search"、14文字)が
切れて重なる不具合があった。切って"…"にする代わりに、折り返す・グラフ幅を広げる
方針にしたことを検証する(common/report_export/src/report_export/html_components.py の
_fit_axis_label / _chart_svg)。
"""

from __future__ import annotations

import re

from report_export.html_components import _fit_axis_label, style_charts


def _chart_html(kind: str, title: str, label_header: str, value_header: str, rows: list[tuple[str, str]]) -> str:
    """style_charts() への入力(グラフ指定コメント + markdown由来のテーブルHTML)を組み立てる。"""
    body_rows = "".join(
        f'<tr><td>{label}</td><td class="r">{value}</td></tr>' for label, value in rows
    )
    table = (
        '<div class="table-scroll"><table class="s-table">'
        f"<thead><tr><th>{label_header}</th><th class=\"r\">{value_header}</th></tr></thead>"
        f"<tbody>{body_rows}</tbody></table></div>"
    )
    return f"<!-- chart: {kind}; title: {title} -->\n{table}"


def _viewbox_width(html: str) -> int:
    m = re.search(r'viewBox="0 0 (\d+) \d+"', html)
    assert m, f"viewBoxが見つからない: {html[:200]}"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# _fit_axis_label: 折り返しの単体テスト
# ---------------------------------------------------------------------------


def test_short_label_is_kept_as_single_line():
    assert _fit_axis_label("Direct") == ("Direct", None)


def test_week_range_wraps_at_wave_dash_keeping_start_date_full():
    # 開始日をフルで1行目に残す(圧縮しない)ため、年またぎでも常に年が読める。
    first, second = _fit_axis_label("2026/08/02〜08/08")
    assert first == "2026/08/02"
    assert second == "〜08/08"


def test_channel_name_wraps_at_space():
    assert _fit_axis_label("Organic Search") == ("Organic", "Search")


def test_hyphenated_label_wraps_at_hyphen():
    assert _fit_axis_label("Cross-network") == ("Cross", "network")


def test_no_separator_and_long_label_stays_single_line_without_ellipsis():
    # 区切りが無い長いラベルは、折り返せないので1行のまま返す。
    # 以前のように[:12]で切って"…"にはしない(全文字を保持する)。
    first, second = _fit_axis_label("Unassigned")
    assert first == "Unassigned"
    assert second is None
    assert "…" not in first


def test_short_month_label_with_incomplete_marker_is_not_wrapped():
    # "2026-08※"はハイフンを含むが8文字以内のため折り返し対象にしない
    # (月次ラベルは短く、無闇に2行にしない)。
    assert _fit_axis_label("2026-08※") == ("2026-08※", None)


# ---------------------------------------------------------------------------
# style_charts(): 実際のグラフSVG出力での検証
# ---------------------------------------------------------------------------


def test_long_channel_labels_are_not_truncated_with_ellipsis():
    rows = [
        ("Organic Search", "200,462"),
        ("Direct", "71,246"),
        ("Organic Social", "58,915"),
        ("Referral", "7,364"),
        ("Email", "1,505"),
        ("Unassigned", "1,089"),
        ("AI Assistant", "191"),
        ("Organic Video", "77"),
        ("Paid Search", "21"),
        ("Paid Social", "4"),
        ("Display", "3"),
        ("Cross-network", "2"),
    ]
    html = style_charts(_chart_html("bar", "チャネル別セッション", "チャネル", "セッション", rows))
    assert "…" not in html
    # 折り返された長いラベルが両方とも欠けずに出力されていること
    assert "Organic</text>" in html and "Search</text>" in html
    assert "Unassigned</text>" in html  # 区切りが無いので1行のままだが全文字残る
    assert "Cross</text>" in html and "network</text>" in html


def test_weekly_chart_keeps_full_start_year_on_every_point_across_year_boundary():
    rows = [
        ("2025/12/22〜12/28", "100"),
        ("2025/12/29〜12/31", "110"),
        ("2026/01/01〜01/07", "120"),
    ]
    html = style_charts(_chart_html("line", "週次セッション推移", "週", "セッション", rows))
    assert "…" not in html
    # 年をまたぐ前後で、それぞれの開始日(年込み)がそのまま読める
    assert "2025/12/29</text>" in html
    assert "2026/01/01</text>" in html


def test_bar_chart_keeps_all_categories_beyond_thirteen_rows():
    rows = [(f"Channel_{index:02d}", str(1000 - index)) for index in range(1, 16)]

    html = style_charts(
        _chart_html("bar", "チャネル別セッション", "チャネル", "セッション", rows)
    )

    assert html.count("<rect ") == 15
    assert "Channel_14</text>" in html
    assert "Channel_15</text>" in html


def test_twelve_weekly_labels_widen_chart_to_avoid_overlap():
    rows = [
        ("2026/06/07〜06/13", "4,371"),
        ("2026/06/14〜06/20", "4,112"),
        ("2026/06/21〜06/27", "3,587"),
        ("2026/06/28〜07/04", "3,861"),
        ("2026/07/05〜07/11", "3,935"),
        ("2026/07/12〜07/18", "3,698"),
        ("2026/07/19〜07/25", "2,944"),
        ("2026/07/26〜08/01", "3,460"),
        ("2026/08/02〜08/08", "3,123"),
        ("2026/08/09〜08/15", "2,360"),
        ("2026/08/16〜08/22", "3,440"),
        ("2026/08/23〜08/29", "1,600"),
    ]
    html = style_charts(_chart_html("line", "週次セッション推移", "週", "セッション", rows))
    assert "…" not in html
    # 12本×日付レンジ表記は既定幅(760px)では重なるため、グラフ全体を広げている
    assert _viewbox_width(html) > 760


def test_thirteen_monthly_labels_stay_readable_without_ellipsis():
    rows = [(f"2025-{m:02d}※" if m in (8,) else f"2025-{m:02d}", str(1000 + m)) for m in range(8, 13)]
    rows += [(f"2026-{m:02d}", str(2000 + m)) for m in range(1, 9)]
    assert len(rows) == 13
    html = style_charts(_chart_html("line", "月次セッション推移", "月", "セッション", rows))
    assert "…" not in html
    assert "2025-08※</text>" in html
    assert "2026-08</text>" in html


def test_few_short_labels_keep_default_chart_width():
    rows = [("2026-08", "100"), ("2026-09", "120"), ("2026-10", "90")]
    html = style_charts(_chart_html("line", "月次セッション推移", "月", "セッション", rows))
    assert _viewbox_width(html) == 760


def test_combo_chart_overlays_cv_count_and_cvr_with_independent_axes():
    table = (
        '<div class="table-scroll"><table class="s-table">'
        '<thead><tr><th>月</th><th>セッション</th><th>CV数</th><th>CVR</th></tr></thead>'
        '<tbody><tr><td>2026-01</td><td>1,000</td><td>20</td><td>2.00%</td></tr>'
        '<tr><td>2026-02</td><td>800</td><td>24</td><td>3.00%</td></tr>'
        '<tr><td><strong>合計</strong></td><td>1,800</td><td>44</td><td>2.44%</td></tr></tbody>'
        '</table></div>'
    )
    html = style_charts(f"<!-- chart: combo; title: 月次 -->{table}")
    assert 'class="report-chart report-chart-combo"' in html
    assert html.count('class="report-chart report-chart-combo"') == 2
    assert html.count('<svg ') == 2
    assert ">セッション</text>" in html
    assert ">CV数</text>" in html
    assert ">CVR</text>" in html
    assert 'class="chart-legend chart-legend-rate">CVR</text>' in html
    assert "<rect " in html and "<polyline " in html
    assert html.count('class="chart-grid"') == 6


def test_combo_chart_supports_search_console_metrics():
    table = (
        '<div class="table-scroll"><table class="s-table">'
        '<thead><tr><th>月</th><th>クリック</th><th>表示回数</th><th>CTR</th></tr></thead>'
        '<tbody><tr><td>2026-01</td><td>100</td><td>1,000</td><td>10.0%</td></tr></tbody>'
        '</table></div>'
    )
    html = style_charts(f"<!-- chart: combo; title: 検索実績 -->{table}")
    assert ">クリック</text>" in html
    assert ">表示回数</text>" in html
    assert ">CTR</text>" in html


def test_combo_chart_keeps_two_cv_definitions_visible():
    table = (
        '<div class="table-scroll"><table class="s-table">'
        '<thead><tr><th>月</th><th>セッション</th><th>資料DL CV数</th><th>資料DL CVR</th>'
        '<th>相談 CV数</th><th>相談 CVR</th></tr></thead>'
        '<tbody><tr><td>2026-01</td><td>1,000</td><td>10</td><td>1.00%</td><td>20</td><td>2.00%</td></tr></tbody>'
        '</table></div>'
    )
    html = style_charts(f"<!-- chart: combo; title: 月次 -->{table}")
    assert ">資料DL CV数</text>" in html
    assert ">資料DL CVR</text>" in html
    assert ">相談 CV数</text>" in html
    assert ">相談 CVR</text>" in html
    # セッション1面＋2つのKPI面。各KPI面でCV数とCVRを重ねる。
    assert html.count('class="report-chart report-chart-combo"') == 3
    assert html.count('<svg ') == 3
    assert html.count('class="chart-grid"') == 9
    assert html.count("chart-legend-rate") == 2
    # 各面で年月・見出し・実数を読めること。
    assert html.count('>2026-01</text>') == 3
    assert html.count('>月</text>') == 3
    assert html.count('class="panel-title"') == 3
    assert html.count('class="bar-value"') == 3


def test_combo_chart_pairs_business_count_labels_with_matching_cvr():
    table = (
        '<div class="table-scroll"><table class="s-table">'
        '<thead><tr><th>月</th><th>セッション</th><th>問い合わせ数</th><th>問い合わせCVR</th>'
        '<th>資料DL数</th><th>資料DL CVR</th></tr></thead>'
        '<tbody><tr><td>2026-08</td><td>1,000</td><td>20</td><td>2.00%</td>'
        '<td>10</td><td>1.00%</td></tr></tbody></table></div>'
    )
    html = style_charts(f"<!-- chart: combo; title: 月次セッション・CV -->{table}")

    assert html.count('class="report-chart report-chart-combo"') == 3
    assert '>問い合わせ数</text>' in html
    assert 'class="chart-legend chart-legend-rate">問い合わせCVR</text>' in html
    assert '>資料DL数</text>' in html
    assert 'class="chart-legend chart-legend-rate">資料DL CVR</text>' in html
    assert html.count("chart-legend-rate") == 2
    assert ".chart-legend{font-size:9.5px}" in html
    assert ".panel-title{font-size:10.5px" in html


def test_combo_chart_keeps_all_three_cv_definitions_visible():
    table = (
        '<div class="table-scroll"><table class="s-table">'
        '<thead><tr><th>月</th><th>セッション</th>'
        '<th>相談数</th><th>相談CVR</th><th>資料DL数</th><th>資料DL CVR</th>'
        '<th>申込完了数</th><th>申込CVR</th></tr></thead>'
        '<tbody><tr><td>2026-08</td><td>1,000</td><td>20</td><td>2.00%</td>'
        '<td>10</td><td>1.00%</td><td>5</td><td>0.50%</td></tr></tbody></table></div>'
    )
    html = style_charts(f"<!-- chart: combo; title: 月次セッション・CV -->{table}")

    assert html.count('class="report-chart report-chart-combo"') == 4
    assert html.count("chart-legend-rate") == 3
    assert 'class="chart-legend chart-legend-rate">申込CVR</text>' in html
    assert 'class="panel-title">申込完了数</text>' in html


def test_table_bars_keep_values_and_skip_total_row():
    html = style_charts(_chart_html("table-bars", "比較", "項目", "セッション", [("A", "100"), ("合計", "100")]))
    assert 'class="table-bar-cell"' in html
    assert 'class="table-bar-value">100</span>' in html
    total_row = html.split("<td>合計</td>", 1)[1].split("</tr>", 1)[0]
    assert "table-bar-cell" not in total_row
