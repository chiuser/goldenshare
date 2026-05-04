from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.prod_raw_current_export_service import ProdRawCurrentExportService
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class ETFBasicStrategy:
    dataset_key = "etf_basic"

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
        _require_prod_raw_source(self.dataset_key, source)
        _reject_snapshot_filters(
            dataset_key=self.dataset_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
        return ProdRawCurrentExportService(
            lake_root=context.lake_root,
            database_url=context.settings.prod_raw_db_url,
        ).export(dataset_key=self.dataset_key)


class ETFIndexStrategy:
    dataset_key = "etf_index"

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
        _require_prod_raw_source(self.dataset_key, source)
        _reject_snapshot_filters(
            dataset_key=self.dataset_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
        return ProdRawCurrentExportService(
            lake_root=context.lake_root,
            database_url=context.settings.prod_raw_db_url,
        ).export(dataset_key=self.dataset_key)


class THSIndexStrategy:
    dataset_key = "ths_index"

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
        _require_prod_raw_source(self.dataset_key, source)
        _reject_snapshot_filters(
            dataset_key=self.dataset_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
        return ProdRawCurrentExportService(
            lake_root=context.lake_root,
            database_url=context.settings.prod_raw_db_url,
        ).export(dataset_key=self.dataset_key)


class THSMemberStrategy:
    dataset_key = "ths_member"

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
        _require_prod_raw_source(self.dataset_key, source)
        _reject_snapshot_filters(
            dataset_key=self.dataset_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            name=name,
            markets=markets,
            publisher=publisher,
            category=category,
        )
        return ProdRawCurrentExportService(
            lake_root=context.lake_root,
            database_url=context.settings.prod_raw_db_url,
        ).export(dataset_key=self.dataset_key)


def _require_prod_raw_source(dataset_key: str, source: str) -> None:
    if source != PROD_RAW_DB_SOURCE:
        raise ValueError(f"{dataset_key} 当前只支持 --from prod-raw-db。")


def _reject_snapshot_filters(
    *,
    dataset_key: str,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
    name: str | None,
    markets: list[str] | None,
    publisher: str | None,
    category: str | None,
) -> None:
    unsupported = {
        "trade_date": trade_date,
        "start_date": start_date,
        "end_date": end_date,
        "ts_code": ts_code,
        "name": name,
        "market": markets,
        "publisher": publisher,
        "category": category,
    }
    provided = [key for key, value in unsupported.items() if value not in (None, [], ())]
    if provided:
        joined = ", ".join(provided)
        raise ValueError(f"{dataset_key} 第一阶段只支持全量 current 快照，不支持参数：{joined}")
