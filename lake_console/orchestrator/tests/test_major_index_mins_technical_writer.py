from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

import orchestrator.defs.io.major_index_mins_technical_writer as writer_module
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    MajorIndexMinsTechnicalValidationError,
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_staging_path,
    gold_major_index_mins_technical_state_path,
    gold_major_index_mins_technical_state_staging_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    expected_major_index_mins_technical_codes,
)

DAY_1 = "2009-01-05"
DAY_2 = "2009-01-06"
FREQ = 120


def _write_silver_partition(
    root: Path,
    *,
    trade_date: str,
    codes: tuple[str, ...],
    first_close: float,
) -> Path:
    path = silver_major_index_mins_path(root, f"{FREQ}min", trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for code_index, code in enumerate(codes):
        code_base = first_close + code_index
        for bar_index, trade_time in enumerate(("11:30:00", "15:00:00")):
            close = code_base + bar_index * 3.0
            rows.append(
                (
                    code,
                    f"{FREQ}min",
                    f"{trade_date} {trade_time}",
                    close + 1.0,
                    close - 1.0,
                    close,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE silver_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO silver_rows VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM silver_rows ORDER BY ts_code, trade_time",
                path,
            )
        )
    return path


def _read_rows(
    path: Path,
    *,
    code: str,
    order_by: str = "trade_time",
) -> list[dict[str, object]]:
    with duckdb.connect(":memory:") as connection:
        cursor = connection.execute(
            f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} "
            f"WHERE ts_code = ? ORDER BY {order_by}",
            [code],
        )
        columns = tuple(description[0] for description in cursor.description)
        rows = cursor.fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _write_day_1_and_day_2_sources(root: Path) -> None:
    _write_silver_partition(
        root,
        trade_date=DAY_1,
        codes=expected_major_index_mins_technical_codes(DAY_1),
        first_close=10.0,
    )
    _write_silver_partition(
        root,
        trade_date=DAY_2,
        codes=expected_major_index_mins_technical_codes(DAY_2),
        first_close=14.0,
    )


def test_writer_seeds_first_available_date_then_requires_continuity(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_day_1_and_day_2_sources(lake_root)
    expected_dates = (DAY_1, DAY_2)

    day_1 = write_major_index_mins_technical_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        freq=FREQ,
        partition_key=DAY_1,
        run_id="day-1",
        expected_trade_dates=expected_dates,
    )
    day_2 = write_major_index_mins_technical_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        freq=FREQ,
        partition_key=DAY_2,
        run_id="day-2",
        expected_trade_dates=expected_dates,
    )

    assert day_1.seed_codes == expected_major_index_mins_technical_codes(DAY_1)
    assert day_2.seed_codes == ()
    assert "000001.SH" in day_2.continuing_codes
    continuing_rows = _read_rows(day_2.technical_path, code="000001.SH")
    assert [row["observation_count"] for row in continuing_rows] == [3, 4]
    assert day_2.state_row_count == len(
        expected_major_index_mins_technical_codes(DAY_2)
    )
    assert day_2.technical_row_count == day_2.input_row_count


def test_writer_formula_and_state_match_literal_first_day_values(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_silver_partition(
        lake_root,
        trade_date=DAY_1,
        codes=expected_major_index_mins_technical_codes(DAY_1),
        first_close=10.0,
    )

    result = write_major_index_mins_technical_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        freq=FREQ,
        partition_key=DAY_1,
        run_id="golden",
        expected_trade_dates=(DAY_1,),
    )

    technical = _read_rows(result.technical_path, code="000001.SH")
    state = _read_rows(
        result.state_path,
        code="000001.SH",
        order_by="last_trade_time",
    )
    assert technical[0]["macd_dif"] == pytest.approx(0.0)
    assert technical[0]["macd_dea"] == pytest.approx(0.0)
    assert technical[0]["macd"] == pytest.approx(0.0)
    assert technical[0]["kdj_k"] == pytest.approx(50.0)
    assert technical[0]["kdj_d"] == pytest.approx(50.0)
    assert technical[0]["kdj_j"] == pytest.approx(50.0)
    assert technical[1]["macd_dif"] == pytest.approx(0.23931623931623935)
    assert technical[1]["macd_dea"] == pytest.approx(0.04786324786324787)
    assert technical[1]["macd"] == pytest.approx(0.38290598290598296)
    assert technical[1]["kdj_k"] == pytest.approx(60.0)
    assert technical[1]["kdj_d"] == pytest.approx(53.333333333333336)
    assert technical[1]["kdj_j"] == pytest.approx(73.33333333333333)
    assert state[0]["macd_ema_fast"] == pytest.approx(10.461538461538462)
    assert state[0]["macd_ema_slow"] == pytest.approx(10.222222222222221)
    assert state[0]["macd_dea"] == pytest.approx(0.04786324786324787)
    assert state[0]["kdj_k"] == pytest.approx(60.0)
    assert state[0]["kdj_d"] == pytest.approx(53.333333333333336)


def test_writer_rejects_missing_previous_state_for_continuing_codes(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_day_1_and_day_2_sources(lake_root)
    day_1_technical = gold_major_index_mins_technical_path(
        lake_root, FREQ, DAY_1
    )
    day_1_state = gold_major_index_mins_technical_state_path(
        lake_root, FREQ, DAY_1
    )
    assert not day_1_technical.exists()
    assert not day_1_state.exists()

    with pytest.raises(
        MajorIndexMinsTechnicalValidationError,
        match="strict previous-date input is missing",
    ):
        write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=DAY_2,
            run_id="missing-previous",
            expected_trade_dates=(DAY_1, DAY_2),
        )


