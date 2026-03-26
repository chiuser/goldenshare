from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.stk_period_bar_adj import StkPeriodBarAdj


class StkPeriodBarAdjDAO(BaseDAO[StkPeriodBarAdj]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, StkPeriodBarAdj)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_bars(self, ts_code: str, freq: str, start_date: date, end_date: date) -> list[StkPeriodBarAdj]:
        stmt = (
            select(StkPeriodBarAdj)
            .where(
                StkPeriodBarAdj.ts_code == ts_code,
                StkPeriodBarAdj.freq == freq,
                StkPeriodBarAdj.trade_date >= start_date,
                StkPeriodBarAdj.trade_date <= end_date,
            )
            .order_by(StkPeriodBarAdj.trade_date)
        )
        return list(self.session.scalars(stmt))

    def get_latest_bar(self, ts_code: str, freq: str, trade_date_or_before: date) -> StkPeriodBarAdj | None:
        stmt = (
            select(StkPeriodBarAdj)
            .where(
                StkPeriodBarAdj.ts_code == ts_code,
                StkPeriodBarAdj.freq == freq,
                StkPeriodBarAdj.trade_date <= trade_date_or_before,
            )
            .order_by(desc(StkPeriodBarAdj.trade_date))
            .limit(1)
        )
        return self.session.scalar(stmt)
