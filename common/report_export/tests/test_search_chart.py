from report_export.html_components import _chart_svg


def test_search_two_panels_four_series():
    svg = _chart_svg('search', '検索', ['月', 'imp', 'click', 'CTR', '順位'],
                     [['2026-01', '1000', '10', '1.00%', '1'], ['2026-02', '2000', '20', '1.00%', '10']])
    assert svg.count('<polyline') == 4
    assert svg.count('class="report-chart report-chart-search"') == 2
    assert svg.count('<svg ') == 2
    assert svg.count('>月</text>') == 2
    assert '1.00%' in svg
    assert '上ほど良い' in svg
    assert 'cy="82.0"' in svg  # rank 1: top of the ranking panel
    assert 'cy="252.0"' in svg  # rank 10: bottom


def test_missing_values_do_not_become_zero():
    svg = _chart_svg('search', '検索', ['月', 'imp', 'click', 'CTR', '順位'],
                     [['2026-01', '100', '10', '10%', '2'], ['2026-02', '—', '—', '—', '—']])
    assert svg.count('<circle') == 4
