from __future__ import annotations

from collections.abc import Sequence
from datetime import date


def validate_trade_dates(trade_dates: Sequence[date]) -> tuple[date, ...]:
    normalized = tuple(trade_dates)
    if not normalized:
        raise ValueError("trade_dates must not be empty")
    if any(left >= right for left, right in zip(normalized, normalized[1:])):
        raise ValueError("trade_dates must be strictly increasing and unique")
    return normalized


def trailing_window_before(
    trade_dates: Sequence[date],
    current_index: int,
    window: int,
) -> tuple[date, ...]:
    if window <= 0:
        raise ValueError("window must be positive")
    if current_index < 0 or current_index >= len(trade_dates):
        raise IndexError("current_index is outside trade_dates")
    start = current_index - window
    if start < 0:
        return ()
    return tuple(trade_dates[start:current_index])


def as_of_prefix(trade_dates: Sequence[date], as_of: date) -> tuple[date, ...]:
    normalized = validate_trade_dates(trade_dates)
    if as_of not in normalized:
        raise ValueError("as_of must be a registered trade date")
    return normalized[: normalized.index(as_of) + 1]
