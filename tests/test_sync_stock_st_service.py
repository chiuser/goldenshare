from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync.sync_stock_st_service import SyncStockStService


def test_sync_stock_st_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stock_st_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStockStService(session)

    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")


def test_sync_stock_st_incremental_paginates_and_writes(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.side_effect = [
        [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "trade_date": "20260416",
                "type": "ST",
                "type_name": "特别处理",
            }
        ]
    ]
    mocker.patch("src.foundation.services.sync.sync_stock_st_service.TushareHttpClient", return_value=client)
    service = SyncStockStService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_stock_st, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.equity_stock_st, "bulk_upsert", return_value=1)
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 16),
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 16)
    assert message is None
    client.call.assert_called_once_with(
        "stock_st",
        params={"trade_date": "20260416", "limit": 1000, "offset": 0},
        fields=service.fields,
    )
    raw_row = raw_upsert.call_args.args[0][0]
    assert raw_row["ts_code"] == "000001.SZ"
    assert raw_row["trade_date"] == date(2026, 4, 16)
    assert raw_row["type"] == "ST"
    assert raw_row["type_name"] == "特别处理"
    core_upsert.assert_called_once()
    assert progress.call_count == 1


def test_sync_stock_st_history_requires_explicit_time_params(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stock_st_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStockStService(session)

    with pytest.raises(ValueError, match="requires explicit time params"):
        service.execute("FULL")


def test_sync_stock_st_history_fans_out_by_trade_calendar(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stock_st_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStockStService(session)
    mocker.patch.object(
        service.dao.trade_calendar,
        "get_open_dates",
        return_value=[date(2026, 4, 1), date(2026, 4, 2)],
    )
    sync_one_day = mocker.patch.object(service, "_sync_trade_date", side_effect=[(10, 8), (11, 9)])
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-04-01",
        end_date="2026-04-02",
    )

    assert fetched == 21
    assert written == 17
    assert result_date == date(2026, 4, 2)
    assert message == "trade_dates=2"
    assert sync_one_day.call_count == 2
    assert sync_one_day.call_args_list[0].kwargs["trade_date"] == date(2026, 4, 1)
    assert sync_one_day.call_args_list[1].kwargs["trade_date"] == date(2026, 4, 2)
    assert progress.call_count == 3


def test_sync_stock_st_history_clips_to_available_start_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stock_st_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStockStService(session)
    get_open_dates = mocker.patch.object(
        service.dao.trade_calendar,
        "get_open_dates",
        return_value=[date(2016, 1, 4)],
    )
    sync_one_day = mocker.patch.object(service, "_sync_trade_date", return_value=(5, 5))

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2015-01-01",
        end_date="2016-01-10",
    )

    assert fetched == 5
    assert written == 5
    assert result_date == date(2016, 1, 10)
    assert message == "trade_dates=1"
    get_open_dates.assert_called_once_with("SSE", date(2016, 1, 1), date(2016, 1, 10))
    sync_one_day.assert_called_once()
