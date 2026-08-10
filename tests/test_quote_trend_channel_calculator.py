from __future__ import annotations

import hashlib
import importlib
import json
import math
import time
import tracemalloc
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "quote_trend_channel"
INPUT_PATH = FIXTURE_DIR / "000001_sh_daily_input.json"
EXPECTED_PATH = FIXTURE_DIR / "000001_sh_daily_expected_v1.json"
EXPECTED_INPUT_SHA256 = "ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad"
PRICE_QUANTUM = Decimal("0.0001")
CALCULATOR_MODULE = "src.biz.services.quote_trend_channel_calculator"


@dataclass(frozen=True, slots=True)
class SourceRow:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    updated_at: datetime


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_row(
    trade_date: date,
    *,
    open_value: str = "10",
    high: str = "11",
    low: str = "9",
    close: str = "10",
) -> SourceRow:
    return SourceRow(
        trade_date=trade_date,
        open=Decimal(open_value),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        updated_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


def _fixture_source_rows() -> list[SourceRow]:
    payload = _load_json(INPUT_PATH)
    return [
        SourceRow(
            trade_date=date.fromisoformat(row["trade_date"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            updated_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        for row in payload["rows"]
    ]


@pytest.fixture()
def calculator_module() -> ModuleType:
    try:
        return importlib.import_module(CALCULATOR_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == CALCULATOR_MODULE:
            pytest.skip("M1 calculator 尚未实现；M0 只固定金标和测试合同")
        raise


@pytest.fixture()
def calculator(calculator_module: ModuleType) -> Any:
    return calculator_module.TrendChannelCalculator()


def _assert_input_error(
    calculator: Any,
    calculator_module: ModuleType,
    rows: list[SourceRow],
    expected_reason: str,
) -> None:
    with pytest.raises(calculator_module.TrendChannelInputError) as exc_info:
        calculator.calculate(rows)
    assert exc_info.value.reason_code == expected_reason


def test_m0_input_fixture_is_fixed_complete_formal_history() -> None:
    input_payload = _load_json(INPUT_PATH)
    expected_payload = _load_json(EXPECTED_PATH)

    actual_sha256 = hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest()
    assert actual_sha256 == EXPECTED_INPUT_SHA256
    assert expected_payload["input_file_sha256"] == EXPECTED_INPUT_SHA256
    assert input_payload["schema_version"] == 1
    assert input_payload["fixture_key"] == "sse-daily-trend-channel-v1-input"
    assert input_payload["source"]["table"] == "core_serving.index_daily_serving"
    assert input_payload["source"]["ts_code"] == "000001.SH"
    assert input_payload["source"]["period"] == "day"
    assert input_payload["source"]["formal_bars_only"] is True
    assert input_payload["row_count"] == len(input_payload["rows"]) == 1_599
    assert input_payload["first_trade_date"] == "2020-01-02"
    assert input_payload["last_trade_date"] == "2026-08-07"

    dates = [date.fromisoformat(row["trade_date"]) for row in input_payload["rows"]]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))

    for row in input_payload["rows"]:
        open_value = Decimal(row["open"])
        high = Decimal(row["high"])
        low = Decimal(row["low"])
        close = Decimal(row["close"])
        assert all(value.is_finite() and value > 0 for value in (open_value, high, low, close))
        assert low <= min(open_value, close) <= max(open_value, close) <= high


def test_m0_expected_fixture_is_self_consistent_and_covers_required_states() -> None:
    input_payload = _load_json(INPUT_PATH)
    expected_payload = _load_json(EXPECTED_PATH)
    expected_rows = expected_payload["rows"]

    assert expected_payload["schema_version"] == 1
    assert expected_payload["fixture_key"] == "sse-daily-trend-channel-v1-expected"
    assert expected_payload["formula"] == {
        "key": "high-low-ema-hysteresis",
        "version": "sse-daily-trend-channel-v1",
        "short_period": 25,
        "long_period": 90,
        "seed": "first_observation",
        "adjust": False,
        "state_rule": "strict_close_breakout_inside_retention",
        "price_quantum": "0.0001",
        "rounding": "ROUND_HALF_UP",
    }
    assert expected_payload["reference"]["production_calculator_imported"] is False
    assert float(expected_payload["reference"]["max_cross_check_abs_error"]) < 1e-8
    assert expected_payload["row_count"] == len(expected_rows) == input_payload["row_count"]
    assert [row["trade_date"] for row in expected_rows] == [
        row["trade_date"] for row in input_payload["rows"]
    ]
    assert expected_payload["checkpoints"] == {
        "first_bar": "2020-01-02",
        "first_short_up": "2020-01-07",
        "first_short_down": "2020-01-08",
        "first_long_up": "2020-01-07",
        "first_long_down": "2020-01-21",
        "first_divergence": "2020-01-08",
        "screenshot_date": "2026-08-07",
    }

    short_state = "UNKNOWN"
    long_state = "UNKNOWN"
    combined_by_states = {
        ("UP", "UP"): "UP_UP",
        ("UP", "DOWN"): "UP_DOWN",
        ("DOWN", "UP"): "DOWN_UP",
        ("DOWN", "DOWN"): "DOWN_DOWN",
    }
    for source, expected in zip(input_payload["rows"], expected_rows, strict=True):
        close = float(source["close"])
        for channel_name in ("short_channel", "long_channel"):
            channel = expected[channel_name]
            upper_raw = float(channel["upper_raw"])
            lower_raw = float(channel["lower_raw"])
            assert math.isfinite(upper_raw)
            assert math.isfinite(lower_raw)
            assert upper_raw >= lower_raw
            assert Decimal(channel["upper"]) == Decimal(str(upper_raw)).quantize(
                PRICE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            assert Decimal(channel["lower"]) == Decimal(str(lower_raw)).quantize(
                PRICE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            expected_position = "ABOVE" if close > upper_raw else "BELOW" if close < lower_raw else "INSIDE"
            assert channel["position"] == expected_position

        short_position = expected["short_channel"]["position"]
        long_position = expected["long_channel"]["position"]
        short_state = "UP" if short_position == "ABOVE" else "DOWN" if short_position == "BELOW" else short_state
        long_state = "UP" if long_position == "ABOVE" else "DOWN" if long_position == "BELOW" else long_state
        assert expected["short_channel"]["state"] == short_state
        assert expected["long_channel"]["state"] == long_state
        assert expected["combined_state"] == combined_by_states.get(
            (short_state, long_state),
            "UNKNOWN",
        )


def test_m0_screenshot_date_has_explicit_reference_values() -> None:
    expected_payload = _load_json(EXPECTED_PATH)
    screenshot_row = next(
        row for row in expected_payload["rows"] if row["trade_date"] == "2026-08-07"
    )

    assert screenshot_row == {
        "trade_date": "2026-08-07",
        "short_channel": {
            "upper_raw": "3918.6885990959127",
            "lower_raw": "3861.57731211288",
            "upper": "3918.6886",
            "lower": "3861.5773",
            "position": "ABOVE",
            "state": "UP",
        },
        "long_channel": {
            "upper_raw": "4008.259892222497",
            "lower_raw": "3953.5230109681197",
            "upper": "4008.2599",
            "lower": "3953.5230",
            "position": "BELOW",
            "state": "DOWN",
        },
        "combined_state": "UP_DOWN",
    }


def test_first_row_uses_first_observation_seed(calculator: Any) -> None:
    row = _source_row(date(2026, 1, 2), open_value="10", high="11", low="9", close="10")
    result = calculator.calculate([row])

    assert len(result) == 1
    assert result[0].short_channel.upper_raw == 11.0
    assert result[0].short_channel.lower_raw == 9.0
    assert result[0].long_channel.upper_raw == 11.0
    assert result[0].long_channel.lower_raw == 9.0
    assert result[0].short_channel.position == "INSIDE"
    assert result[0].short_channel.state == "UNKNOWN"
    assert result[0].long_channel.state == "UNKNOWN"
    assert result[0].combined_state == "UNKNOWN"


def test_two_rows_match_explicit_25_and_90_recursion(calculator: Any) -> None:
    rows = [
        _source_row(date(2026, 1, 2), high="11", low="9", close="10"),
        _source_row(date(2026, 1, 5), open_value="11", high="12", low="10", close="12"),
    ]
    result = calculator.calculate(rows)

    expected_short_upper = (2.0 / 26.0) * 12.0 + (24.0 / 26.0) * 11.0
    expected_short_lower = (2.0 / 26.0) * 10.0 + (24.0 / 26.0) * 9.0
    expected_long_upper = (2.0 / 91.0) * 12.0 + (89.0 / 91.0) * 11.0
    expected_long_lower = (2.0 / 91.0) * 10.0 + (89.0 / 91.0) * 9.0
    assert result[1].short_channel.upper_raw == pytest.approx(expected_short_upper, abs=1e-8)
    assert result[1].short_channel.lower_raw == pytest.approx(expected_short_lower, abs=1e-8)
    assert result[1].long_channel.upper_raw == pytest.approx(expected_long_upper, abs=1e-8)
    assert result[1].long_channel.lower_raw == pytest.approx(expected_long_lower, abs=1e-8)


def test_breakouts_and_inside_positions_retain_previous_state(calculator: Any) -> None:
    rows = [
        _source_row(date(2026, 1, 2), high="11", low="9", close="10"),
        _source_row(date(2026, 1, 5), open_value="11", high="12", low="10", close="12"),
        _source_row(date(2026, 1, 6), open_value="11", high="12", low="10", close="11"),
        _source_row(date(2026, 1, 7), open_value="8", high="9", low="7", close="7"),
        _source_row(date(2026, 1, 8), open_value="9", high="10", low="8", close="9"),
    ]
    result = calculator.calculate(rows)

    assert (result[1].short_channel.position, result[1].short_channel.state) == ("ABOVE", "UP")
    assert (result[2].short_channel.position, result[2].short_channel.state) == ("INSIDE", "UP")
    assert (result[3].short_channel.position, result[3].short_channel.state) == ("BELOW", "DOWN")
    assert (result[4].short_channel.position, result[4].short_channel.state) == ("INSIDE", "DOWN")
    assert (result[1].long_channel.position, result[1].long_channel.state) == ("ABOVE", "UP")
    assert (result[2].long_channel.position, result[2].long_channel.state) == ("INSIDE", "UP")
    assert (result[3].long_channel.position, result[3].long_channel.state) == ("BELOW", "DOWN")
    assert (result[4].long_channel.position, result[4].long_channel.state) == ("INSIDE", "DOWN")


@pytest.mark.parametrize(
    ("open_value", "high", "low", "close"),
    [
        ("10", "11", "9", "11"),
        ("10", "11", "9", "9"),
    ],
)
def test_close_equal_to_channel_boundary_does_not_switch_state(
    calculator: Any,
    open_value: str,
    high: str,
    low: str,
    close: str,
) -> None:
    result = calculator.calculate(
        [_source_row(date(2026, 1, 2), open_value=open_value, high=high, low=low, close=close)]
    )

    assert result[0].short_channel.position == "INSIDE"
    assert result[0].short_channel.state == "UNKNOWN"
    assert result[0].long_channel.position == "INSIDE"
    assert result[0].long_channel.state == "UNKNOWN"


def test_full_production_result_matches_independent_golden_without_quantized_recursion(
    calculator: Any,
) -> None:
    source_rows = _fixture_source_rows()
    expected_rows = _load_json(EXPECTED_PATH)["rows"]
    actual_rows = calculator.calculate(source_rows)

    assert len(actual_rows) == len(expected_rows)
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        assert actual.trade_date.isoformat() == expected["trade_date"]
        for channel_name in ("short_channel", "long_channel"):
            actual_channel = getattr(actual, channel_name)
            expected_channel = expected[channel_name]
            assert actual_channel.upper_raw == pytest.approx(
                float(expected_channel["upper_raw"]),
                abs=1e-8,
            )
            assert actual_channel.lower_raw == pytest.approx(
                float(expected_channel["lower_raw"]),
                abs=1e-8,
            )
            assert actual_channel.upper == Decimal(expected_channel["upper"])
            assert actual_channel.lower == Decimal(expected_channel["lower"])
            assert actual_channel.position == expected_channel["position"]
            assert actual_channel.state == expected_channel["state"]
        assert actual.combined_state == expected["combined_state"]


def test_future_rows_do_not_change_existing_history_or_limit_window_values(calculator: Any) -> None:
    source_rows = _fixture_source_rows()
    prefix_rows = calculator.calculate(source_rows[:1_200])
    full_rows = calculator.calculate(source_rows)

    assert prefix_rows == full_rows[:1_200]
    assert tuple(full_rows[-500:]) == tuple(calculator.calculate(source_rows)[-500:])


def test_duplicate_date_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
) -> None:
    row = _source_row(date(2026, 1, 2))
    _assert_input_error(calculator, calculator_module, [row, row], "duplicate_trade_date")


def test_descending_date_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
) -> None:
    rows = [_source_row(date(2026, 1, 5)), _source_row(date(2026, 1, 2))]
    _assert_input_error(
        calculator,
        calculator_module,
        rows,
        "trade_date_not_strictly_ascending",
    )


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_missing_ohlc_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
    field: str,
) -> None:
    row = replace(_source_row(date(2026, 1, 2)), **{field: None})
    _assert_input_error(calculator, calculator_module, [row], "missing_ohlc")


@pytest.mark.parametrize("bad_value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_ohlc_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
    bad_value: Decimal,
) -> None:
    row = replace(_source_row(date(2026, 1, 2)), close=bad_value)
    _assert_input_error(calculator, calculator_module, [row], "non_finite_ohlc")


@pytest.mark.parametrize("bad_value", [Decimal("0"), Decimal("-1")])
def test_non_positive_ohlc_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
    bad_value: Decimal,
) -> None:
    row = replace(_source_row(date(2026, 1, 2)), low=bad_value)
    _assert_input_error(calculator, calculator_module, [row], "non_positive_ohlc")


@pytest.mark.parametrize(
    "row",
    [
        _source_row(date(2026, 1, 2), open_value="8", high="11", low="9", close="10"),
        _source_row(date(2026, 1, 2), open_value="10", high="11", low="9", close="12"),
        _source_row(date(2026, 1, 2), open_value="10", high="8", low="9", close="10"),
    ],
)
def test_invalid_ohlc_range_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
    row: SourceRow,
) -> None:
    _assert_input_error(calculator, calculator_module, [row], "invalid_ohlc_range")


