from __future__ import annotations

from datetime import date

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core.index_basic import IndexBasic


class IndexBasicDAO(BaseDAO[IndexBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexBasic)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_by_ts_code(self, ts_code: str) -> IndexBasic | None:
        return self.fetch_by_pk(ts_code)

    def list_by_market(self, market: str) -> list[IndexBasic]:
        stmt = select(IndexBasic).where(IndexBasic.market == market)
        return list(self.session.scalars(stmt))

    def get_active_indexes(self, as_of: date | None = None) -> list[IndexBasic]:
        effective_date = as_of or date.today()
        stmt = (
            select(IndexBasic)
            .where(or_(IndexBasic.exp_date.is_(None), IndexBasic.exp_date >= effective_date))
            .order_by(IndexBasic.ts_code)
        )
        return list(self.session.scalars(stmt))
