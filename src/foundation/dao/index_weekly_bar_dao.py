from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar


class IndexWeeklyBarDAO(BaseDAO[IndexWeeklyBar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexWeeklyBar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_bars(self, ts_code: str, start_date: date, end_date: date) -> list[IndexWeeklyBar]:
        stmt = (
            select(IndexWeeklyBar)
            .where(
                IndexWeeklyBar.ts_code == ts_code,
                IndexWeeklyBar.trade_date >= start_date,
                IndexWeeklyBar.trade_date <= end_date,
            )
            .order_by(IndexWeeklyBar.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_trade_date(self, ts_code: str) -> date | None:
        stmt = select(IndexWeeklyBar.trade_date).where(IndexWeeklyBar.ts_code == ts_code).order_by(desc(IndexWeeklyBar.trade_date)).limit(1)
        return self.session.scalar(stmt)
