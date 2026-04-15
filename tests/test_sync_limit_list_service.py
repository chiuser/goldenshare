from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_limit_list_service import SyncLimitListService, build_limit_list_params


def test_build_limit_list_params_supports_incremental_filters() -> None:
    params = build_limit_list_params(
        "INCREMENTAL",
        trade_date=date(2026, 4, 3),
        limit_type="U",
        exchange="SH",
    )

    assert params == {
        "trade_date": "20260403",
        "limit_type": "U",
        "exchange": "SH",
    }


def test_build_limit_list_params_supports_full_range_filters() -> None:
    params = build_limit_list_params(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
        limit_type="D",
        exchange="BJ",
    )

    assert params == {
        "start_date": "20260301",
        "end_date": "20260331",
        "limit_type": "D",
        "exchange": "BJ",
    }


def test_sync_limit_list_execute_fans_out_when_filters_not_provided(mocker) -> None:
    session = mocker.Mock()
    service = SyncLimitListService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = []
    service.dao.raw_limit_list = mocker.Mock()
    service.dao.equity_limit_list = mocker.Mock()
    service.dao.equity_limit_list.bulk_upsert.return_value = 0

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 3))

    assert fetched == 0
    assert written == 0
    assert result_date == date(2026, 4, 3)
    assert message is None
    assert service.client.call.call_count == 9

    called_pairs = {
        (call.kwargs["params"]["limit_type"], call.kwargs["params"]["exchange"])
        for call in service.client.call.call_args_list
    }
    assert called_pairs == {
        ("U", "SH"),
        ("U", "SZ"),
        ("U", "BJ"),
        ("D", "SH"),
        ("D", "SZ"),
        ("D", "BJ"),
        ("Z", "SH"),
        ("Z", "SZ"),
        ("Z", "BJ"),
    }


def test_sync_limit_list_execute_calls_once_when_single_filters_given(mocker) -> None:
    session = mocker.Mock()
    service = SyncLimitListService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = []
    service.dao.raw_limit_list = mocker.Mock()
    service.dao.equity_limit_list = mocker.Mock()
    service.dao.equity_limit_list.bulk_upsert.return_value = 0

    service.execute("INCREMENTAL", trade_date=date(2026, 4, 3), limit_type="U", exchange="SH")

    assert service.client.call.call_count == 1
    assert service.client.call.call_args.kwargs["params"] == {
        "trade_date": "20260403",
        "limit_type": "U",
        "exchange": "SH",
    }
