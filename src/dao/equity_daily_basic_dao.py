from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.equity_daily_basic import EquityDailyBasic


class EquityDailyBasicDAO(BaseDAO[EquityDailyBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EquityDailyBasic)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_snapshot(self, trade_date: date) -> list[EquityDailyBasic]:
        stmt = select(EquityDailyBasic).where(EquityDailyBasic.trade_date == trade_date)
        return list(self.session.scalars(stmt))
