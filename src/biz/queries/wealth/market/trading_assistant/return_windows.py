"""Civil period identities, not exchange-calendar or publication evidence."""
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from src.biz.services.wealth.market.trading_assistant.calculation.periods import calendar_window


@dataclass(frozen=True, slots=True)
class ReturnWindow:
    start: date
    end: date
    target_end: date
    is_ended: bool

    def effective_range(self, history_start: date) -> tuple[date, date] | None:
        """Each account/stock supplies its actual openedOn-based history start."""
        if type(history_start) is not date:
            raise ValueError("Invalid return history start")
        start = max(self.start, history_start)
        return (start, self.target_end) if start <= self.target_end else None


def curve_windows(start: date, end: date, *, granularity: str, today: date) -> Iterator[ReturnWindow]:
    """Expand intersecting weeks/months; never change the requested review range.

    Identity is independent of publication gaps. The caller must resolve the
    actual trading cutoff and coverage inside these bounds, not treat today as
    proof of an available close. Future periods have no fabricated points.
    """
    if any(type(day) is not date for day in (start, end, today)) or start > end:
        raise ValueError("Invalid curve date range")
    if granularity not in ("DAY", "WEEK", "MONTH"):
        raise ValueError("Invalid curve granularity")
    last = min(end, today)
    if start > last:
        return
    cursor = start
    while cursor <= last:
        first, final = calendar_window(cursor, granularity)
        yield ReturnWindow(first, final, min(final, today), final < today)
        if final >= last:
            return
        cursor = final + timedelta(days=1)


def calendar_dates(month_start: date) -> tuple[date, ...]:
    """Complete five-column grid, including adjacent-month weekdays (§4.30)."""
    if type(month_start) is not date or month_start.day != 1:
        raise ValueError("Calendar requires the selected month's first date")
    _, month_end = calendar_window(month_start, "MONTH")
    first_ordinal = month_start.toordinal() - month_start.weekday()
    last_ordinal = min(date.max.toordinal(), month_end.toordinal() + 6 - month_end.weekday())
    return tuple(day for ordinal in range(first_ordinal, last_ordinal + 1)
                 if (day := date.fromordinal(ordinal)).weekday() < 5)
