"""Full-month calendar evidence shared by index monthly planning and writing."""

from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar


def load_index_month_open_dates(
    session: Session, *, exchange: str, day: date
) -> tuple[date, ...]:
    start = day.replace(day=1)
    end = day.replace(day=monthrange(day.year, day.month)[1])
    rows = session.execute(
        select(TradeCalendar.trade_date, TradeCalendar.is_open)
        .where(
            TradeCalendar.exchange == exchange,
            TradeCalendar.trade_date >= start,
            TradeCalendar.trade_date <= end,
        )
        .order_by(TradeCalendar.trade_date)
    ).all()
    expected = [start + timedelta(days=i) for i in range(end.day)]
    # Missing closed days matter too: a truncated calendar cannot prove month end.
    if [row[0] for row in rows] != expected or any(row[1] is None for row in rows):
        return ()
    return tuple(day for day, is_open in rows if is_open)
