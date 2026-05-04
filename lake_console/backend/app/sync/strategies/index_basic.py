from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.tushare_index_basic_sync_service import TushareIndexBasicSyncService
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class IndexBasicStrategy:
    dataset_key = "index_basic"

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
        source: str = "tushare",
    ) -> LakeSyncResult:
        if source != "tushare":
            raise ValueError("index_basic 当前只支持 --from tushare。")
        return TushareIndexBasicSyncService(lake_root=context.lake_root, client=context.client).sync(
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
