from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.services.sync.fields import BLOCK_TRADE_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.foundation.services.sync.sync_daily_basic_service import build_trade_date_only
from src.utils import coerce_row


class SyncBlockTradeService(HttpResourceSyncService):
    job_name = "sync_block_trade"
    target_table = "core.equity_block_trade"
    api_name = "block_trade"
    raw_dao_name = "raw_block_trade"
    core_dao_name = "equity_block_trade"
    fields = BLOCK_TRADE_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("price", "vol", "amount")
    params_builder = staticmethod(build_trade_date_only)

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(self.api_name, params=self.params_builder(run_type, **kwargs), fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)

        # block_trade 原始数据存在业务性重复行：按业务日期重建快照，保留所有重复明细。
        target_dates = sorted({row["trade_date"] for row in normalized if row.get("trade_date") is not None})
        for current_date in target_dates:
            raw_dao.delete_by_date_range(current_date, current_date)
            core_dao.delete_by_date_range(current_date, current_date)

        raw_dao.bulk_insert(normalized)
        written = core_dao.bulk_insert(normalized)
        return len(rows), written, trade_date, None
