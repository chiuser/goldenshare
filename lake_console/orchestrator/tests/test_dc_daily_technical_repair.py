from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.asset_guards.dc_daily_silver_repair_producer import (
    source_revision_for_silver_paths,
)
from orchestrator.defs.assets.dc_daily_technical_repair import (
    DcDailyTechnicalRepairValidationError,
    write_gold_dc_daily_technical_repair_batch,
)
from orchestrator.defs.paths import silver_dc_daily_path, silver_trade_calendar_path
from orchestrator.defs.run_contracts.silver_repair import hash_affected_series
from orchestrator.defs.asset_guards.dc_daily_silver_repair import (
    build_dc_daily_silver_repair_batch,
)


class _MemoryDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    def connect(self):
        self.connection_count += 1
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _dates(count: int = 20) -> tuple[str, ...]:
    start = date(2024, 1, 2)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(count))


def _write_fixture(root: Path, dates: tuple[str, ...]) -> None:
    calendar = silver_trade_calendar_path(root)
    calendar.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('SSE', DATE '{trade_date}', TRUE)" for trade_date in dates
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open)) "
            "TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )

    for index, trade_date in enumerate(dates, start=1):
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
            connection.execute(
                """INSERT INTO source VALUES (
                    'BK0001.DC', CAST(? AS DATE), ?, ?, ?, ?, 0, 0, 1, 1, 0, 0, '行业板块'
                )""",
                [
                    trade_date,
                    float(index),
                    float(index),
                    float(index + 1),
                    float(index - 1),
                ],
            )
            connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def _batch(root: Path, dates: tuple[str, ...]):
    source_paths = tuple(silver_dc_daily_path(root, trade_date) for trade_date in dates[:2])
    with duckdb.connect(":memory:") as connection:
        source_revision = source_revision_for_silver_paths(connection, source_paths)
    return build_dc_daily_silver_repair_batch(
        producer_run_id="silver-producer-run-1",
        source_revision=source_revision,
        source_repair_start_trade_date=dates[0],
        source_repair_end_trade_date=dates[1],
        indicator_recompute_start_trade_date=dates[0],
        indicator_recompute_end_trade_date=dates[-1],
        context_start_trade_date=dates[0],
        target_frontier_trade_date=dates[-1],
        affected_date_count=2,
        affected_series_count=1,
        affected_series_hash=hash_affected_series(("BK0001.DC|行业板块",)),
        truncated=False,
        selected_partition_count=len(dates),
        expected_trade_dates=dates,
        registered_trade_dates=dates,
    )


def test_repair_writer_recomputes_all_targets_with_one_duckdb_connection(tmp_path: Path):
    dates = _dates()
    _write_fixture(tmp_path, dates)
    resource = _MemoryDuckDB()

    result = write_gold_dc_daily_technical_repair_batch(
        lake_root_path=tmp_path,
        duckdb_resource=resource,
        batch=_batch(tmp_path, dates),
        expected_trade_dates=dates,
        registered_trade_dates=dates,
    )

    assert resource.connection_count == 1
    assert result.rewritten_partition_count == len(dates)
    assert result.output_row_count == len(dates)
    assert result.source_file_count == len(dates)
    assert all(item.skipped_existing is False for item in result.partition_results)
    assert not list(tmp_path.rglob("*.p7-repair-*.tmp"))
    assert all(silver_dc_daily_path(tmp_path, date_key).exists() for date_key in dates)


def test_source_revision_mismatch_fails_before_existing_targets_change(tmp_path: Path):
    dates = _dates()
    _write_fixture(tmp_path, dates)
    target = tmp_path / "gold-target-sentinel.parquet"
    target.write_bytes(b"existing-target")
    batch = _batch(tmp_path, dates)
    invalid_batch = build_dc_daily_silver_repair_batch(
        producer_run_id=batch.producer_run_id,
        source_revision="silver_dc_daily:v1:" + "0" * 64,
        source_repair_start_trade_date=batch.source_repair_start_trade_date,
        source_repair_end_trade_date=batch.source_repair_end_trade_date,
        indicator_recompute_start_trade_date=batch.indicator_recompute_start_trade_date,
        indicator_recompute_end_trade_date=batch.indicator_recompute_end_trade_date,
        context_start_trade_date=batch.context_start_trade_date,
        target_frontier_trade_date=batch.target_frontier_trade_date,
        affected_date_count=batch.affected_date_count,
        affected_series_count=batch.affected_series_count,
        affected_series_hash=batch.affected_series_hash,
        truncated=False,
        selected_partition_count=batch.selected_partition_count,
        expected_trade_dates=dates,
        registered_trade_dates=dates,
    )

    with pytest.raises(DcDailyTechnicalRepairValidationError, match="source_revision"):
        write_gold_dc_daily_technical_repair_batch(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            batch=invalid_batch,
            expected_trade_dates=dates,
            registered_trade_dates=dates,
        )

    assert target.read_bytes() == b"existing-target"
    assert not list(tmp_path.rglob("*.p7-repair-*.tmp"))


def test_repair_budget_is_checked_before_writing(tmp_path: Path):
    dates = _dates()
    _write_fixture(tmp_path, dates)

    with pytest.raises(ValueError, match="bounded budget"):
        write_gold_dc_daily_technical_repair_batch(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            batch=_batch(tmp_path, dates),
            expected_trade_dates=dates,
            registered_trade_dates=dates,
            max_indicator_recompute_dates=10,
        )

    assert not list(tmp_path.rglob("*.p7-repair-*.tmp"))


def test_repair_60_day_benchmark_stays_within_bounded_budget(tmp_path: Path):
    dates = _dates(60)
    _write_fixture(tmp_path, dates)
    resource = _MemoryDuckDB()

    result = write_gold_dc_daily_technical_repair_batch(
        lake_root_path=tmp_path,
        duckdb_resource=resource,
        batch=_batch(tmp_path, dates),
        expected_trade_dates=dates,
        registered_trade_dates=dates,
        max_indicator_recompute_dates=60,
    )

    assert resource.connection_count == 1
    assert result.source_file_count == 60
    assert result.rewritten_partition_count == 60
    assert result.elapsed_ms < 60_000
    assert result.duckdb_elapsed_ms >= 0
    assert result.staging_write_elapsed_ms >= 0
    assert result.promote_elapsed_ms >= 0
    assert not list(tmp_path.rglob("*.p7-repair-*.tmp"))
