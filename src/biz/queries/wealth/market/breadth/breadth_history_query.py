from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

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
