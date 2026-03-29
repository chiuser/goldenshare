from __future__ import annotations

from datetime import date

from src.services.sync.sync_etf_basic_service import SyncEtfBasicService, build_etf_basic_params
from src.services.sync.sync_index_daily_basic_service import SyncIndexDailyBasicService, build_index_daily_basic_params
from src.services.sync.sync_index_weight_service import build_index_weight_params
from src.services.sync.sync_stk_period_bar_adj_month_service import SyncStkPeriodBarAdjMonthService
from src.services.sync.sync_stk_period_bar_adj_week_service import SyncStkPeriodBarAdjWeekService
from src.services.sync.sync_stk_period_bar_month_service import SyncStkPeriodBarMonthService
from src.services.sync.sync_stk_period_bar_week_service import SyncStkPeriodBarWeekService


def test_stk_period_bar_week_builds_trade_date_params() -> None:
    params = SyncStkPeriodBarWeekService.params_builder("FULL", trade_date=date(2026, 3, 27))
    assert params == {"freq": "week", "trade_date": "20260327"}


def test_stk_period_bar_adj_week_builds_full_range_params() -> None:
    params = SyncStkPeriodBarAdjWeekService.params_builder(
        "FULL",
        ts_code="000001.SZ",
        start_date="2010-01-01",
        end_date="2026-03-24",
    )
    assert params == {
        "freq": "week",
        "ts_code": "000001.SZ",
        "start_date": "20100101",
        "end_date": "20260324",
    }


def test_stk_period_bar_month_builds_full_range_params() -> None:
    params = SyncStkPeriodBarMonthService.params_builder(
        "FULL",
        ts_code="000001.SZ",
        start_date="2010-01-01",
        end_date="2026-03-24",
    )
    assert params == {
        "freq": "month",
        "ts_code": "000001.SZ",
        "start_date": "20100101",
        "end_date": "20260324",
    }


def test_stk_period_bar_adj_month_builds_full_range_params() -> None:
    params = SyncStkPeriodBarAdjMonthService.params_builder(
        "FULL",
        ts_code="000001.SZ",
        start_date="2010-01-01",
        end_date="2026-03-24",
    )
    assert params == {
        "freq": "month",
        "ts_code": "000001.SZ",
        "start_date": "20100101",
        "end_date": "20260324",
    }


def test_index_weight_prefers_index_code_and_builds_month_bounds() -> None:
    params = build_index_weight_params("INCREMENTAL", trade_date=date(2026, 3, 25), index_code="000300.SH", ts_code="ignored")
    assert params == {"index_code": "000300.SH", "start_date": "20260301", "end_date": "20260331"}


def test_index_daily_basic_accepts_sparse_trade_date_queries() -> None:
    params = build_index_daily_basic_params("INCREMENTAL", trade_date=date(2026, 3, 25))
    assert params == {"trade_date": "20260325"}


def test_index_daily_basic_service_fields_are_explicit() -> None:
    assert SyncIndexDailyBasicService.fields


def test_etf_basic_builds_default_full_sync_params() -> None:
    params = build_etf_basic_params("FULL")

    assert params == {}


def test_etf_basic_builds_filtered_params() -> None:
    params = build_etf_basic_params(
        "FULL",
        ts_code="510300.SH",
        index_code="000300.SH",
        list_date="2026-03-29",
        exchange="SSE",
        mgr="华泰柏瑞基金",
        list_status="L",
    )

    assert params == {
        "list_status": "L",
        "ts_code": "510300.SH",
        "index_code": "000300.SH",
        "list_date": "20260329",
        "exchange": "SSE",
        "mgr": "华泰柏瑞基金",
    }


def test_etf_basic_service_fields_are_explicit() -> None:
    assert SyncEtfBasicService.fields
