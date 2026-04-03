from __future__ import annotations

from datetime import date

from src.services.sync.sync_etf_basic_service import SyncEtfBasicService, build_etf_basic_params
from src.services.sync.sync_index_daily_service import SyncIndexDailyService, build_index_daily_params
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


def test_index_daily_includes_ts_code_when_provided_for_incremental() -> None:
    params = build_index_daily_params("INCREMENTAL", trade_date=date(2026, 3, 25), ts_code="000001.SH")
    assert params == {"trade_date": "20260325", "ts_code": "000001.SH"}


def test_index_daily_basic_accepts_sparse_trade_date_queries() -> None:
    params = build_index_daily_basic_params("INCREMENTAL", trade_date=date(2026, 3, 25))
    assert params == {"trade_date": "20260325"}


def test_index_daily_basic_service_fields_are_explicit() -> None:
    assert SyncIndexDailyBasicService.fields


def test_index_daily_service_iterates_index_pool_when_ts_code_missing(mocker) -> None:
    session = mocker.Mock()
    service = SyncIndexDailyService(session)
    mocker.patch.object(
        service.dao.index_basic,
        "get_active_indexes",
        return_value=[
            mocker.Mock(ts_code="000001.SH"),
            mocker.Mock(ts_code="399001.SZ"),
        ],
    )
    mocker.patch.object(
        service.client,
        "call",
        side_effect=[
            [{"ts_code": "000001.SH", "trade_date": "20260325", "open": "1", "high": "1", "low": "1", "close": "1", "pre_close": "1", "change": "0", "pct_chg": "0", "vol": "1", "amount": "1"}],
            [{"ts_code": "399001.SZ", "trade_date": "20260325", "open": "2", "high": "2", "low": "2", "close": "2", "pre_close": "2", "change": "0", "pct_chg": "0", "vol": "2", "amount": "2"}],
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_index_daily, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.index_daily_bar, "bulk_upsert", side_effect=[1, 1])

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 3, 25))

    assert fetched == 2
    assert written == 2
    assert result_date == date(2026, 3, 25)
    assert message is None
    assert service.client.call.call_args_list[0].kwargs["params"] == {"trade_date": "20260325", "ts_code": "000001.SH"}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"trade_date": "20260325", "ts_code": "399001.SZ"}
    assert raw_upsert.call_count == 2
    assert core_upsert.call_count == 2


def test_index_daily_service_updates_progress_for_index_pool(mocker) -> None:
    session = mocker.Mock()
    session.get.return_value = None
    service = SyncIndexDailyService(session)
    mocker.patch.object(
        service.dao.index_basic,
        "get_active_indexes",
        return_value=[
            mocker.Mock(ts_code="000001.SH"),
            mocker.Mock(ts_code="399001.SZ"),
        ],
    )
    mocker.patch.object(
        service.client,
        "call",
        side_effect=[
            [{"ts_code": "000001.SH", "trade_date": "20260325", "open": "1", "high": "1", "low": "1", "close": "1", "pre_close": "1", "change": "0", "pct_chg": "0", "vol": "1", "amount": "1"}],
            [{"ts_code": "399001.SZ", "trade_date": "20260325", "open": "2", "high": "2", "low": "2", "close": "2", "pre_close": "2", "change": "0", "pct_chg": "0", "vol": "2", "amount": "2"}],
        ],
    )
    mocker.patch.object(service.dao.raw_index_daily, "bulk_upsert", return_value=1)
    mocker.patch.object(service.dao.index_daily_bar, "bulk_upsert", side_effect=[1, 1])
    progress = mocker.patch.object(service, "_update_progress")

    service.execute("INCREMENTAL", trade_date=date(2026, 3, 25), execution_id=99)

    assert progress.call_count == 3
    assert progress.call_args_list[0].kwargs == {
        "execution_id": 99,
        "current": 0,
        "total": 2,
        "message": "准备按 2 个指数逐个同步日线行情。",
    }
    assert progress.call_args_list[1].kwargs["current"] == 1
    assert progress.call_args_list[2].kwargs["current"] == 2


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
