from __future__ import annotations

from datetime import date

from lake_console.backend.app.catalog.datasets.moneyflow import MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET
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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="adj_factor",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="daily_basic",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class CyqPerfStrategy:
    dataset_key = "cyq_perf"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="cyq_perf",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class FundDailyStrategy:
    dataset_key = "fund_daily"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="fund_daily",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class FundAdjStrategy:
    dataset_key = "fund_adj"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="fund_adj",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="index_dailybasic",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


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


class MarginStrategy:
    dataset_key = "margin"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="margin",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class LimitListDStrategy:
    dataset_key = "limit_list_d"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="limit_list_d",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class LimitListThsStrategy:
    dataset_key = "limit_list_ths"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="limit_list_ths",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class LimitStepStrategy:
    dataset_key = "limit_step"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="limit_step",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class LimitCptListStrategy:
    dataset_key = "limit_cpt_list"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="limit_cpt_list",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


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
        source: str = "tushare",
    ) -> LakeSyncResult:
        _reject_unused_filters(self.dataset_key, name=name, markets=markets, publisher=publisher, category=category)
        _require_source(self.dataset_key, source, PROD_RAW_DB_SOURCE)
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowThsStrategy:
    dataset_key = "moneyflow_ths"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_ths",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowDcStrategy:
    dataset_key = "moneyflow_dc"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_dc",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowCntThsStrategy:
    dataset_key = "moneyflow_cnt_ths"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_cnt_ths",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowIndThsStrategy:
    dataset_key = "moneyflow_ind_ths"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_ind_ths",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowIndDcStrategy:
    dataset_key = "moneyflow_ind_dc"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_ind_dc",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class MoneyflowMktDcStrategy:
    dataset_key = "moneyflow_mkt_dc"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="moneyflow_mkt_dc",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class StkLimitStrategy:
    dataset_key = "stk_limit"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="stk_limit",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class StockStStrategy:
    dataset_key = "stock_st"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="stock_st",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class SuspendDStrategy:
    dataset_key = "suspend_d"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="suspend_d",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


class TopListStrategy:
    dataset_key = "top_list"

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
        return _export_prod_raw_trade_date(
            context=context,
            dataset_key=self.dataset_key,
            api_name="top_list",
            source=source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )


def _export_prod_raw_trade_date(
    *,
    context: LakeSyncContext,
    dataset_key: str,
    api_name: str,
    source: str,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
) -> LakeSyncResult:
    return DbTradeDateExportService(
        lake_root=context.lake_root,
        dataset_key=dataset_key,
        api_name=api_name,
        source=source,
        database_url=context.settings.prod_raw_db_url,
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=fetch_prod_raw_rows,
        iter_rows=iter_prod_raw_rows,
        known_source_gap_dates=MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET.get(dataset_key, ()),
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
