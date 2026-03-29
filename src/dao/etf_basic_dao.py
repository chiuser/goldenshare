from __future__ import annotations

from sqlalchemy import not_, select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.etf_basic import EtfBasic


class EtfBasicDAO(BaseDAO[EtfBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EtfBasic)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_by_ts_code(self, ts_code: str) -> EtfBasic | None:
        return self.fetch_by_pk(ts_code)

    def get_active_etfs(self) -> list[EtfBasic]:
        stmt = select(EtfBasic).where(EtfBasic.list_status.in_(["L", "P", "D"]))
        return list(self.session.scalars(stmt))

    def get_fund_daily_candidates(self) -> list[EtfBasic]:
        stmt = select(EtfBasic).where(
            EtfBasic.list_status.in_(["L", "P", "D"]),
            not_(EtfBasic.ts_code.like("%.OF")),
        )
        return list(self.session.scalars(stmt))
