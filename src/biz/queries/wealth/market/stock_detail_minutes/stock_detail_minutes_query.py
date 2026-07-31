from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StockMinuteQueryWindow:
    start_date: date | None
    query_end_date: date
    expected_end_date: date | None


def resolve_stock_minute_query_window(*, start_date: date | None, end_date: date | None, today: date) -> StockMinuteQueryWindow:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("startDate 不能晚于 endDate。")
    return StockMinuteQueryWindow(
        start_date=start_date,
        query_end_date=end_date or today,
        expected_end_date=end_date,
    )
