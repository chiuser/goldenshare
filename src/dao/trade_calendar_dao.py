from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.trade_calendar import TradeCalendar


class TradeCalendarDAO(BaseDAO[TradeCalendar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TradeCalendar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_open_dates(self, exchange: str, start_date: date, end_date: date) -> list[date]:
        stmt = (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.trade_date >= start_date,
                TradeCalendar.trade_date <= end_date,
                TradeCalendar.is_open.is_(True),
            )
            .order_by(TradeCalendar.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_open_date(self, exchange: str, before_or_on: date) -> date | None:
        stmt = (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.trade_date <= before_or_on,
                TradeCalendar.is_open.is_(True),
            )
            .order_by(desc(TradeCalendar.trade_date))
            .limit(1)
        )
        return self.session.scalar(stmt)
