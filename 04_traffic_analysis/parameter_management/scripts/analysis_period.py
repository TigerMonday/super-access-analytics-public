"""基本分析で共通利用する取得期間の決定ロジック。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class AnalysisPeriod:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _shift_year(value: date, years: int) -> date:
    """同じ月日を保って年をずらす。2月29日は移動先の2月末へ寄せる。"""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _month_start_months_before(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    return date(month_index // 12, month_index % 12 + 1, 1)


def resolve_analysis_periods(
    *,
    today: date,
    days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[AnalysisPeriod, AnalysisPeriod]:
    """当期と比較期間を返す。

    無指定時は、進行中の月を除いた直近12か月の月初〜月末を当期とする。
    明示日付では前年の同じ暦日範囲、互換用の ``days`` 指定では従来どおり
    昨日までのN日と、その直前の同日数を返す。
    """
    if bool(start_date) != bool(end_date):
        raise ValueError("--start-date と --end-date は両方指定してください")

    if start_date and end_date:
        if start_date > end_date:
            raise ValueError("--start-date は --end-date 以前の日付にしてください")
        current = AnalysisPeriod(start_date, end_date)
        previous = AnalysisPeriod(_shift_year(start_date, -1), _shift_year(end_date, -1))
        return current, previous

    if days is not None:
        if days < 1:
            raise ValueError("--days は1以上を指定してください")
        end = today - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)
        return AnalysisPeriod(start, end), AnalysisPeriod(previous_start, previous_end)

    # 標準期間: 直近の完了月を終点にした12暦月。
    current_month_start = date(today.year, today.month, 1)
    end = current_month_start - timedelta(days=1)
    start = _month_start_months_before(date(end.year, end.month, 1), 11)
    current = AnalysisPeriod(start, end)
    previous = AnalysisPeriod(_shift_year(start, -1), _shift_year(end, -1))
    return current, previous
