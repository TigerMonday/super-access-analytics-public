from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ab_test_power import estimate  # noqa: E402


def test_zero_baseline_routes_to_instrumentation():
    result = estimate(
        baseline_visitors=10000,
        baseline_conversions=0,
        daily_visitors=100,
        relative_uplift=0.20,
    )
    assert result["decision"] == "instrument_first"


def test_long_test_routes_to_single_release():
    result = estimate(
        baseline_visitors=10000,
        baseline_conversions=100,
        daily_visitors=10,
        relative_uplift=0.20,
        max_days=90,
    )
    assert result["decision"] == "single_release"
    assert result["expected_days"] > 90


def test_sufficient_volume_allows_ab_test():
    result = estimate(
        baseline_visitors=10000,
        baseline_conversions=500,
        daily_visitors=10000,
        relative_uplift=0.50,
        max_days=90,
    )
    assert result["decision"] == "ab_test"
    assert result["sample_per_variant"] > 0
