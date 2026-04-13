from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync.sync_biying_equity_daily_service import SyncBiyingEquityDailyService


def test_sync_biying_equity_daily_full_writes_raw_rows(mocker) -> None:
    session = mocker.Mock()
    connector = mocker.Mock()
    connector.call.return_value = [
        {"t": "2026-04-09 00:00:00", "o": 24.33, "h": 24.93, "l": 24.18, "c": 24.38, "v": 943525, "a": 2307474664, "pc": 25.05, "sf": 0},
    ]
    mocker.patch("src.foundation.services.sync.sync_biying_equity_daily_service.create_source_connector", return_value=connector)

    service = SyncBiyingEquityDailyService(session)
    mocker.patch.object(service, "_load_stocks", return_value=[("600602.SH", "云赛智联")])
    mocker.patch.object(service, "_build_windows", return_value=[(date(2026, 4, 3), date(2026, 4, 10))])
    raw_upsert = mocker.patch.object(service.dao.raw_biying_equity_daily_bar, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-04-03",
        end_date="2026-04-10",
    )

    assert fetched == 3  # 1 row * 3 adj types
    assert written == 3
    assert result_date == date(2026, 4, 10)
    assert message == "stocks=1 windows=1"
    assert raw_upsert.call_count == 3
    first_row = raw_upsert.call_args.args[0][0]
    assert first_row["dm"] == "600602.SH"
    assert first_row["trade_date"] == date(2026, 4, 9)
    assert first_row["adj_type"] in {"n", "f", "b"}
    assert first_row["mc"] == "云赛智联"
    assert first_row["suspend_flag"] == 0


def test_sync_biying_equity_daily_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_biying_equity_daily_service.create_source_connector", return_value=mocker.Mock())
    service = SyncBiyingEquityDailyService(session)
    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")
