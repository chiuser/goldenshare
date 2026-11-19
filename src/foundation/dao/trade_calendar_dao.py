from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.clients.reference_data import local_reference_data
from src.foundation.models.core.trade_calendar import TradeCalendar


class TradeCalendarDAO(BaseDAO[TradeCalendar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TradeCalendar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_open_dates(self, exchange: str, start_date: date, end_date: date) -> list[date]:
        reference = local_reference_data(self.session)
        if reference is not None:
            return [row.trade_date for row in reference.calendar.range_rows(
                exchange=exchange, start=start_date, end=end_date, open_only=True,
            )]
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
        reference = local_reference_data(self.session)
        if reference is not None:
            rows = reference.calendar.recent_open_rows(exchange=exchange, bound=before_or_on, limit=1)
            return rows[0].trade_date if rows else None
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
