from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.utils import coerce_row


class HttpResourceSyncService(BaseSyncService):
    api_name: str
    raw_dao_name: str
    core_dao_name: str
    date_fields: tuple[str, ...] = ()
    decimal_fields: tuple[str, ...] = ()
    fields: tuple[str, ...] | list[str] = ()
    params_builder = staticmethod(lambda run_type, trade_date=None, **kwargs: {})
    core_transform = staticmethod(lambda row: row)

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(self.api_name, params=self.params_builder(run_type, **kwargs), fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)
        raw_dao.bulk_upsert(normalized)
        written = core_dao.bulk_upsert([self.core_transform(row) for row in normalized])
        return len(rows), written, trade_date, None
