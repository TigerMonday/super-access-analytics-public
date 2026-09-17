from report_export.html_components import _chart_svg


def test_percent_axis_retains_unit_and_decimals():
    svg = _chart_svg('line', 'CTR', ['月', 'CTR'], [['2026-01', '0.50%'], ['2026-02', '1.00%']])
    for tick in ['1.00%', '0.75%', '0.50%', '0.25%', '0.00%']:
        assert f'>{tick}</text>' in svg


def test_count_axis_keeps_integer_ticks():
    svg = _chart_svg('line', 'クリック', ['月', 'クリック'], [['2026-01', '100'], ['2026-02', '200']])
    assert '>150</text>' in svg
    assert '%' not in svg
