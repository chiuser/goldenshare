from __future__ import annotations

from pathlib import Path
from datetime import date
from typing import Any

from lake_console.backend.app.settings import LakeConsoleSettings
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.strategies import STRATEGY_CLASSES


class LakeSyncEngine:
    def __init__(self, *, lake_root: Path, client: TushareLakeClient, settings: LakeConsoleSettings) -> None:
        self.context = LakeSyncContext(lake_root=lake_root, client=client, settings=settings)

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
        source: str = "tushare",
    ) -> dict[str, Any]:
        strategy_class = STRATEGY_CLASSES.get(dataset_key)
        if strategy_class is None:
            available = "/".join(sorted(STRATEGY_CLASSES))
            raise ValueError(f"sync-dataset 当前只接入 {available}；其他数据集需先完成对应策略文件。")
        return strategy_class().sync(
            context=self.context,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
            source=source,
        )
