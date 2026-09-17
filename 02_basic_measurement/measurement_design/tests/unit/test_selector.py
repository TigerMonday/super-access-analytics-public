"""selector.py のユニットテスト."""
import pytest


KPI_BREAKDOWNS_BASIC = [
    {
        "kpi_id": "kpi_001",
        "required_events": [
            {"event_name": "file_download", "params": []}
        ],
        "mcv_candidates": [],
    }
]

KPI_BREAKDOWNS_EC = [
    {
        "kpi_id": "kpi_ec",
        "required_events": [
            {"event_name": "purchase", "params": []},
            {"event_name": "view_item", "params": []},
        ],
        "mcv_candidates": [],
    }
]

REVIEW_DATA_BASIC = {
    "ga4": {
        "events_observed": [],
        "custom_definitions": {"dimensions": [], "metrics": []},
    }
}

REVIEW_DATA_WITH_DIMS = {
    "ga4": {
        "events_observed": [],
        "custom_definitions": {
            "dimensions": [{"parameter_name": "user_type", "scope": "USER"}],
            "metrics": [],
        },
    }
}


def test_select_chapters_always_includes_01_02_03():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_BASIC)
    assert 1 in chapters
    assert 2 in chapters
    assert 3 in chapters


def test_select_chapters_includes_04_when_kpis_exist():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_BASIC)
    assert 4 in chapters


def test_select_chapters_includes_06_when_custom_events():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_BASIC)
    assert 6 in chapters


def test_select_chapters_includes_08_for_ec_events():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_EC, REVIEW_DATA_BASIC)
    assert 8 in chapters


def test_select_chapters_excludes_08_without_ec():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_BASIC)
    assert 8 not in chapters


def test_select_chapters_includes_07_with_custom_dims():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_WITH_DIMS)
    assert 7 in chapters


def test_select_chapters_returns_sorted_list():
    from measurement_design.design.selector import select_chapters
    chapters = select_chapters(KPI_BREAKDOWNS_BASIC, REVIEW_DATA_BASIC)
    assert chapters == sorted(chapters)
