#!/usr/bin/env python3
"""2群比率テストの必要サンプルと想定期間を事前判定する。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from statistics import NormalDist


def estimate(
    *,
    baseline_visitors: int,
    baseline_conversions: int,
    daily_visitors: float,
    relative_uplift: float,
    max_days: int = 90,
    alpha: float = 0.05,
    power: float = 0.80,
    min_baseline_conversions: int = 5,
) -> dict[str, float | int | str]:
    if baseline_visitors <= 0:
        raise ValueError("baseline_visitors は1以上にしてください")
    if baseline_conversions < 0 or baseline_conversions > baseline_visitors:
        raise ValueError("baseline_conversions は0以上かつ訪問数以下にしてください")
    if daily_visitors <= 0:
        raise ValueError("daily_visitors は0より大きくしてください")
    if relative_uplift <= 0:
        raise ValueError("relative_uplift は0より大きくしてください")
    if max_days <= 0:
        raise ValueError("max_days は1以上にしてください")

    baseline_rate = baseline_conversions / baseline_visitors
    base = {
        "baseline_rate": baseline_rate,
        "baseline_conversions": baseline_conversions,
        "max_days": max_days,
    }
    if baseline_conversions < min_baseline_conversions or baseline_rate == 0:
        return {
            **base,
            "decision": "instrument_first",
            "reason": "ベースラインCVが少なく、安定した必要サンプルを計算できません",
        }

    target_rate = baseline_rate * (1 + relative_uplift)
    if target_rate >= 1:
        raise ValueError("想定改善後の率が100%以上になります")

    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(power)
    pooled = (baseline_rate + target_rate) / 2
    delta = target_rate - baseline_rate
    numerator = (
        z_alpha * math.sqrt(2 * pooled * (1 - pooled))
        + z_power
        * math.sqrt(
            baseline_rate * (1 - baseline_rate)
            + target_rate * (1 - target_rate)
        )
    ) ** 2
    per_variant = math.ceil(numerator / (delta**2))
    total = per_variant * 2
    expected_days = math.ceil(total / daily_visitors)
    decision = "ab_test" if expected_days <= max_days else "single_release"
    reason = (
        "許容期間内に必要サンプルを集められます"
        if decision == "ab_test"
        else "必要サンプルの収集が許容期間を超えます"
    )
    return {
        **base,
        "target_rate": target_rate,
        "relative_uplift": relative_uplift,
        "sample_per_variant": per_variant,
        "total_sample": total,
        "expected_days": expected_days,
        "decision": decision,
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-visitors", type=int, required=True)
    parser.add_argument("--baseline-conversions", type=int, required=True)
    parser.add_argument("--daily-visitors", type=float, required=True)
    parser.add_argument("--relative-uplift", type=float, default=0.20)
    parser.add_argument("--max-days", type=int, default=90)
    args = parser.parse_args()
    try:
        result = estimate(
            baseline_visitors=args.baseline_visitors,
            baseline_conversions=args.baseline_conversions,
            daily_visitors=args.daily_visitors,
            relative_uplift=args.relative_uplift,
            max_days=args.max_days,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