def test_writer_rejects_later_partition_without_previous_expected_date(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_silver_partition(
        lake_root,
        trade_date=DAY_2,
        codes=expected_major_index_mins_technical_codes(DAY_2),
        first_close=10.0,
    )

    with pytest.raises(
        MajorIndexMinsTechnicalValidationError,
        match="strict previous expected trade date is unavailable",
    ):
        write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=DAY_2,
            run_id="missing-previous-date",
            expected_trade_dates=(DAY_2,),
        )


def test_writer_refuses_existing_paired_target(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_silver_partition(
        lake_root,
        trade_date=DAY_1,
        codes=expected_major_index_mins_technical_codes(DAY_1),
        first_close=10.0,
    )
    target = gold_major_index_mins_technical_path(lake_root, FREQ, DAY_1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing")

    with pytest.raises(
        MajorIndexMinsTechnicalValidationError,
        match="refuses to overwrite existing target",
    ):
        write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=DAY_1,
            run_id="existing-target",
            expected_trade_dates=(DAY_1,),
        )


def _weekday_dates(start: date, count: int) -> tuple[str, ...]:
    values: list[str] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(values)


def test_writer_matches_scalar_recursive_reference_across_twenty_days(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    expected_dates = _weekday_dates(date(2009, 1, 5), 20)
    code = "000001.SH"
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    final_result = None

    for day_index, trade_date in enumerate(expected_dates):
        first_close = 10.0 + day_index
        _write_silver_partition(
            lake_root,
            trade_date=trade_date,
            codes=expected_major_index_mins_technical_codes(trade_date),
            first_close=first_close,
        )
        closes.extend((first_close, first_close + 3.0))
        highs.extend((first_close + 1.0, first_close + 4.0))
        lows.extend((first_close - 1.0, first_close + 2.0))
        final_result = write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=trade_date,
            run_id=f"recursive-{day_index}",
            expected_trade_dates=expected_dates,
        )

    ema_fast = closes[0]
    ema_slow = closes[0]
    dea = 0.0
    k_value = 50.0
    d_value = 50.0
    for index, close in enumerate(closes):
        ema_fast = (2.0 * close + 11.0 * ema_fast) / 13.0
        ema_slow = (2.0 * close + 25.0 * ema_slow) / 27.0
        dif = ema_fast - ema_slow
        dea = (2.0 * dif + 8.0 * dea) / 10.0
        window_start = max(0, index - 8)
        highest = max(highs[window_start : index + 1])
        lowest = min(lows[window_start : index + 1])
        rsv = 50.0 if highest == lowest else (close - lowest) / (highest - lowest) * 100.0
        k_value = (2.0 * k_value + rsv) / 3.0
        d_value = (2.0 * d_value + k_value) / 3.0

    assert final_result is not None
    final_technical = _read_rows(final_result.technical_path, code=code)
    final_state = _read_rows(
        final_result.state_path,
        code=code,
        order_by="last_trade_time",
    )[0]
    assert [row["observation_count"] for row in final_technical] == [39, 40]
    assert final_state["macd_ema_fast"] == pytest.approx(ema_fast)
    assert final_state["macd_ema_slow"] == pytest.approx(ema_slow)
    assert final_state["macd_dea"] == pytest.approx(dea)
    assert final_state["kdj_k"] == pytest.approx(k_value)
    assert final_state["kdj_d"] == pytest.approx(d_value)


def test_writer_does_not_scan_future_expected_partition(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    future_date = "2009-01-07"
    for trade_date, first_close in (
        (DAY_1, 10.0),
        (DAY_2, 14.0),
        (future_date, 1000.0),
    ):
        _write_silver_partition(
            lake_root,
            trade_date=trade_date,
            codes=expected_major_index_mins_technical_codes(trade_date),
            first_close=first_close,
        )

    result = write_major_index_mins_technical_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        freq=FREQ,
        partition_key=DAY_1,
        run_id="no-future",
        expected_trade_dates=(DAY_1, DAY_2, future_date),
    )

    assert result.source_trade_dates == (DAY_1,)
    rows = _read_rows(result.technical_path, code="000001.SH")
    assert max(float(row["macd_dif"]) for row in rows) < 1.0


def test_writer_leaves_partial_technical_visible_when_state_promotion_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_silver_partition(
        lake_root,
        trade_date=DAY_1,
        codes=expected_major_index_mins_technical_codes(DAY_1),
        first_close=10.0,
    )
    real_replace = os.replace
    replace_calls = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("state promotion failed")
        real_replace(source, target)

    monkeypatch.setattr(writer_module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="state promotion failed"):
        write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=DAY_1,
            run_id="partial-promotion",
            expected_trade_dates=(DAY_1,),
        )

    assert gold_major_index_mins_technical_path(
        lake_root, FREQ, DAY_1
    ).exists()
    assert not gold_major_index_mins_technical_state_path(
        lake_root, FREQ, DAY_1
    ).exists()
    assert not gold_major_index_mins_technical_staging_path(
        staging_root, "partial-promotion", FREQ, DAY_1
    ).exists()
    assert not gold_major_index_mins_technical_state_staging_path(
        staging_root, "partial-promotion", FREQ, DAY_1
    ).exists()
