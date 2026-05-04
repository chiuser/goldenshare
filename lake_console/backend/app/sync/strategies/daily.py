from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.tushare_daily_sync_service import TushareDailySyncService
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.services.prod_raw_daily_export_service import ProdRawDailyExportService
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class DailyStrategy:
    dataset_key = "daily"

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
        if source == PROD_RAW_DB_SOURCE:
            return ProdRawDailyExportService(
                lake_root=context.lake_root,
                database_url=context.settings.prod_raw_db_url,
            ).export(
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
            )
        if source != "tushare":
            raise ValueError("daily 只支持 --from tushare 或 --from prod-raw-db。")
        return TushareDailySyncService(lake_root=context.lake_root, client=context.client).sync(
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )
