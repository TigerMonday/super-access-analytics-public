from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_search_console as sc  # noqa: E402


def test_aggregate_monthly_uses_weighted_position():
    rows = [
        {"keys": ["2026-01-01"], "clicks": 10, "impressions": 100, "ctr": .1, "position": 2},
        {"keys": ["2026-01-02"], "clicks": 10, "impressions": 300, "ctr": .033, "position": 6},
    ]
    monthly = sc.aggregate_monthly(rows)
    assert monthly[0]["month"] == "2026-01"
    assert monthly[0]["clicks"] == 20
    assert monthly[0]["impressions"] == 400
    assert monthly[0]["ctr"] == .05
    assert monthly[0]["position"] == 5


def test_resolve_period_uses_explicit_report_dates():
    period = sc.resolve_period(
        today=date(2026, 9, 12), days=365,
        start_date=date(2025, 9, 11), end_date=date(2026, 9, 10),
    )
    assert period == sc.Period(date(2025, 9, 11), date(2026, 9, 10))


def test_resolve_period_requires_both_explicit_dates():
    with pytest.raises(ValueError, match="両方指定"):
        sc.resolve_period(
            today=date(2026, 9, 12), days=365,
            start_date=date(2025, 9, 11), end_date=None,
        )


def test_markdown_contains_current_previous_totals_and_search_dimensions():
    period = sc.Period(date(2026, 1, 1), date(2026, 1, 1))
    previous = sc.Period(date(2025, 12, 1), date(2025, 12, 1))
    current_row = {"keys": ["2026-01-01"], "clicks": 20, "impressions": 200, "ctr": .1, "position": 3}
    previous_row = {"keys": ["2025-12-01"], "clicks": 10, "impressions": 100, "ctr": .1, "position": 4}
    query = {"keys": ["example query"], "clicks": 20, "impressions": 200, "ctr": .1, "position": 3}
    page = {"keys": ["https://example.invalid/page"], "clicks": 20, "impressions": 200, "ctr": .1, "position": 3}
    md = sc.to_markdown(
        "sc-domain:example.invalid", period, previous,
        [current_row], [previous_row], [query], [], [page], [], [],
    )
    assert "| クリック | 20 | 10 | +100.0% |" in md
    assert "## 2. 検索クエリ" in md
    assert "## 3. 検索流入ページ" in md
    assert "<!-- chart: search" in md
    assert "| 月 | 表示回数 | クリック | CTR | 平均掲載順位 |" in md
    assert "| 2026-01 | 200 | 20 | 10.00% | 3.0 |" in md
    assert "**合計**" in md


def daily_rows(period, clicks=10):
    return [
        {"keys": [(period.start + timedelta(days=i)).isoformat()],
         "clicks": clicks, "impressions": 100, "ctr": clicks / 100, "position": 4}
        for i in range(period.days)
    ]


def render(period, previous, current_rows, previous_rows):
    query = {"keys": ["sample query"], "clicks": 20, "impressions": 100, "ctr": .2, "position": 3}
    old_query = {**query, "clicks": 10}
    return sc.to_markdown(
        "sc-domain:example.invalid", period, previous, current_rows, previous_rows,
        [query], [old_query], [query], [old_query], [],
    )


@pytest.mark.parametrize("days", [0, -1])
def test_default_period_rejects_nonpositive_days(days):
    with pytest.raises(ValueError, match="1以上"):
        sc.resolve_period(today=date(2026, 1, 1), days=days, start_date=None, end_date=None)


def test_preceding_period_uses_actual_explicit_period_length():
    current = sc.resolve_period(
        today=date(2026, 5, 1), days=365,
        start_date=date(2026, 4, 1), end_date=date(2026, 4, 30),
    )
    assert sc.preceding_period(current) == sc.Period(date(2026, 3, 2), date(2026, 3, 31))


def test_coverage_detects_internal_missing_day_not_just_endpoints():
    period = sc.Period(date(2026, 1, 1), date(2026, 1, 3))
    rows = daily_rows(period)
    coverage = sc.date_coverage(period, [rows[0], rows[-1]])
    assert coverage["missing_dates"] == ["2026-01-02"]
    assert coverage["observed_days"] == 2
    assert not coverage["complete"]


