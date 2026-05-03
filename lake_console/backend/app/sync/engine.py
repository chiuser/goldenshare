from __future__ import annotations

from pathlib import Path
from datetime import date
from typing import Any

from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_daily_sync_service import TushareDailySyncService
from lake_console.backend.app.services.tushare_index_basic_sync_service import TushareIndexBasicSyncService


class LakeSyncEngine:
    def __init__(self, *, lake_root: Path, client: TushareLakeClient) -> None:
        self.lake_root = lake_root
        self.client = client

    def sync_dataset(
        self,
        *,
        dataset_key: str,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
        name: str | None = None,
        markets: list[str] | None = None,
        publisher: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        if dataset_key == "daily":
            return TushareDailySyncService(lake_root=self.lake_root, client=self.client).sync(
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
            )
        if dataset_key != "index_basic":
            raise ValueError("sync-dataset 当前只接入 index_basic/daily；其他数据集需先完成对应策略文件。")
        return TushareIndexBasicSyncService(lake_root=self.lake_root, client=self.client).sync(
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
