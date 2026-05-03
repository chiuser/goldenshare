from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


STK_MINS_PAGE_LIMIT = 8000
STK_MINS_ROWS_PER_TRADE_DAY: dict[int, int] = {
    1: 241,
    5: 49,
    15: 17,
    30: 9,
    60: 5,
}


@dataclass(frozen=True)
class StkMinsRequestWindow:
    start_date: date
    end_date: date
    trade_dates: tuple[date, ...]


def get_trade_days_per_window(freq: int) -> int:
    rows_per_trade_day = STK_MINS_ROWS_PER_TRADE_DAY.get(freq)
    if rows_per_trade_day is None:
        allowed = ", ".join(str(item) for item in sorted(STK_MINS_ROWS_PER_TRADE_DAY))
        raise ValueError(f"不支持的 freq={freq}，允许值：{allowed}")
    return max(1, STK_MINS_PAGE_LIMIT // rows_per_trade_day)


def estimate_target_request_count(*, symbol_count: int, trade_date_count: int, freqs: list[int]) -> int:
    total = 0
    for freq in freqs:
        trade_days_per_window = get_trade_days_per_window(freq)
        window_count = max(1, math.ceil(trade_date_count / trade_days_per_window))
        total += symbol_count * window_count
    return total


def build_target_request_windows(*, trade_dates: list[date], freq: int) -> list[StkMinsRequestWindow]:
    if not trade_dates:
        return []
    sorted_dates = sorted(set(trade_dates))
    trade_days_per_window = get_trade_days_per_window(freq)
    windows: list[StkMinsRequestWindow] = []
    for index in range(0, len(sorted_dates), trade_days_per_window):
        current = sorted_dates[index : index + trade_days_per_window]
        windows.append(
            StkMinsRequestWindow(
                start_date=current[0],
                end_date=current[-1],
                trade_dates=tuple(current),
            )
        )
    return windows


def build_current_month_windows(*, trade_dates: list[date], max_window_days: int) -> list[StkMinsRequestWindow]:
    if not trade_dates:
        return []
    sorted_dates = sorted(set(trade_dates))
    windows: list[StkMinsRequestWindow] = []
    current: list[date] = []
    for trade_date in sorted_dates:
        if not current:
            current = [trade_date]
            continue
        first = current[0]
        crosses_month = trade_date.year != first.year or trade_date.month != first.month
        exceeds_days = (trade_date - first).days + 1 > max_window_days
        if crosses_month or exceeds_days:
            windows.append(
                StkMinsRequestWindow(
                    start_date=current[0],
                    end_date=current[-1],
                    trade_dates=tuple(current),
                )
            )
            current = [trade_date]
        else:
            current.append(trade_date)
    if current:
        windows.append(
            StkMinsRequestWindow(
                start_date=current[0],
                end_date=current[-1],
                trade_dates=tuple(current),
            )
        )
    return windows
