from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.foundation.services.sync.sync_margin_service import SyncMarginService


def test_sync_margin_incremental_fans_out_all_exchanges_by_default(mocker) -> None:
    session = mocker.Mock()
    service = SyncMarginService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260416",
            "exchange_id": "SSE",
            "rzye": "1.2",
            "rzmre": "2.3",
            "rzche": "3.4",
            "rqye": "4.5",
            "rqmcl": "5.6",
            "rzrqye": "6.7",
            "rqyl": "7.8",
        }
    ]
    raw_upsert = mocker.patch.object(service.dao.raw_margin, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.equity_margin, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 16))

    assert fetched == 3
    assert written == 3
    assert result_date == date(2026, 4, 16)
    assert message == "trade_date=2026-04-16 exchanges=SSE,SZSE,BSE"
    assert service.client.call.call_count == 3
    assert {call.kwargs["params"]["exchange_id"] for call in service.client.call.call_args_list} == {"SSE", "SZSE", "BSE"}
    raw_upsert.assert_called()
    core_upsert.assert_called()
    row = core_upsert.call_args.args[0][0]
    assert row["trade_date"] == date(2026, 4, 16)
    assert row["rzye"] == Decimal("1.2")


def test_sync_margin_incremental_with_selected_exchange_ids(mocker) -> None:
    session = mocker.Mock()
    service = SyncMarginService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = []
    mocker.patch.object(service.dao.raw_margin, "bulk_upsert", return_value=0)
    mocker.patch.object(service.dao.equity_margin, "bulk_upsert", return_value=0)

    fetched, written, _, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 16),
        exchange_id=["SSE", "BSE"],
    )

    assert fetched == 0
    assert written == 0
    assert message == "trade_date=2026-04-16 exchanges=SSE,BSE"
    assert service.client.call.call_count == 2
    assert {call.kwargs["params"]["exchange_id"] for call in service.client.call.call_args_list} == {"SSE", "BSE"}


def test_sync_margin_history_range_uses_trade_calendar_and_exchange_fanout(mocker) -> None:
    session = mocker.Mock()
    service = SyncMarginService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = []
    service.dao = mocker.Mock()
    service.dao.trade_calendar.get_open_dates.return_value = [date(2026, 4, 14), date(2026, 4, 15)]
    service.dao.raw_margin.bulk_upsert.return_value = 0
    service.dao.equity_margin.bulk_upsert.return_value = 0

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-04-14",
        end_date="2026-04-15",
        exchange_id="SSE,SZSE",
    )

    assert fetched == 0
    assert written == 0
    assert result_date == date(2026, 4, 15)
    assert message == "trade_dates=2 exchanges=SSE,SZSE"
    assert service.client.call.call_count == 4
    assert service.dao.trade_calendar.get_open_dates.call_args.args == ("SSE", date(2026, 4, 14), date(2026, 4, 15))


def test_sync_margin_requires_explicit_time_params_for_history(mocker) -> None:
    session = mocker.Mock()
    service = SyncMarginService(session)

    with pytest.raises(ValueError, match="sync_history.margin requires explicit time params"):
        service.execute("FULL")


def test_sync_margin_rejects_invalid_exchange_id() -> None:
    with pytest.raises(ValueError, match="exchange_id contains unsupported values"):
        SyncMarginService._normalize_exchange_ids("SSE,UNKNOWN")

