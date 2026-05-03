from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.tushare_moneyflow_sync_service import TushareMoneyflowSyncService
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class MoneyflowStrategy:
    dataset_key = "moneyflow"

    def sync(
        self,
        *,
        context: LakeSyncContext,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
        name: str | None = None,
        markets: list[str] | None = None,
        publisher: str | None = None,
        category: str | None = None,
    ) -> LakeSyncResult:
        return TushareMoneyflowSyncService(lake_root=context.lake_root, client=context.client).sync(
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )
