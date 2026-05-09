from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.services.indicators import IndicatorByDateWriter, MacdState, MacdStateStore, calculate_macd
from lake_console.backend.app.services.parquet_writer import read_parquet_rows


def test_macd_state_store_missing_state_requires_bootstrap(tmp_path) -> None:
    store = MacdStateStore(lake_root=tmp_path)

    assert store.get_state(ts_code="600000.SH", freq=30) is None
    assert store.needs_bootstrap(ts_code="600000.SH", freq=30) is True


def test_macd_state_store_writes_after_indicator_result_success(tmp_path) -> None:
    result = calculate_macd(
        [
            _bar("2026-04-24 10:00:00", 10.0),
            _bar("2026-04-24 10:30:00", 10.5),
        ]
    )
    assert result.final_state is not None
    result_summary = IndicatorByDateWriter(lake_root=tmp_path).write_rows(
        result.rows,
        indicator="macd",
        params_key="12_26_9",
        freq=30,
        run_id="test-result-success",
    )

    summary = MacdStateStore(lake_root=tmp_path).replace_states_after_result_write(
        [result.final_state],
        result_summary=result_summary,
        run_id="test-state-success",
    )

    loaded_state = MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30)
    state_rows = read_parquet_rows(tmp_path / "manifest" / "indicator_state" / "stk_mins_macd" / "params_key=12_26_9" / "state.parquet")
    assert summary["operation"] == "replace_macd_state"
    assert summary["state_count"] == 1
    assert loaded_state == result.final_state
    assert state_rows[0]["indicator_key"] == "macd"
    assert state_rows[0]["source_dataset_key"] == "stk_mins"
    assert state_rows[0]["source_layer"] == "raw_tushare"
    assert state_rows[0]["state_version"] == 1
    assert state_rows[0]["updated_at"] is not None
    assert not (tmp_path / "_tmp" / "test-state-success" / "manifest").exists()


def test_macd_state_store_rejects_state_advance_without_result_success(tmp_path) -> None:
    store = MacdStateStore(lake_root=tmp_path)
    state = MacdState(
        ts_code="600000.SH",
        freq=30,
        last_trade_time=datetime(2026, 4, 24, 10, 30),
        ema_fast=10.1,
        ema_slow=10.05,
        dea=0.02,
    )

    with pytest.raises(ValueError, match="by_date 写入成功后"):
        store.replace_states_after_result_write(
            [state],
            result_summary={"operation": "manual_state_write", "indicator": "macd", "written_rows": 1, "partition_count": 1},
            run_id="test-state-reject",
        )

    assert store.get_state(ts_code="600000.SH", freq=30) is None


def test_macd_state_store_full_replace_removes_omitted_state(tmp_path) -> None:
    store = MacdStateStore(lake_root=tmp_path)
    result_summary = {
        "operation": "write_indicator_by_date",
        "indicator": "macd",
        "params_key": "12_26_9",
        "freq": 30,
        "run_id": "result",
        "written_rows": 2,
        "partition_count": 1,
    }
    first_state = MacdState(
        ts_code="600000.SH",
        freq=30,
        last_trade_time=datetime(2026, 4, 24, 10, 30),
        ema_fast=10.1,
        ema_slow=10.05,
        dea=0.02,
    )
    second_state = MacdState(
        ts_code="000001.SZ",
        freq=30,
        last_trade_time=datetime(2026, 4, 24, 10, 30),
        ema_fast=8.1,
        ema_slow=8.05,
        dea=0.01,
    )

    store.replace_states_after_result_write(
        [first_state, second_state],
        result_summary=result_summary,
        run_id="test-state-two",
    )
    store.replace_states_after_result_write(
        [first_state],
        result_summary=result_summary,
        run_id="test-state-one",
    )

    states = store.load_states()
    assert set(states) == {("600000.SH", 30)}
    assert states[("600000.SH", 30)] == first_state


def _bar(trade_time: str, close: float, *, freq: int = 30) -> dict[str, object]:
    return {
        "ts_code": "600000.SH",
        "freq": freq,
        "trade_time": datetime.fromisoformat(trade_time),
        "close": close,
    }
