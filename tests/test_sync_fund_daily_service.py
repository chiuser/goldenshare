from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_fund_daily_service import SyncFundDailyService, build_fund_daily_params


def test_build_fund_daily_params_does_not_include_ts_code_for_full() -> None:
    params = build_fund_daily_params(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
        ts_code="510300.SH",
    )
    assert params == {
        "start_date": "20260301",
        "end_date": "20260331",
    }


def test_sync_fund_daily_incremental_paginates_by_limit_and_offset(mocker) -> None:
    session = mocker.Mock()
    service = SyncFundDailyService(session)
    service.page_limit = 2

    mocker.patch.object(
        service.client,
        "call",
        side_effect=[
            [
                {"ts_code": "510300.SH", "trade_date": "2026-03-31", "open": "1", "high": "1", "low": "1", "close": "1", "pre_close": "1", "change": "0", "pct_chg": "0", "vol": "1", "amount": "1"},
                {"ts_code": "159915.SZ", "trade_date": "2026-03-31", "open": "2", "high": "2", "low": "2", "close": "2", "pre_close": "2", "change": "0", "pct_chg": "0", "vol": "2", "amount": "2"},
            ],
            [
                {"ts_code": "512880.SH", "trade_date": "2026-03-31", "open": "3", "high": "3", "low": "3", "close": "3", "pre_close": "3", "change": "0", "pct_chg": "0", "vol": "3", "amount": "3"},
            ],
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_fund_daily, "bulk_upsert", side_effect=[2, 1])
    core_upsert = mocker.patch.object(service.dao.fund_daily_bar, "bulk_upsert", side_effect=[2, 1])

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 3, 31))

    assert fetched == 3
    assert written == 3
    assert result_date == date(2026, 3, 31)
    assert message is None
    assert service.client.call.call_args_list[0].kwargs["params"] == {"trade_date": "20260331", "limit": 2, "offset": 0}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"trade_date": "20260331", "limit": 2, "offset": 2}
    assert raw_upsert.call_count == 2
    assert core_upsert.call_count == 2
