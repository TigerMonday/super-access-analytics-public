"""loader.py のユニットテスト."""
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_load_kpis_returns_list():
    from measurement_design.loader import load_kpis
    result = load_kpis(FIXTURES)
    assert isinstance(result, list)
    assert len(result) >= 1


def test_load_kpis_has_required_fields():
    from measurement_design.loader import load_kpis
    kpis = load_kpis(FIXTURES)
    for kpi in kpis:
        assert "kpi_id" in kpi
        assert "name" in kpi
        assert "description" in kpi


def test_load_kpis_missing_file_raises():
    from measurement_design.loader import load_kpis
    with pytest.raises(FileNotFoundError):
        load_kpis(Path("/nonexistent"))


def test_load_screen_flow_returns_dict():
    from measurement_design.loader import load_screen_flow
    result = load_screen_flow(FIXTURES)
    assert "pages" in result
    assert "flows" in result


def test_load_screen_flow_pages_have_page_id():
    from measurement_design.loader import load_screen_flow
    result = load_screen_flow(FIXTURES)
    for page in result["pages"]:
        assert "page_id" in page


def test_load_ga4_local_returns_dict():
    from measurement_design.loader import load_ga4_local
    result = load_ga4_local(FIXTURES)
    assert "property_id" in result


def test_load_ga4_local_missing_returns_empty():
    from measurement_design.loader import load_ga4_local
    result = load_ga4_local(Path("/nonexistent"))
    assert result == {}


def test_load_gtm_local_returns_none_when_missing():
    from measurement_design.loader import load_gtm_local
    result = load_gtm_local(Path("/nonexistent"))
    assert result is None


def test_load_gtm_local_returns_dict_when_present():
    from measurement_design.loader import load_gtm_local
    result = load_gtm_local(FIXTURES)
    assert result is not None
    assert "gtm_account_id" in result
