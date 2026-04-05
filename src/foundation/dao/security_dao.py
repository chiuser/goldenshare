from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core.security import Security


class SecurityDAO(BaseDAO[Security]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Security)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_active_equities(self) -> list[Security]:
        stmt = select(Security).where(Security.security_type == "EQUITY", Security.list_status.in_(["L", "P", "D"]))
        return list(self.session.scalars(stmt))

    def get_by_ts_code(self, ts_code: str) -> Security | None:
        return self.fetch_by_pk(ts_code)
