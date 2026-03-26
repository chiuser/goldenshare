from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.index_monthly_bar import IndexMonthlyBar


class IndexMonthlyBarDAO(BaseDAO[IndexMonthlyBar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexMonthlyBar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_bars(self, ts_code: str, start_date: date, end_date: date) -> list[IndexMonthlyBar]:
        stmt = (
            select(IndexMonthlyBar)
            .where(
                IndexMonthlyBar.ts_code == ts_code,
                IndexMonthlyBar.trade_date >= start_date,
                IndexMonthlyBar.trade_date <= end_date,
            )
            .order_by(IndexMonthlyBar.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_trade_date(self, ts_code: str) -> date | None:
        stmt = select(IndexMonthlyBar.trade_date).where(IndexMonthlyBar.ts_code == ts_code).order_by(desc(IndexMonthlyBar.trade_date)).limit(1)
        return self.session.scalar(stmt)
