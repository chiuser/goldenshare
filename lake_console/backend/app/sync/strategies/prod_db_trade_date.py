from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.db_trade_date_export_service import DbTradeDateExportService
from lake_console.backend.app.services.prod_core_db import (
    PROD_CORE_DB_SOURCE,
    build_prod_core_trade_date_query,
    build_prod_core_trade_date_range_query,
    fetch_prod_core_rows,
    iter_prod_core_rows,
)
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_SOURCE,
    build_prod_raw_trade_date_query,
    build_prod_raw_trade_date_range_query,
    fetch_prod_raw_rows,
    iter_prod_raw_rows,
)
from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class AdjFactorStrategy:
    dataset_key = "adj_factor"

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
        _reject_unused_filters(self.dataset_key, name=name, markets=markets, publisher=publisher, category=category)
        _require_source(self.dataset_key, source, PROD_RAW_DB_SOURCE)
        return DbTradeDateExportService(
            lake_root=context.lake_root,
            dataset_key=self.dataset_key,
            api_name="adj_factor",
            source=source,
            database_url=context.settings.prod_raw_db_url,
            build_point_query=build_prod_raw_trade_date_query,
            build_range_query=build_prod_raw_trade_date_range_query,
            fetch_rows=fetch_prod_raw_rows,
            iter_rows=iter_prod_raw_rows,
        ).export(trade_date=trade_date, start_date=start_date, end_date=end_date, ts_code=ts_code)


class DailyBasicStrategy:
    dataset_key = "daily_basic"

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
        _reject_unused_filters(self.dataset_key, name=name, markets=markets, publisher=publisher, category=category)
        _require_source(self.dataset_key, source, PROD_RAW_DB_SOURCE)
        return DbTradeDateExportService(
            lake_root=context.lake_root,
            dataset_key=self.dataset_key,
            api_name="daily_basic",
            source=source,
            database_url=context.settings.prod_raw_db_url,
            build_point_query=build_prod_raw_trade_date_query,
            build_range_query=build_prod_raw_trade_date_range_query,
            fetch_rows=fetch_prod_raw_rows,
            iter_rows=iter_prod_raw_rows,
        ).export(trade_date=trade_date, start_date=start_date, end_date=end_date, ts_code=ts_code)


class IndexDailyBasicStrategy:
    dataset_key = "index_daily_basic"

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
        _reject_unused_filters(self.dataset_key, name=name, markets=markets, publisher=publisher, category=category)
        _require_source(self.dataset_key, source, PROD_RAW_DB_SOURCE)
        return DbTradeDateExportService(
            lake_root=context.lake_root,
            dataset_key=self.dataset_key,
            api_name="index_dailybasic",
            source=source,
            database_url=context.settings.prod_raw_db_url,
            build_point_query=build_prod_raw_trade_date_query,
            build_range_query=build_prod_raw_trade_date_range_query,
            fetch_rows=fetch_prod_raw_rows,
            iter_rows=iter_prod_raw_rows,
        ).export(trade_date=trade_date, start_date=start_date, end_date=end_date, ts_code=ts_code)


class IndexDailyStrategy:
    dataset_key = "index_daily"

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
        _reject_unused_filters(self.dataset_key, name=name, markets=markets, publisher=publisher, category=category)
        _require_source(self.dataset_key, source, PROD_CORE_DB_SOURCE)
        return DbTradeDateExportService(
            lake_root=context.lake_root,
            dataset_key=self.dataset_key,
            api_name="index_daily",
            source=source,
            database_url=context.settings.prod_core_db_url,
            build_point_query=build_prod_core_trade_date_query,
            build_range_query=build_prod_core_trade_date_range_query,
            fetch_rows=fetch_prod_core_rows,
            iter_rows=iter_prod_core_rows,
        ).export(trade_date=trade_date, start_date=start_date, end_date=end_date, ts_code=ts_code)


def _require_source(dataset_key: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError(f"{dataset_key} 当前只支持 --from {expected}。")


def _reject_unused_filters(
    dataset_key: str,
    *,
    name: str | None,
    markets: list[str] | None,
    publisher: str | None,
    category: str | None,
) -> None:
    unsupported = {
        "name": name,
        "market": markets,
        "publisher": publisher,
        "category": category,
    }
    provided = [key for key, value in unsupported.items() if value not in (None, [], ())]
    if provided:
        joined = ", ".join(provided)
        raise ValueError(f"{dataset_key} 当前不支持参数：{joined}")
