from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.index_weight import IndexWeight


class IndexWeightDAO(BaseDAO[IndexWeight]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexWeight)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_weights(self, index_code: str, start_date: date, end_date: date) -> list[IndexWeight]:
        stmt = (
            select(IndexWeight)
            .where(
                IndexWeight.index_code == index_code,
                IndexWeight.trade_date >= start_date,
                IndexWeight.trade_date <= end_date,
            )
            .order_by(IndexWeight.trade_date, IndexWeight.con_code)
        )
        return list(self.session.scalars(stmt))

    def get_latest_weights(self, index_code: str, trade_date_or_before: date) -> list[IndexWeight]:
        latest_stmt = (
            select(IndexWeight.trade_date)
            .where(
                IndexWeight.index_code == index_code,
                IndexWeight.trade_date <= trade_date_or_before,
            )
            .order_by(desc(IndexWeight.trade_date))
            .limit(1)
        )
        latest_date = self.session.scalar(latest_stmt)
        if latest_date is None:
            return []
        stmt = (
            select(IndexWeight)
            .where(IndexWeight.index_code == index_code, IndexWeight.trade_date == latest_date)
            .order_by(IndexWeight.con_code)
        )
        return list(self.session.scalars(stmt))
