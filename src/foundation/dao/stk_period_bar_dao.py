from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core.stk_period_bar import StkPeriodBar


class StkPeriodBarDAO(BaseDAO[StkPeriodBar]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, StkPeriodBar)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_bars(self, ts_code: str, freq: str, start_date: date, end_date: date) -> list[StkPeriodBar]:
        stmt = (
            select(StkPeriodBar)
            .where(
                StkPeriodBar.ts_code == ts_code,
                StkPeriodBar.freq == freq,
                StkPeriodBar.trade_date >= start_date,
                StkPeriodBar.trade_date <= end_date,
            )
            .order_by(StkPeriodBar.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_bar(self, ts_code: str, freq: str, trade_date_or_before: date) -> StkPeriodBar | None:
        stmt = (
            select(StkPeriodBar)
            .where(
                StkPeriodBar.ts_code == ts_code,
                StkPeriodBar.freq == freq,
                StkPeriodBar.trade_date <= trade_date_or_before,
            )
            .order_by(desc(StkPeriodBar.trade_date))
            .limit(1)
        )
        return self.session.scalar(stmt)
