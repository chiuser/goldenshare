from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.index_daily_basic import IndexDailyBasic


class IndexDailyBasicDAO(BaseDAO[IndexDailyBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexDailyBasic)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_snapshot(self, trade_date: date) -> list[IndexDailyBasic]:
        stmt = select(IndexDailyBasic).where(IndexDailyBasic.trade_date == trade_date)
        return list(self.session.scalars(stmt))

    def get_by_ts_code(self, ts_code: str, start_date: date, end_date: date) -> list[IndexDailyBasic]:
        stmt = (
            select(IndexDailyBasic)
            .where(
                IndexDailyBasic.ts_code == ts_code,
                IndexDailyBasic.trade_date >= start_date,
                IndexDailyBasic.trade_date <= end_date,
            )
            .order_by(IndexDailyBasic.trade_date)
        )
        return list(self.session.scalars(stmt))
