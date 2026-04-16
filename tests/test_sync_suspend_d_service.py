from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync.sync_suspend_d_service import SyncSuspendDService


def test_sync_suspend_d_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_suspend_d_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncSuspendDService(session)

    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")


def test_sync_suspend_d_incremental_paginates_and_writes_with_row_hash(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.side_effect = [
        [
            {
                "trade_date": "20260410",
                "ts_code": "000001.SZ",
                "suspend_timing": "09:30-10:30",
                "suspend_type": "S",
            }
        ]
    ]
    mocker.patch("src.foundation.services.sync.sync_suspend_d_service.TushareHttpClient", return_value=client)
    service = SyncSuspendDService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_suspend_d, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.equity_suspend_d, "bulk_upsert", return_value=1)
    progress = mocker.patch.object(service, "_update_progress")

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 10),
        suspend_type="s",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 10)
    assert message is None
    client.call.assert_called_once_with(
        "suspend_d",
        params={"trade_date": "20260410", "suspend_type": "S", "limit": 5000, "offset": 0},
        fields=service.fields,
    )
    raw_row = raw_upsert.call_args.args[0][0]
    assert raw_row["trade_date"] == date(2026, 4, 10)
    assert raw_row["row_key_hash"]
    assert len(raw_row["row_key_hash"]) == 64
    assert raw_row["suspend_timing"] == "09:30-10:30"
    assert raw_row["suspend_type"] == "S"
    assert raw_upsert.call_args.kwargs["conflict_columns"] == ["row_key_hash"]
    assert core_upsert.call_args.kwargs["conflict_columns"] == ["row_key_hash"]
    assert progress.call_count == 1


def test_sync_suspend_d_history_requires_explicit_time_params(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_suspend_d_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncSuspendDService(session)

    with pytest.raises(ValueError, match="requires explicit time params"):
        service.execute("FULL")


def test_sync_suspend_d_history_fans_out_by_trade_calendar(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_suspend_d_service.TushareHttpClient", return_value=mocker.Mock())
    service = SyncSuspendDService(session)
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
        suspend_type="R",
    )

    assert fetched == 21
    assert written == 17
    assert result_date == date(2026, 4, 2)
    assert message == "trade_dates=2"
    assert sync_one_day.call_count == 2
    assert sync_one_day.call_args_list[0].kwargs["trade_date"] == date(2026, 4, 1)
    assert sync_one_day.call_args_list[0].kwargs["suspend_type"] == "R"
    assert sync_one_day.call_args_list[1].kwargs["trade_date"] == date(2026, 4, 2)
    assert progress.call_count == 3

