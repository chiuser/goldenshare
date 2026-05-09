from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.services.indicators import calculate_macd


def test_macd_calculator_matches_formula_fixture() -> None:
    rows = [
        _bar("2026-04-24 10:00:00", 10.0),
        _bar("2026-04-24 10:30:00", 11.0),
        _bar("2026-04-24 11:00:00", 12.0),
    ]

    result = calculate_macd(rows)
    expected = _manual_macd([10.0, 11.0, 12.0])

    assert len(result.rows) == 3
    assert result.final_state is not None
    assert result.final_state.ts_code == "600000.SH"
    assert result.final_state.freq == 30
    assert result.final_state.last_trade_time == datetime(2026, 4, 24, 11, 0)
    for actual, expected_row in zip(result.rows, expected, strict=True):
        assert actual["dif"] == pytest.approx(expected_row["dif"])
        assert actual["dea"] == pytest.approx(expected_row["dea"])
        assert actual["macd_bar"] == pytest.approx(expected_row["macd_bar"])
        assert actual["params_key"] == "12_26_9"
        assert actual["indicator_version"] == 1


def test_macd_incremental_result_matches_full_result_across_days() -> None:
    rows = [
        _bar("2026-04-24 10:00:00", 10.0),
        _bar("2026-04-24 10:30:00", 10.5),
        _bar("2026-04-27 10:00:00", 11.0),
        _bar("2026-04-27 10:30:00", 10.8),
    ]

    full_result = calculate_macd(rows)
    first_day_result = calculate_macd(rows[:2])
    incremental_result = calculate_macd(rows[2:], initial_state=first_day_result.final_state)

    combined_rows = first_day_result.rows + incremental_result.rows
    assert [row["trade_time"] for row in combined_rows] == [row["trade_time"] for row in full_result.rows]
    for actual, expected in zip(combined_rows, full_result.rows, strict=True):
        assert actual["dif"] == pytest.approx(expected["dif"])
        assert actual["dea"] == pytest.approx(expected["dea"])
        assert actual["macd_bar"] == pytest.approx(expected["macd_bar"])
    assert incremental_result.rows[0]["trade_time"] == datetime(2026, 4, 27, 10, 0)
    assert incremental_result.rows[0]["macd_bar"] != 0.0


def test_macd_calculator_rejects_mixed_streams() -> None:
    with pytest.raises(ValueError, match="一个 ts_code \\+ freq"):
        calculate_macd(
            [
                _bar("2026-04-24 10:00:00", 10.0, ts_code="600000.SH"),
                _bar("2026-04-24 10:30:00", 10.1, ts_code="000001.SZ"),
            ]
        )


def _bar(trade_time: str, close: float, *, ts_code: str = "600000.SH", freq: int = 30) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": datetime.fromisoformat(trade_time),
        "close": close,
    }


def _manual_macd(closes: list[float]) -> list[dict[str, float]]:
    alpha_fast = 2.0 / (12 + 1)
    alpha_slow = 2.0 / (26 + 1)
    alpha_signal = 2.0 / (9 + 1)
    ema_fast: float | None = None
    ema_slow: float | None = None
    dea: float | None = None
    rows: list[dict[str, float]] = []
    for close in closes:
        if ema_fast is None or ema_slow is None or dea is None:
            ema_fast = close
            ema_slow = close
            dif = 0.0
            dea = 0.0
        else:
            ema_fast = ema_fast * (1.0 - alpha_fast) + close * alpha_fast
            ema_slow = ema_slow * (1.0 - alpha_slow) + close * alpha_slow
            dif = ema_fast - ema_slow
            dea = dea * (1.0 - alpha_signal) + dif * alpha_signal
        rows.append({"dif": dif, "dea": dea, "macd_bar": 2.0 * (dif - dea)})
    return rows
