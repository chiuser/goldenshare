from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor


class EquityAdjFactorDAO(BaseDAO[EquityAdjFactor]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EquityAdjFactor)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_factor_series(self, ts_code: str, start_date: date, end_date: date) -> list[EquityAdjFactor]:
        stmt = (
            select(EquityAdjFactor)
            .where(
                EquityAdjFactor.ts_code == ts_code,
                EquityAdjFactor.trade_date >= start_date,
                EquityAdjFactor.trade_date <= end_date,
            )
            .order_by(EquityAdjFactor.trade_date)
        )
        return list(self.session.scalars(stmt))
