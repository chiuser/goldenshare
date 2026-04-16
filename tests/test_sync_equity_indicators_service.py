from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.services.sync.sync_equity_indicators_service import SyncEquityIndicatorsService


def test_sync_equity_indicators_incremental_executes_for_single_day(mocker) -> None:
    service = SyncEquityIndicatorsService(mocker.Mock())
    mocker.patch.object(service, "_load_ts_codes", return_value=["000001.SZ"])
    mocker.patch.object(service, "_load_trade_bounds", return_value=(date(2020, 1, 1), date(2026, 4, 8)))
    mocker.patch.object(service, "_ensure_meta_rows")
    mocker.patch.object(service, "_build_for_ts_code", return_value=(2, 6))

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        ts_code="000001.SZ",
    )

    assert fetched == 2
    assert written == 6
    assert result_date == date(2026, 4, 8)
    assert message == "stocks=1 bars=2"


def test_build_for_ts_code_generates_rows_for_forward_and_backward(mocker) -> None:
    service = SyncEquityIndicatorsService(mocker.Mock())
    mocker.patch.object(
        service,
        "_load_daily_rows",
        return_value=[
            SimpleNamespace(
                trade_date=date(2026, 4, 7),
                open=Decimal("10.0000"),
                high=Decimal("10.5000"),
                low=Decimal("9.8000"),
                close=Decimal("10.2000"),
            ),
            SimpleNamespace(
                trade_date=date(2026, 4, 8),
                open=Decimal("10.2000"),
                high=Decimal("10.6000"),
                low=Decimal("10.0000"),
                close=Decimal("10.4000"),
            ),
        ],
    )
    mocker.patch.object(
        service,
        "_load_factor_map",
        return_value={
            date(2026, 4, 7): Decimal("1.00000000"),
            date(2026, 4, 8): Decimal("1.00000000"),
        },
    )
    mocker.patch.object(service, "_load_anchor", return_value=Decimal("1.00000000"))
    state_upsert = mocker.patch.object(service.dao.indicator_state, "bulk_upsert", return_value=6)
    macd_upsert = mocker.patch.object(service.dao.indicator_macd, "bulk_upsert", return_value=4)
    kdj_upsert = mocker.patch.object(service.dao.indicator_kdj, "bulk_upsert", return_value=4)
    rsi_upsert = mocker.patch.object(service.dao.indicator_rsi, "bulk_upsert", return_value=4)
    macd_std_upsert = mocker.patch.object(service.dao.indicator_macd_std, "bulk_upsert", return_value=4)
    kdj_std_upsert = mocker.patch.object(service.dao.indicator_kdj_std, "bulk_upsert", return_value=4)
    rsi_std_upsert = mocker.patch.object(service.dao.indicator_rsi_std, "bulk_upsert", return_value=4)

    fetched, written = service._build_for_ts_code(
        "000001.SZ",
        start_date=date(2026, 4, 7),
        end_date=date(2026, 4, 8),
        source_key="tushare",
    )

    assert fetched == 4  # 2 days x 2 adjustments
    assert written == 12
    assert state_upsert.call_count == 1
    first_macd_row = macd_upsert.call_args.args[0][0]
    assert first_macd_row["adjustment"] in {"forward", "backward"}
    assert first_macd_row["version"] == 1
    assert first_macd_row["trade_date"] == date(2026, 4, 7)
    assert first_macd_row["is_valid"] is False
    assert kdj_upsert.call_count == 1
    assert rsi_upsert.call_count == 1
    assert macd_std_upsert.call_count == 1
    assert kdj_std_upsert.call_count == 1
    assert rsi_std_upsert.call_count == 1
    first_state_row = state_upsert.call_args.args[0][0]
    assert first_state_row["source_key"] == "tushare"
    assert first_state_row["state_json"]["bar_count"] == 2
    first_macd_std_row = macd_std_upsert.call_args.args[0][0]
    assert first_macd_std_row["source_key"] == "tushare"


def test_load_factor_map_uses_adj_factor_by_default(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value.all.return_value = []
    service = SyncEquityIndicatorsService(session)

    service._load_factor_map(
        ts_code="000001.SZ",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 8),
    )

    stmt = session.execute.call_args.args[0]
    assert "core.equity_adj_factor" in str(stmt)
