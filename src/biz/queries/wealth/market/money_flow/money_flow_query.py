from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core.trade_calendar import TradeCalendar


@dataclass(frozen=True, slots=True)
class OrderSizeFlowSnapshot:
    elg_amount: float | None
    elg_rate: float | None
    lg_amount: float | None
    lg_rate: float | None
    md_amount: float | None
    md_rate: float | None
    sm_amount: float | None
    sm_rate: float | None

    @property
    def is_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.elg_amount,
                self.elg_rate,
                self.lg_amount,
                self.lg_rate,
                self.md_amount,
                self.md_rate,
                self.sm_amount,
                self.sm_rate,
            )
        )


@dataclass(frozen=True, slots=True)
class MoneyFlowMetricsSnapshot:
    today_net_amount: float | None
    prev_net_amount: float | None
    by_order_size: OrderSizeFlowSnapshot

    @property
    def has_core_metrics(self) -> bool:
        return self.today_net_amount is not None or self.prev_net_amount is not None


@dataclass(frozen=True, slots=True)
class MoneyFlowHistoryPoint:
    trade_date: date
    net_amount: float | None


class MoneyFlowQuery:
    """Load money-flow metrics and history points."""

    def load_recent_trade_dates(
        self,
        session: Session,
        *,
        end_trade_date: date,
        limit_days: int,
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

    def load_metrics(
        self,
        session: Session,
        *,
        trade_date: date,
        prev_trade_date: date | None,
    ) -> MoneyFlowMetricsSnapshot:
        current_row = session.scalar(
            select(MarketMoneyflowDc).where(MarketMoneyflowDc.trade_date == trade_date)
        )
        prev_net_amount = (
            session.scalar(
                select(MarketMoneyflowDc.net_amount).where(MarketMoneyflowDc.trade_date == prev_trade_date)
            )
            if prev_trade_date is not None
            else None
        )
        return MoneyFlowMetricsSnapshot(
            today_net_amount=self._to_float(current_row.net_amount) if current_row is not None else None,
            prev_net_amount=self._to_float(prev_net_amount),
            by_order_size=OrderSizeFlowSnapshot(
                elg_amount=self._to_float(current_row.buy_elg_amount) if current_row is not None else None,
                elg_rate=self._to_float(current_row.buy_elg_amount_rate) if current_row is not None else None,
                lg_amount=self._to_float(current_row.buy_lg_amount) if current_row is not None else None,
                lg_rate=self._to_float(current_row.buy_lg_amount_rate) if current_row is not None else None,
                md_amount=self._to_float(current_row.buy_md_amount) if current_row is not None else None,
                md_rate=self._to_float(current_row.buy_md_amount_rate) if current_row is not None else None,
                sm_amount=self._to_float(current_row.buy_sm_amount) if current_row is not None else None,
                sm_rate=self._to_float(current_row.buy_sm_amount_rate) if current_row is not None else None,
            ),
        )

    def load_history_points(
        self,
        session: Session,
        *,
        trade_dates: list[date],
    ) -> list[MoneyFlowHistoryPoint]:
        amounts_map = self.load_amounts_by_trade_dates(session, trade_dates=trade_dates)
        return [
            MoneyFlowHistoryPoint(
                trade_date=trade_day,
                net_amount=amounts_map.get(trade_day),
            )
            for trade_day in trade_dates
        ]

    def load_amounts_by_trade_dates(self, session: Session, *, trade_dates: list[date]) -> dict[date, float | None]:
        if not trade_dates:
            return {}
        rows = session.execute(
            select(MarketMoneyflowDc.trade_date, MarketMoneyflowDc.net_amount).where(
                MarketMoneyflowDc.trade_date.in_(tuple(trade_dates))
            )
        ).all()
        return {
            row.trade_date: self._to_float(row.net_amount)
            for row in rows
        }

    @staticmethod
    def _to_float(value: Decimal | int | float | None) -> float | None:
        if value is None:
            return None
        return float(value)
