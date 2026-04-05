from __future__ import annotations

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

    def get_active_indexes(self) -> list[IndexBasic]:
        stmt = select(IndexBasic)
        return list(self.session.scalars(stmt))
