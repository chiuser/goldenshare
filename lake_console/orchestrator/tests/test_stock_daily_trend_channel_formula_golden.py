from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.stock_daily_trend_channel import (
    DAILY_SOURCE_ROW_HARD_LIMIT,
    FORMULA_KEY,
    FORMULA_VERSION,
    LONG_PERIOD,
    SEGMENT_TRADE_DAY_LIMIT,
    SHORT_PERIOD,
    build_stock_daily_trend_channel_daily_sql,
    build_stock_daily_trend_channel_history_segment_sql,
    build_stock_daily_trend_channel_repair_segment_sql,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "quote_trend_channel"
INPUT_PATH = FIXTURE_ROOT / "000001_sh_daily_input.json"
EXPECTED_PATH = FIXTURE_ROOT / "000001_sh_daily_expected_v1.json"
SOURCE_CODE = "000001.SH"

FormulaBuilder = Callable[..., str]


def _load_fixture_rows() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    input_payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    expected_payload = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return input_payload["rows"], expected_payload["rows"]


def _replace_source_rows(
    connection: duckdb.DuckDBPyConnection,
    rows: list[dict[str, str]],
    *,
    codes: tuple[str, ...] = (SOURCE_CODE,),
) -> None:
    connection.execute("DROP TABLE IF EXISTS trend_source")
    connection.execute(
        """
        CREATE TEMP TABLE trend_source(
          ts_code VARCHAR,
          trade_date DATE,
          open DOUBLE,
          high DOUBLE,
          low DOUBLE,
          close DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO trend_source VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                code,
                date.fromisoformat(row["trade_date"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
            )
            for row in rows
            for code in codes
        ],
    )


def _replace_seed_row(
    connection: duckdb.DuckDBPyConnection,
    seed_by_code: dict[str, tuple[float, float, str, float, float, str]],
) -> None:
    connection.execute("DROP TABLE IF EXISTS trend_seed")
    connection.execute(
        """
        CREATE TEMP TABLE trend_seed(
          ts_code VARCHAR,
          short_upper_raw DOUBLE,
          short_lower_raw DOUBLE,
          short_state VARCHAR,
          long_upper_raw DOUBLE,
          long_lower_raw DOUBLE,
          long_state VARCHAR
        )
        """
    )
    if seed_by_code:
        connection.executemany(
            "INSERT INTO trend_seed VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(code, *seed) for code, seed in sorted(seed_by_code.items())],
        )


def _seed_from_rows(rows: list[tuple]) -> dict[str, tuple[float, float, str, float, float, str]]:
    latest_by_code: dict[str, tuple] = {}
    for row in rows:
        latest_by_code[row[0]] = row
    return {
        code: (row[6], row[7], row[11], row[12], row[13], row[17])
        for code, row in latest_by_code.items()
    }


def _execute_segmented(
    source_rows: list[dict[str, str]],
    *,
    builder: FormulaBuilder,
    segment_size: int,
) -> list[tuple]:
    connection = duckdb.connect()
    actual_rows: list[tuple] = []
    seed_by_code: dict[str, tuple[float, float, str, float, float, str]] = {}
    try:
        for segment_start in range(0, len(source_rows), segment_size):
            segment_rows = source_rows[segment_start : segment_start + segment_size]
            _replace_source_rows(connection, segment_rows)
            _replace_seed_row(connection, seed_by_code)
            sql = builder(
                "trend_source",
                segment_trade_day_count=len(segment_rows),
                previous_state_relation=("trend_seed" if seed_by_code else None),
            )
            segment_output = connection.execute(sql).fetchall()
            actual_rows.extend(segment_output)
            seed_by_code = _seed_from_rows(segment_output)
    finally:
        connection.close()
    return actual_rows


def _assert_matches_literal_expected(
    actual_rows: list[tuple],
    expected_rows: list[dict[str, object]],
) -> None:
    assert len(actual_rows) == len(expected_rows)
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        short = expected["short_channel"]
        long = expected["long_channel"]
        assert isinstance(short, dict)
        assert isinstance(long, dict)
        assert actual[0] == SOURCE_CODE
        assert actual[1].isoformat() == expected["trade_date"]
        assert actual[6] == pytest.approx(float(short["upper_raw"]), abs=1e-10)
        assert actual[7] == pytest.approx(float(short["lower_raw"]), abs=1e-10)
        assert Decimal(str(actual[8])) == Decimal(short["upper"])
        assert Decimal(str(actual[9])) == Decimal(short["lower"])
        assert actual[10] == short["position"]
        assert actual[11] == short["state"]
        assert actual[12] == pytest.approx(float(long["upper_raw"]), abs=1e-10)
        assert actual[13] == pytest.approx(float(long["lower_raw"]), abs=1e-10)
        assert Decimal(str(actual[14])) == Decimal(long["upper"])
        assert Decimal(str(actual[15])) == Decimal(long["lower"])
        assert actual[16] == long["position"]
        assert actual[17] == long["state"]
        assert actual[18] == expected["combined_state"]
        assert actual[19] == FORMULA_VERSION


def _assert_formula_paths_equivalent(
    actual_rows: list[tuple], expected_rows: list[tuple]
) -> None:
    assert len(actual_rows) == len(expected_rows)
    raw_value_indexes = (6, 7, 12, 13)
    exact_value_indexes = tuple(
        index for index in range(20) if index not in raw_value_indexes
    )
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        for index in raw_value_indexes:
            assert actual[index] == pytest.approx(expected[index], abs=1e-10)
        assert tuple(actual[index] for index in exact_value_indexes) == tuple(
            expected[index] for index in exact_value_indexes
        )


def test_formula_constants_are_frozen() -> None:
    assert FORMULA_KEY == "high-low-ema-hysteresis"
    assert FORMULA_VERSION == "stock-daily-trend-channel-v1"
    assert SHORT_PERIOD == 25
    assert LONG_PERIOD == 90
    assert SEGMENT_TRADE_DAY_LIMIT == 250
    assert DAILY_SOURCE_ROW_HARD_LIMIT == 10_000


def test_history_segments_match_the_independent_index_literal_fixture() -> None:
    source_rows, expected_rows = _load_fixture_rows()

    actual_rows = _execute_segmented(
        source_rows,
        builder=build_stock_daily_trend_channel_history_segment_sql,
        segment_size=SEGMENT_TRADE_DAY_LIMIT,
    )

    _assert_matches_literal_expected(actual_rows, expected_rows)
    for boundary_index in (248, 249, 250):
        assert actual_rows[boundary_index][1].isoformat() == expected_rows[boundary_index][
            "trade_date"
        ]
    assert {row[11] for row in actual_rows} == {"UNKNOWN", "UP", "DOWN"}
    assert {row[17] for row in actual_rows} == {"UNKNOWN", "UP", "DOWN"}
    assert {row[18] for row in actual_rows} == {
        "UNKNOWN",
        "UP_UP",
        "UP_DOWN",
        "DOWN_UP",
        "DOWN_DOWN",
    }


def test_daily_history_and_repair_paths_are_value_identical() -> None:
    source_rows, expected_rows = _load_fixture_rows()
    source_rows = source_rows[:251]
    expected_rows = expected_rows[:251]

    history_rows = _execute_segmented(
        source_rows,
        builder=build_stock_daily_trend_channel_history_segment_sql,
        segment_size=250,
    )
    repair_rows = _execute_segmented(
        source_rows,
        builder=build_stock_daily_trend_channel_repair_segment_sql,
        segment_size=249,
    )

    connection = duckdb.connect()
    daily_rows: list[tuple] = []
    seed_by_code: dict[str, tuple[float, float, str, float, float, str]] = {}
    try:
        for source_row in source_rows:
            _replace_source_rows(connection, [source_row])
            _replace_seed_row(connection, seed_by_code)
            sql = build_stock_daily_trend_channel_daily_sql(
                "trend_source",
                previous_state_relation=("trend_seed" if seed_by_code else None),
            )
            output = connection.execute(sql).fetchall()
            daily_rows.extend(output)
            seed_by_code = _seed_from_rows(output)
    finally:
        connection.close()

    _assert_matches_literal_expected(history_rows, expected_rows)
    _assert_matches_literal_expected(repair_rows, expected_rows)
    _assert_matches_literal_expected(daily_rows, expected_rows)
    _assert_formula_paths_equivalent(repair_rows, history_rows)
    _assert_formula_paths_equivalent(daily_rows, history_rows)


def test_interleaved_stock_codes_are_calculated_independently() -> None:
    source_rows, _ = _load_fixture_rows()
    connection = duckdb.connect()
    try:
        _replace_source_rows(
            connection,
            source_rows[:8],
            codes=("000001.SZ", "600000.SH"),
        )
        output = connection.execute(
            build_stock_daily_trend_channel_history_segment_sql(
                "trend_source",
                segment_trade_day_count=8,
            )
        ).fetchall()
    finally:
        connection.close()

    first_stock = [row[1:] for row in output if row[0] == "000001.SZ"]
    second_stock = [row[1:] for row in output if row[0] == "600000.SH"]
    assert first_stock == second_stock


def test_equality_is_inside_and_decimal_rounding_is_half_up() -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TEMP TABLE trend_source AS
            SELECT * FROM (VALUES
              ('000001.SZ', DATE '2026-01-02', 1.20000, 1.23445, 1.11115, 1.23445),
              ('600000.SH', DATE '2026-01-02', 1.20000, 1.23445, 1.11115, 1.11115)
            ) AS source(ts_code, trade_date, open, high, low, close)
            """
        )
        output = connection.execute(
            build_stock_daily_trend_channel_daily_sql("trend_source")
        ).fetchall()
    finally:
        connection.close()

    assert [row[10] for row in output] == ["INSIDE", "INSIDE"]
    assert [row[11] for row in output] == ["UNKNOWN", "UNKNOWN"]
    assert Decimal(str(output[0][8])) == Decimal("1.2345")
    assert Decimal(str(output[0][9])) == Decimal("1.1112")


@pytest.mark.parametrize("segment_size", [0, 251])
def test_segment_builder_rejects_out_of_contract_sizes(segment_size: int) -> None:
    with pytest.raises(ValueError):
        build_stock_daily_trend_channel_history_segment_sql(
            "trend_source",
            segment_trade_day_count=segment_size,
        )


@pytest.mark.parametrize(
    "relation",
    ["", "trend source", "trend_source; DROP TABLE x", "a/b", 'a"b'],
)
def test_formula_builder_rejects_unsafe_relation_identifiers(relation: str) -> None:
    with pytest.raises(ValueError):
        build_stock_daily_trend_channel_daily_sql(relation)
