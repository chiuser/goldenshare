from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync.sync_stk_factor_pro_service import SyncStkFactorProService


def test_sync_stk_factor_pro_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_factor_pro_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkFactorProService(session)

    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")


def test_sync_stk_factor_pro_incremental_paginates_and_writes(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.side_effect = [
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260410",
                "close_bfq": 10.11,
                "open_bfq": 10.01,
                "macd_bfq": 0.12,
                "rsi_bfq_6": 56.78,
            }
        ]
    ]
    mocker.patch("src.foundation.services.sync.sync_stk_factor_pro_service.TushareHttpClient", return_value=client)
    service = SyncStkFactorProService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_stk_factor_pro, "bulk_upsert", return_value=1)
    serving_upsert = mocker.patch.object(service.dao.equity_factor_pro, "bulk_upsert", return_value=1)
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 10))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 10)
    assert message is None
    client.call.assert_called_once_with(
        "stk_factor_pro",
        params={"trade_date": "20260410", "limit": 10000, "offset": 0},
        fields=service.fields,
    )
    row = raw_upsert.call_args.args[0][0]
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["close_bfq"] == 10.11
    serving_row = serving_upsert.call_args.args[0][0]
    assert serving_row["source"] == "tushare"
    assert progress.call_count == 1


def test_sync_stk_factor_pro_history_requires_explicit_time_params(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_factor_pro_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkFactorProService(session)

    with pytest.raises(ValueError, match="requires explicit time params"):
        service.execute("FULL")


def test_sync_stk_factor_pro_history_fans_out_by_trade_calendar(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_factor_pro_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkFactorProService(session)
    mocker.patch.object(
        service.dao.trade_calendar,
        "get_open_dates",
        return_value=[date(2026, 4, 1), date(2026, 4, 2)],
    )
    sync_one_day = mocker.patch.object(service, "_sync_trade_date", side_effect=[(100, 80), (110, 90)])
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-04-01",
        end_date="2026-04-02",
    )

    assert fetched == 210
    assert written == 170
    assert result_date == date(2026, 4, 2)
    assert message == "trade_dates=2"
    assert sync_one_day.call_count == 2
    assert sync_one_day.call_args_list[0].kwargs["trade_date"] == date(2026, 4, 1)
    assert sync_one_day.call_args_list[1].kwargs["trade_date"] == date(2026, 4, 2)
    assert progress.call_count == 3

