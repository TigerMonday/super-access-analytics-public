from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analysis_period import resolve_analysis_periods  # noqa: E402


def test_default_period_is_latest_twelve_completed_calendar_months():
    current, previous = resolve_analysis_periods(today=date(2026, 9, 17))

    assert (current.start, current.end) == (date(2025, 9, 1), date(2026, 8, 31))
    assert (previous.start, previous.end) == (date(2024, 9, 1), date(2025, 8, 31))


def test_explicit_dates_take_priority_and_compare_with_previous_year():
    current, previous = resolve_analysis_periods(
        today=date(2026, 9, 17), days=90,
        start_date=date(2025, 10, 1), end_date=date(2026, 3, 31),
    )

    assert (current.start, current.end) == (date(2025, 10, 1), date(2026, 3, 31))
    assert (previous.start, previous.end) == (date(2024, 10, 1), date(2025, 3, 31))


def test_legacy_days_still_uses_rolling_complete_days():
    current, previous = resolve_analysis_periods(today=date(2026, 9, 17), days=90)

    assert (current.start, current.end) == (date(2026, 6, 19), date(2026, 9, 16))
    assert current.days == previous.days == 90
    assert previous.end < current.start


@pytest.mark.parametrize(
    "start_date,end_date",
    [(date(2026, 1, 1), None), (None, date(2026, 1, 31))],
)
def test_explicit_period_requires_both_dates(start_date, end_date):
    with pytest.raises(ValueError, match="両方指定"):
        resolve_analysis_periods(
            today=date(2026, 9, 17), start_date=start_date, end_date=end_date,
        )
