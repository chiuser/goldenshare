from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.core.etf_basic import EtfBasic


class EtfBasicDAO(BaseDAO[EtfBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EtfBasic)

    def get_active_etfs(self) -> list[EtfBasic]:
        stmt = select(EtfBasic).where(EtfBasic.list_status.in_(["L", "P", "D"]))
        return list(self.session.scalars(stmt))
