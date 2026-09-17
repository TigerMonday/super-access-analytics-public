from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_ga4_traffic as traffic  # noqa: E402


def _row(dimensions, metrics):
    return SimpleNamespace(
        dimension_values=[SimpleNamespace(value=v) for v in dimensions],
        metric_values=[SimpleNamespace(value=str(v)) for v in metrics],
    )


def test_to_markdown_uses_only_selected_event_totals():
    sessions = SimpleNamespace(rows=[_row(["google", "organic", "(organic)"], [100])])
    selected = SimpleNamespace(rows=[
        _row(["google", "organic", "(organic)", "form_submit"], [3]),
        _row(["google", "organic", "(organic)", "download"], [2]),
    ])

    md = traffic.to_markdown(
        sessions, date(2026, 1, 1), date(2026, 1, 31),
        cv_response=selected, key_events=["form_submit", "download"],
    )

    assert "| 指定CV |" in md
    assert "| google | organic | (organic) | 100 | 5 |" in md


def test_to_markdown_labels_unfiltered_metric_as_all_key_events():
    response = SimpleNamespace(rows=[_row(["google", "organic", "(organic)"], [100, 12])])
    md = traffic.to_markdown(response, date(2026, 1, 1), date(2026, 1, 31))
    assert "キーイベント（全体）" in md
    assert "| google | organic | (organic) | 100 | 12 |" in md


def test_selected_cv_fetch_paginates_until_reported_row_count():
    pages = [
        SimpleNamespace(rows=[_row(["a", "m", "c1", "purchase"], [1]),
                              _row(["b", "m", "c2", "purchase"], [2])], row_count=3),
        SimpleNamespace(rows=[_row(["c", "m", "c3", "purchase"], [3])], row_count=3),
    ]

    class FakeClient:
        def __init__(self):
            self.offsets = []

        def run_report(self, request):
            self.offsets.append(request.offset)
            return pages.pop(0)

    client = FakeClient()
    response = traffic._fetch_selected_cv_response(
        client, "123456", date(2026, 1, 1), date(2026, 1, 31), ["purchase"], page_size=2,
    )

    assert client.offsets == [0, 2]
    assert len(response.rows) == 3
    assert response.row_count == 3


def test_selected_cv_fetch_continues_after_short_intermediate_page():
    pages = [
        SimpleNamespace(rows=[_row(["a", "m", "c1", "purchase"], [1])], row_count=3),
        SimpleNamespace(rows=[_row(["b", "m", "c2", "purchase"], [2]),
                              _row(["c", "m", "c3", "purchase"], [3])], row_count=3),
    ]

    class FakeClient:
        def __init__(self):
            self.offsets = []

        def run_report(self, request):
            self.offsets.append(request.offset)
            return pages.pop(0)

    client = FakeClient()
    response = traffic._fetch_selected_cv_response(
        client, "123456", date(2026, 1, 1), date(2026, 1, 31), ["purchase"], page_size=2,
    )

    assert client.offsets == [0, 1]
    assert len(response.rows) == 3


def test_selected_cv_fetch_fails_when_reported_rows_stop_midway():
    pages = [
        SimpleNamespace(rows=[_row(["a", "m", "c1", "purchase"], [1])], row_count=3),
        SimpleNamespace(rows=[], row_count=3),
    ]

    class FakeClient:
        def run_report(self, _request):
            return pages.pop(0)

    with pytest.raises(RuntimeError, match="未取得分を0件として扱わず"):
        traffic._fetch_selected_cv_response(
            FakeClient(), "123456", date(2026, 1, 1), date(2026, 1, 31),
            ["purchase"], page_size=2,
        )
