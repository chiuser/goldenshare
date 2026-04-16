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
    first_kdj_row = kdj_upsert.call_args.args[0][0]
    assert first_kdj_row["rsv"] is not None
    assert first_kdj_row["is_valid"] is False
    first_rsi_row = rsi_upsert.call_args.args[0][0]
    assert first_rsi_row["is_valid"] is False
    first_kdj_std_row = kdj_std_upsert.call_args.args[0][0]
    assert first_kdj_std_row["is_valid"] is False
    first_rsi_std_row = rsi_std_upsert.call_args.args[0][0]
    assert first_rsi_std_row["is_valid"] is False
    assert kdj_upsert.call_count == 1
    assert rsi_upsert.call_count == 1
    assert macd_std_upsert.call_count == 1
    assert kdj_std_upsert.call_count == 1
    assert rsi_std_upsert.call_count == 1
    first_state_row = state_upsert.call_args.args[0][0]
    assert first_state_row["source_key"] == "tushare"
    assert first_state_row["state_json"]["bar_count"] == 2
    kdj_state_row = next(row for row in state_upsert.call_args.args[0] if row["indicator_name"] == "kdj")
    assert "last_adj_factor" in kdj_state_row["state_json"]
    rsi_state_row = next(row for row in state_upsert.call_args.args[0] if row["indicator_name"] == "rsi")
    assert "last_adj_factor" in rsi_state_row["state_json"]
    first_macd_std_row = macd_std_upsert.call_args.args[0][0]
    assert first_macd_std_row["source_key"] == "tushare"
    assert service._load_daily_rows.call_count == 1
    assert service._load_factor_map.call_count == 1


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


def test_incremental_fallback_when_state_trade_date_not_aligned(mocker) -> None:
    service = SyncEquityIndicatorsService(mocker.Mock())
    macd_state = SimpleNamespace(
        last_trade_date=date(2026, 4, 8),
        state_json={"bar_count": 100, "ema_fast": 1.0, "ema_slow": 1.0, "dea": 0.1, "last_adj_factor": 1.0},
    )
    kdj_state = SimpleNamespace(
        last_trade_date=date(2026, 4, 7),
        state_json={"bar_count": 100, "k": 50.0, "d": 50.0, "last_adj_factor": 1.0},
    )
    rsi_state = SimpleNamespace(
        last_trade_date=date(2026, 4, 8),
        state_json={
            "bar_count": 100,
            "period_6": {"avg_gain": 1.0, "avg_loss": 0.5, "prev_close": 10.0},
            "period_12": {"avg_gain": 1.0, "avg_loss": 0.5, "prev_close": 10.0},
            "period_24": {"avg_gain": 1.0, "avg_loss": 0.5, "prev_close": 10.0},
            "last_adj_factor": 1.0,
        },
    )
    load_state = mocker.patch.object(
        service,
        "_load_indicator_state",
        side_effect=[macd_state, kdj_state, rsi_state],
    )

    payload = service._build_adjustment_incremental(
        ts_code="000001.SZ",
        start_date=date(2020, 1, 1),
        end_date=date(2026, 4, 8),
        source_key="tushare",
        adjustment="forward",
    )

    assert payload is None
    assert load_state.call_count == 3