@pytest.mark.parametrize("bad_row", [
    {"keys": []}, {"keys": ["not-a-date"]}, {"keys": ["2025-12-31"]},
    {"keys": ["2026-01-01"]},
])
def test_coverage_rejects_invalid_outside_or_duplicate_rows(bad_row):
    period = sc.Period(date(2026, 1, 1), date(2026, 1, 1))
    coverage = sc.date_coverage(period, daily_rows(period) + [bad_row])
    assert coverage["invalid_rows"] == 1
    assert not coverage["complete"]


@pytest.mark.parametrize("missing_from", ["current", "previous", "all"])
def test_incomplete_dates_block_all_period_deltas(missing_from):
    current = sc.Period(date(2026, 1, 1), date(2026, 1, 3))
    previous = sc.preceding_period(current)
    rows, old_rows = daily_rows(current, 20), daily_rows(previous, 10)
    if missing_from == "current":
        rows = rows[1:]
    elif missing_from == "previous":
        old_rows = old_rows[1:]
    else:
        rows, old_rows = [], []
    md = render(current, previous, rows, old_rows)
    assert "期間比較: 不可" in md
    assert "| sample query | 20 | — | 比較不可 |" in md
    assert "+100.0%" not in md
    summary = md.split("## 0. 検索実績サマリー")[1].split("## 1.")[0]
    assert summary.count("比較不可") == 4


@pytest.mark.parametrize("previous", [
    sc.Period(date(2025, 12, 31), date(2025, 12, 31)),
    sc.Period(date(2026, 1, 1), date(2026, 1, 2)),
])
def test_different_length_or_overlapping_periods_are_not_compared(previous):
    current = sc.Period(date(2026, 1, 1), date(2026, 1, 2))
    assert "期間比較: 不可" in render(current, previous, daily_rows(current), daily_rows(previous))


def test_absent_previous_top_row_is_unknown_not_zero_or_new():
    row = {"keys": ["sample"], "clicks": 20, "impressions": 100, "ctr": .2, "position": 3}
    lines = sc._period_comparison_table([row], [], "検索クエリ")
    assert "| sample | 20 | — | 比較不可 | 100 | — |" in lines[2]
    assert "**比較不可**" in lines[-1]
    assert "新規" not in "\n".join(lines)


def test_complete_periods_allow_summary_and_matching_row_comparison():
    current = sc.Period(date(2026, 1, 1), date(2026, 1, 3))
    previous = sc.preceding_period(current)
    md = render(current, previous, daily_rows(current, 20), daily_rows(previous, 10))
    assert "期間比較: 可能" in md
    assert "| クリック | 60 | 30 | +100.0% |" in md
    assert "| sample query | 20 | 10 | +100.0% |" in md


def test_main_saves_raw_rows_and_coverage_without_network(monkeypatch, tmp_path):
    output = tmp_path / "search.md"
    monkeypatch.setattr(sys, "argv", [
        "fetch_search_console", "--site-url", "sc-domain:example.invalid",
        "--start-date", "2026-01-01", "--end-date", "2026-01-03",
        "--output", str(output),
    ])
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(inject_into_ssl=lambda: None))
    discovery = SimpleNamespace(build=lambda *args, **kwargs: object())
    monkeypatch.setitem(sys.modules, "googleapiclient", SimpleNamespace(discovery=discovery))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
    monkeypatch.setattr(sc, "get_search_console_credentials", lambda: object())
    monkeypatch.setattr(sc, "query_rows", lambda service, url, period, dimensions, limit:
                        daily_rows(period) if dimensions == ["date"] else [])

    sc.main()

    snapshot = json.loads((tmp_path / "search.md.json").read_text(encoding="utf-8"))
    assert snapshot["current_coverage"]["complete"]
    assert snapshot["previous_coverage"]["requested_start"] == "2025-12-29"
    assert len(snapshot["daily_previous"]) == 3
    assert snapshot["data_state"] == "final"
    assert "期間比較: 可能" in output.read_text(encoding="utf-8")


def test_matching_site_entries_prefers_exact_prefix_then_domain():
    entries = [
        {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"},
        {"siteUrl": "https://www.example.com/", "permissionLevel": "siteOwner"},
        {"siteUrl": "https://other.example/", "permissionLevel": "siteOwner"},
    ]

    matches = sc.matching_site_entries("https://www.example.com/", entries)

    assert [entry["siteUrl"] for entry in matches] == [
        "https://www.example.com/",
        "sc-domain:example.com",
    ]


def test_matching_site_entries_does_not_guess_unlisted_property():
    entries = [{"siteUrl": "https://blog.example.com/", "permissionLevel": "siteOwner"}]

    assert sc.matching_site_entries("https://www.example.com/", entries) == []