def test_more_than_10000_rows_is_rejected(
    calculator: Any,
    calculator_module: ModuleType,
) -> None:
    start = date(1990, 1, 1)
    rows = [_source_row(start + timedelta(days=index)) for index in range(10_001)]
    _assert_input_error(calculator, calculator_module, rows, "source_row_limit_exceeded")


def test_1000_rows_complete_calculation_p95_is_below_10ms(calculator: Any) -> None:
    start = date(2020, 1, 1)
    rows = tuple(_source_row(start + timedelta(days=index)) for index in range(1_000))

    for _ in range(100):
        calculator.calculate(rows)

    samples: list[float] = []
    for _ in range(1_000):
        started = time.perf_counter()
        calculator.calculate(rows)
        samples.append((time.perf_counter() - started) * 1_000.0)

    ordered = sorted(samples)
    p95_ms = ordered[949]
    assert p95_ms < 10.0, {
        "median_ms": ordered[len(ordered) // 2],
        "p95_ms": p95_ms,
        "max_ms": ordered[-1],
    }


def test_10000_row_result_peak_memory_is_below_10mib(calculator: Any) -> None:
    start = date(1990, 1, 1)
    rows = tuple(_source_row(start + timedelta(days=index)) for index in range(10_000))

    tracemalloc.start()
    try:
        result = calculator.calculate(rows)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(result) == 10_000
    assert peak_bytes < 10 * 1024 * 1024
