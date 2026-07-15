from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets.dc_daily_technical import (
    DcDailyTechnicalValidationError,
    write_gold_dc_daily_technical_partition,
)
from orchestrator.defs.paths import (
    gold_dc_daily_technical_path,
    silver_dc_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _dates(count: int) -> tuple[str, ...]:
    start = date(2024, 1, 2)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(count))


def _write_calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('SSE', DATE '{trade_date}', TRUE, NULL::DATE)" for trade_date in dates
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open, pretrade_date)) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _write_silver_rows(
    root: Path,
    dates: tuple[str, ...],
    *,
    categories: tuple[str, ...] = ("行业板块",),
    invalid_trade_date: str | None = None,
    duplicate_last_row: bool = False,
) -> None:
    rows_by_date: dict[str, list[tuple[object, ...]]] = {trade_date: [] for trade_date in dates}
    for index, trade_date in enumerate(dates, start=1):
        for category_index, category in enumerate(categories):
            close = float(index + category_index * 100)
            rows_by_date[trade_date].append(
                (
                    "BK0001.DC" if category_index == 0 else "BK0002.DC",
                    invalid_trade_date or trade_date,
                    close,
                    close,
                    close + 1.0,
                    close - 1.0,
                    0.0,
                    0.0,
                    1.0,
                    1.0,
                    0.0,
                    0.0,
                    category,
                )
            )
    if duplicate_last_row:
        rows_by_date[dates[-1]].append(rows_by_date[dates[-1]][-1])

    for trade_date in dates:
        path = silver_dc_daily_path(root, trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(":memory:") as connection:
            connection.execute(
                """
                CREATE TABLE source (
                  ts_code VARCHAR,
                  trade_date DATE,
                  close DOUBLE,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  change DOUBLE,
                  pct_change DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE,
                  swing DOUBLE,
                  turnover_rate DOUBLE,
                  category VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO source VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows_by_date[trade_date],
            )
            connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def _write_fixture(root: Path, count: int = 20, **kwargs) -> tuple[str, ...]:
    dates = _dates(count)
    _write_calendar(root, dates)
    _write_silver_rows(root, dates, **kwargs)
    return dates


def _row(root: Path, trade_date: str) -> dict[str, object]:
    path = gold_dc_daily_technical_path(root, trade_date)
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            f"SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchone()
        columns = [item[0] for item in connection.description]
    return dict(zip(columns, row))


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    result: list[float] = []
    previous = values[0]
    result.append(previous)
    for value in values[1:]:
        previous = previous + alpha * (value - previous)
        result.append(previous)
    return result


def _kdj_last(values: list[float]) -> tuple[float, float, float]:
    highs = [value + 1.0 for value in values]
    lows = [value - 1.0 for value in values]
    k_value = 50.0
    d_value = 50.0
    for index, close in enumerate(values):
        start = max(0, index - 8)
        hhv = max(highs[start : index + 1])
        llv = min(lows[start : index + 1])
        rsv = 50.0 if hhv == llv else (close - llv) / (hhv - llv) * 100.0
        k_value = (2.0 * k_value + rsv) / 3.0
        d_value = (2.0 * d_value + k_value) / 3.0
    return k_value, d_value, 3.0 * k_value - 2.0 * d_value


def test_writer_matches_formula_fixture_and_schema(tmp_path):
    root = Path(tmp_path)
    dates = _write_fixture(root, 20)
    result = write_gold_dc_daily_technical_partition(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key=dates[-1],
    )

    assert result.trade_date == dates[-1]
    assert result.source_file_count == 20
    assert result.source_row_count == 20
    assert result.written_row_count == 1
    assert result.series_count == 1
    assert result.skipped_existing is False
    assert result.staging_path is not None
    assert result.staging_path.exists() is False
    assert result.target_path == gold_dc_daily_technical_path(root, dates[-1])

    row = _row(root, dates[-1])
    assert row["close"] == pytest.approx(20.0)
    assert row["ma_5"] == pytest.approx(18.0)
    assert row["ma_20"] == pytest.approx(10.5)
    assert row["ma_250"] is None
    assert row["boll_mid"] == pytest.approx(10.5)
    assert row["boll_upper"] == pytest.approx(10.5 + 2.0 * (33.25**0.5))
    assert row["boll_lower"] == pytest.approx(10.5 - 2.0 * (33.25**0.5))
    values = [float(index) for index in range(1, 21)]
    kdj_k, kdj_d, kdj_j = _kdj_last(values)
    assert row["kdj_k"] == pytest.approx(kdj_k)
    assert row["kdj_d"] == pytest.approx(kdj_d)
    assert row["kdj_j"] == pytest.approx(kdj_j)
    fast = _ema(values, 12)
    slow = _ema(values, 26)
    dif = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    dea = _ema(dif, 9)
    assert row["macd_dif"] == pytest.approx(dif[-1])
    assert row["macd_dea"] == pytest.approx(dea[-1])
    assert row["macd"] == pytest.approx(2.0 * (dif[-1] - dea[-1]))
    assert row["observation_count"] == 20
    assert row["params_key"] == "ma_5_10_15_20_30_60_120_250__macd_12_26_9__kdj_9_3_3__boll_20_2"
    assert row["indicator_version"] == "v1"

    with duckdb.connect(":memory:") as connection:
        observed = tuple(
            (str(item[0]), str(item[1]).upper())
            for item in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(result.target_path)]
            ).fetchall()
        )
    expected = tuple((column.name, column.type) for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA)
    assert observed == expected


def test_warmup_fields_are_null_and_series_are_isolated_by_category(tmp_path):
    root = Path(tmp_path)
    dates = _write_fixture(root, 10, categories=("行业板块", "概念板块"))
    result = write_gold_dc_daily_technical_partition(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key=dates[-1],
    )
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            """
            SELECT ts_code, category, observation_count, ma_5, ma_10,
                   boll_mid, boll_upper, boll_lower
            FROM read_parquet(?)
            ORDER BY ts_code, category
            """,
            [str(result.target_path)],
        ).fetchall()
    assert len(rows) == 2
    assert all(row[2] == 10 for row in rows)
    assert all(row[3] is not None for row in rows)
    assert all(row[4] is not None for row in rows)
    assert all(row[5] is None and row[6] is None and row[7] is None for row in rows)


def test_existing_valid_target_is_skipped_without_overwrite(tmp_path):
    root = Path(tmp_path)
    dates = _write_fixture(root, 20)
    first = write_gold_dc_daily_technical_partition(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key=dates[-1],
    )
    before = first.target_path.read_bytes()
    second = write_gold_dc_daily_technical_partition(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key=dates[-1],
    )
    assert second.skipped_existing is True
    assert second.target_path.read_bytes() == before
    assert list(first.target_path.parent.glob("*.tmp")) == []


def test_invalid_source_keeps_existing_target_and_cleans_staging(tmp_path):
    root = Path(tmp_path)
    dates = _write_fixture(root, 4, invalid_trade_date="2024-01-01")
    target = gold_dc_daily_technical_path(root, dates[-1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing-target")

    with pytest.raises(DcDailyTechnicalValidationError, match="out_of_partition_count"):
        write_gold_dc_daily_technical_partition(
            lake_root_path=root,
            duckdb_resource=_MemoryDuckDB(),
            partition_key=dates[-1],
        )
    assert target.read_bytes() == b"existing-target"
    assert list(target.parent.glob("*.tmp")) == []


def test_duplicate_source_key_fails_closed(tmp_path):
    root = Path(tmp_path)
    dates = _dates(3)
    _write_calendar(root, dates)
    _write_silver_rows(root, dates, duplicate_last_row=True)

    with pytest.raises(DcDailyTechnicalValidationError, match="duplicate_key_count"):
        write_gold_dc_daily_technical_partition(
            lake_root_path=root,
            duckdb_resource=_MemoryDuckDB(),
            partition_key=dates[-1],
        )
