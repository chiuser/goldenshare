from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.services.sync.sync_equity_price_restore_factor_service import SyncEquityPriceRestoreFactorService


def test_sync_equity_price_restore_factor_incremental_requires_trade_date(mocker) -> None:
    service = SyncEquityPriceRestoreFactorService(mocker.Mock())
    try:
        service.execute("INCREMENTAL")
        assert False, "expected ValueError for missing trade_date"
    except ValueError as exc:
        assert "trade_date is required" in str(exc)


def test_sync_equity_price_restore_factor_incremental_executes_for_single_day(mocker) -> None:
    service = SyncEquityPriceRestoreFactorService(mocker.Mock())
    mocker.patch.object(service, "_load_ts_codes", return_value=["000001.SZ"])
    mocker.patch.object(service, "_build_for_ts_code", return_value=(1, 1, 1))

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 7),
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 7)
    assert message == "stocks=1 days=1 events=1"


def test_build_for_ts_code_applies_event_factors_in_order(mocker) -> None:
    session = mocker.Mock()
    service = SyncEquityPriceRestoreFactorService(session)
    mocker.patch.object(
        session,
        "execute",
        return_value=[
            SimpleNamespace(trade_date=date(2026, 4, 1), close=Decimal("10.0000")),
            SimpleNamespace(trade_date=date(2026, 4, 2), close=Decimal("11.0000")),
        ],
    )
    mocker.patch.object(service, "_factor_before", return_value=Decimal("1.00000000"))
    mocker.patch.object(
        service,
        "_load_event_factors_by_trade_date",
        return_value={
            date(2026, 4, 2): [
                SimpleNamespace(ex_date=date(2026, 4, 2), single_factor=Decimal("0.50000000")),
            ]
        },
    )
    upsert = mocker.patch.object(service.dao.equity_price_restore_factor, "bulk_upsert", return_value=2)

    fetched, written, events = service._build_for_ts_code(
        "000001.SZ",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
    )

    assert fetched == 2
    assert written == 2
    assert events == 1
    rows = upsert.call_args.args[0]
    assert rows[0]["trade_date"] == date(2026, 4, 1)
    assert rows[0]["cum_factor"] == Decimal("1.00000000")
    assert rows[1]["trade_date"] == date(2026, 4, 2)
    assert rows[1]["cum_factor"] == Decimal("0.50000000")
    assert rows[1]["single_factor"] == Decimal("0.50000000")
    assert rows[1]["event_applied"] is True
