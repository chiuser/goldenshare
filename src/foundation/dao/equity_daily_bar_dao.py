from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


class EquityDailyBarDAO(BaseDAO[EquityDailyBar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EquityDailyBar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_latest_trade_date(self, ts_code: str) -> date | None:
        stmt = (
            select(EquityDailyBar.trade_date)
            .where(EquityDailyBar.ts_code == ts_code)
            .order_by(desc(EquityDailyBar.trade_date))
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_bars(self, ts_code: str, start_date: date, end_date: date) -> list[EquityDailyBar]:
        stmt = (
            select(EquityDailyBar)
            .where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date >= start_date,
                EquityDailyBar.trade_date <= end_date,
            )
            .order_by(EquityDailyBar.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_n_bars(self, ts_code: str, n: int) -> list[EquityDailyBar]:
        stmt = select(EquityDailyBar).where(EquityDailyBar.ts_code == ts_code).order_by(desc(EquityDailyBar.trade_date)).limit(n)
        return list(self.session.scalars(stmt))
