from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.foundation.services.sync.sync_stk_nineturn_service import SyncStkNineTurnService


def test_sync_stk_nineturn_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_nineturn_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkNineTurnService(session)

    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")


def test_sync_stk_nineturn_incremental_paginates_and_writes(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.side_effect = [
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260410",
                "freq": "D",
                "open": "10.11",
                "high": "10.22",
                "low": "9.98",
                "close": "10.05",
                "vol": "123456.0000",
                "amount": "987654.0000",
                "up_count": "3",
                "down_count": "0",
                "nine_up_turn": "Y",
                "nine_down_turn": "N",
            }
        ]
    ]
    mocker.patch("src.foundation.services.sync.sync_stk_nineturn_service.TushareHttpClient", return_value=client)
    service = SyncStkNineTurnService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_stk_nineturn, "bulk_upsert", return_value=1)
    serving_upsert = mocker.patch.object(service.dao.equity_nineturn, "bulk_upsert", return_value=1)
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 10))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 10)
    assert message is None
    client.call.assert_called_once_with(
        "stk_nineturn",
        params={"trade_date": "20260410", "freq": "D", "limit": 10000, "offset": 0},
        fields=service.fields,
    )
    row = raw_upsert.call_args.args[0][0]
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["open"] == Decimal("10.11")
    assert row["up_count"] == Decimal("3")
    serving_upsert.assert_called_once()
    assert progress.call_count == 1


def test_sync_stk_nineturn_history_requires_explicit_time_params(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_nineturn_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkNineTurnService(session)

    with pytest.raises(ValueError, match="requires explicit time params"):
        service.execute("FULL")


def test_sync_stk_nineturn_history_fans_out_by_trade_calendar(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_nineturn_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkNineTurnService(session)
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


def test_sync_stk_nineturn_history_range_before_supported_start_returns_hint(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_stk_nineturn_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncStkNineTurnService(session)
    sync_one_day = mocker.patch.object(service, "_sync_trade_date")

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2022-01-01",
        end_date="2022-12-30",
    )

    assert fetched == 0
    assert written == 0
    assert result_date == date(2022, 12, 30)
    assert message == "区间早于可用起点 2023-01-01，未执行同步"
    sync_one_day.assert_not_called()

