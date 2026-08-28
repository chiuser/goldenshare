from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final, Mapping


ETF_MINS_RANGE_WINDOW_MONTHS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "1min": 2,
        "5min": 12,
        "15min": 36,
        "30min": 72,
        "60min": 120,
    }
)


def build_etf_minute_windows(
    *,
    freq: str,
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, date], ...]:
    months = ETF_MINS_RANGE_WINDOW_MONTHS.get(freq)
    if months is None:
        raise ValueError(f"ETF 历史分钟行情频率无效：{freq}")
    if start_date > end_date:
        raise ValueError("ETF 历史分钟行情开始日期不得晚于结束日期")

    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        last_month_index = cursor.year * 12 + (cursor.month - 1) + (months - 1)
        last_year, last_month_zero_based = divmod(last_month_index, 12)
        last_month = last_month_zero_based + 1
        natural_window_end = date(
            last_year,
            last_month,
            monthrange(last_year, last_month)[1],
        )
        window_end = min(natural_window_end, end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)
