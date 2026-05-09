from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.services.prod_raw_index_mins_export_service import ProdRawIndexMinsExportService
from lake_console.backend.app.services.tushare_index_mins_sync_service import TushareIndexMinsSyncService
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class IndexMinsStrategy:
    dataset_key = "index_mins"

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
        freqs: list[str] | None = None,
    ) -> LakeSyncResult:
        if name is not None or markets or publisher is not None or category is not None:
            raise ValueError("index_mins 当前不支持 name/market/publisher/category 过滤。")
        if not freqs:
            raise ValueError("index_mins 必须传 --freq 或 --freqs。")
        if source == "tushare":
            return TushareIndexMinsSyncService(lake_root=context.lake_root, client=context.client).sync(
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                freqs=freqs,
            )
        if source == PROD_RAW_DB_SOURCE:
            return ProdRawIndexMinsExportService(
                lake_root=context.lake_root,
                database_url=context.settings.prod_raw_db_url,
            ).export(
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                freqs=freqs,
            )
        raise ValueError("index_mins 当前只支持 --from tushare 或 --from prod-raw-db。")
