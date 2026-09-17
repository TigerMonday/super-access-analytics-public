from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_ga4 as ga  # noqa: E402


def _row(*metric_values: str):
    return SimpleNamespace(
        dimension_values=[],
        metric_values=[SimpleNamespace(value=value) for value in metric_values],
    )


class _FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def run_report(self, request):
        self.requests.append(request)
        offset = int(getattr(request, "offset", 0) or 0)
        return self.pages[offset]


def _install_client(monkeypatch, client):
    monkeypatch.setattr(ga, "validate_configured_roots", lambda: None)
    monkeypatch.setattr(ga, "get_credentials", lambda: object())
    monkeypatch.setattr(ga, "BetaAnalyticsDataClient", lambda credentials: client)
    monkeypatch.setattr(ga, "validate_query", lambda *args, **kwargs: None)


def test_removed_engagement_metric_is_rejected_before_api_call():
    with pytest.raises(ValueError, match="取得しない指標"):
        ga.fetch("1", [], ["engagementRate"], "2026-01-01", "2026-01-31")


def test_legacy_conversion_alias_uses_key_events_at_api_boundary(monkeypatch):
    response = SimpleNamespace(rows=[_row("3")], row_count=1, metadata=None, property_quota=None)
    client = _FakeClient({0: response})
    _install_client(monkeypatch, client)

    result = ga.fetch("1", [], ["conversions"], "2026-01-01", "2026-01-31")

    assert result is response
    assert client.requests[0].metrics[0].name == "keyEvents"


def test_all_rows_pages_until_reported_row_count(monkeypatch):
    first = SimpleNamespace(
        rows=[_row("1"), _row("2")],
        row_count=3,
        metadata=SimpleNamespace(subject_to_thresholding=True, data_loss_from_other_row=False),
        property_quota=SimpleNamespace(),
    )
    second = SimpleNamespace(rows=[_row("3")], row_count=3, metadata=None, property_quota=None)
    client = _FakeClient({0: first, 2: second})
    _install_client(monkeypatch, client)

    result = ga.fetch("1", [], ["sessions"], "2026-01-01", "2026-01-31", fetch_all=True)

    assert len(result.rows) == 3
    assert result.row_count == 3
    assert [int(request.offset or 0) for request in client.requests] == [0, 2]
    assert result.metadata.subject_to_thresholding is True


def test_markdown_surfaces_truncation_and_data_quality_warnings():
    response = SimpleNamespace(
        rows=[_row("2")],
        row_count=5,
        metadata=SimpleNamespace(subject_to_thresholding=True, data_loss_from_other_row=True),
    )

    text = ga.to_markdown(response, [], ["sessions"], "2026-01-01", "2026-01-31")

    assert "4行は未取得" in text
    assert "しきい値適用" in text
    assert "(other)行" in text


def test_markdown_does_not_sum_rate_or_average_metrics():
    response = SimpleNamespace(rows=[_row("0.5", "12.3")], row_count=1, metadata=None)

    text = ga.to_markdown(
        response,
        [],
        ["bounceRate", "averageSessionDuration"],
        "2026-01-01",
        "2026-01-31",
    )

    assert "合計:" not in text


def test_markdown_surfaces_low_quota():
    response = SimpleNamespace(
        rows=[_row("2")],
        row_count=1,
        metadata=None,
        property_quota=SimpleNamespace(
            tokens_per_hour=SimpleNamespace(remaining=7),
            tokens_per_project_per_hour=SimpleNamespace(remaining=100),
            concurrent_requests=SimpleNamespace(remaining=100),
        ),
    )

    text = ga.to_markdown(response, [], ["sessions"], "2026-01-01", "2026-01-31")

    assert "1時間あたりトークン残量が7" in text
