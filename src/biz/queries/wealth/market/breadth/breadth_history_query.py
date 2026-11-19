from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.clients.reference_data import local_reference_data
from src.foundation.models.core.trade_calendar import TradeCalendar


class BreadthHistoryQuery:
    """Load fixed trading-day windows for breadth facts."""

    def load_recent_trade_dates(
        self,
        session: Session,
        *,
        end_trade_date: date,
        limit_days: int = 62,
    ) -> list[date]:
        reference = local_reference_data(session)
        if reference is not None:
            return [row.trade_date for row in reference.calendar.recent_open_rows(
                exchange="SSE", bound=end_trade_date, limit=limit_days,
            )]
        rows = session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit_days)
        ).scalars().all()
        return list(reversed(rows))
