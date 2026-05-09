from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@dataclass(frozen=True, slots=True)
class BreadthHistoryPoint:
    trade_date: date
    up_count: int
    down_count: int


class BreadthHistoryQuery:
    """Load breadth history points for fixed trading-day windows."""

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

    def load_history_points(
        self,
        session: Session,
        *,
        trade_dates: list[date],
    ) -> list[BreadthHistoryPoint]:
        if not trade_dates:
            return []

        up_expr = func.sum(case((EquityDailyBar.pct_chg > 0, 1), else_=0))
        down_expr = func.sum(case((EquityDailyBar.pct_chg < 0, 1), else_=0))

        rows = session.execute(
            select(
                EquityDailyBar.trade_date,
                up_expr.label("up_count"),
                down_expr.label("down_count"),
            )
            .where(
                EquityDailyBar.trade_date.in_(tuple(trade_dates)),
                EquityDailyBar.pct_chg.is_not(None),
            )
            .group_by(EquityDailyBar.trade_date)
            .order_by(EquityDailyBar.trade_date.asc())
        ).all()

        return [
            BreadthHistoryPoint(
                trade_date=row.trade_date,
                up_count=int(row.up_count or 0),
                down_count=int(row.down_count or 0),
            )
            for row in rows
        ]
