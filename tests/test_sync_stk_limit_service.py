from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.foundation.services.sync.sync_stk_limit_service import SyncStkLimitService


def test_sync_stk_limit_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_limit_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkLimitService(session)

    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")


def test_sync_stk_limit_incremental_paginates_and_writes(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.side_effect = [
        [
            {
                "trade_date": "20260410",
                "ts_code": "000001.SZ",
                "pre_close": "10.11",
                "up_limit": "11.12",
                "down_limit": "9.10",
            }
        ]
    ]
    mocker.patch("src.foundation.services.sync.sync_stk_limit_service.TushareHttpClient", return_value=client)
    service = SyncStkLimitService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_stk_limit, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.equity_stk_limit, "bulk_upsert", return_value=1)
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 10))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 10)
    assert message is None
    client.call.assert_called_once_with(
        "stk_limit",
        params={"trade_date": "20260410", "limit": 5800, "offset": 0},
        fields=service.fields,
    )
    raw_row = raw_upsert.call_args.args[0][0]
    assert raw_row["trade_date"] == date(2026, 4, 10)
    assert raw_row["pre_close"] == Decimal("10.11")
    assert raw_row["up_limit"] == Decimal("11.12")
    assert raw_row["down_limit"] == Decimal("9.10")
    core_upsert.assert_called_once()
    assert progress.call_count == 1


def test_sync_stk_limit_history_requires_explicit_time_params(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_limit_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkLimitService(session)

    with pytest.raises(ValueError, match="requires explicit time params"):
        service.execute("FULL")


def test_sync_stk_limit_history_fans_out_by_trade_calendar(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_limit_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkLimitService(session)
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
