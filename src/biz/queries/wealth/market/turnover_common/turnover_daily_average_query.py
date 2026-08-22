from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


_AVERAGE_WINDOW_DAYS = 20


@dataclass(frozen=True, slots=True)
class TurnoverDailyAverageSnapshot:
    end_trade_date: date
    avg5d_amount: Decimal | None
    avg20d_amount: Decimal | None
    available5d_count: int
    available20d_count: int


class TurnoverDailyAverageQuery:
    """Load the shared 5/20-day turnover averages with two bounded queries."""

    def load(
        self,
        session: Session,
        *,
        end_trade_date: date,
    ) -> TurnoverDailyAverageSnapshot:
        descending_dates = session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(_AVERAGE_WINDOW_DAYS)
        ).scalars().all()
        trade_dates = tuple(reversed(descending_dates))

        amounts_by_date: dict[date, Decimal] = {}
        if trade_dates:
            rows = session.execute(
                select(
                    EquityDailyBar.trade_date,
                    func.sum(EquityDailyBar.amount).label("amount"),
                )
                .where(EquityDailyBar.trade_date.in_(trade_dates))
                .group_by(EquityDailyBar.trade_date)
            ).all()
            amounts_by_date = {
                row.trade_date: Decimal(str(row.amount))
                for row in rows
                if row.amount is not None
            }

        recent_5_dates = trade_dates[-5:]
        avg5d, available5d_count = self._average_existing(
            amounts_by_date=amounts_by_date,
            trade_dates=recent_5_dates,
        )
        avg20d, available20d_count = self._average_existing(
            amounts_by_date=amounts_by_date,
            trade_dates=trade_dates,
        )
        return TurnoverDailyAverageSnapshot(
            end_trade_date=end_trade_date,
            avg5d_amount=avg5d,
            avg20d_amount=avg20d,
            available5d_count=available5d_count,
            available20d_count=available20d_count,
        )

    @staticmethod
    def _average_existing(
        *,
        amounts_by_date: dict[date, Decimal],
        trade_dates: tuple[date, ...],
    ) -> tuple[Decimal | None, int]:
        values = tuple(amounts_by_date[trade_day] for trade_day in trade_dates if trade_day in amounts_by_date)
        if not values:
            return None, 0
        return sum(values, Decimal("0")) / Decimal(len(values)), len(values)
