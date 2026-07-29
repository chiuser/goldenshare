from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from orchestrator.defs.asset_guards.index_mins_lake_readiness import (
    batch_raw_index_mins_lake_readiness,
    batch_silver_index_mins_lake_readiness,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ASSET_FREQS,
    INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ,
)


TRADE_DATE = "2026-07-27"
TRADE_TIME = datetime(2026, 7, 27, 9, 30)


def _write_raw_file(root: Path, *, source_freq: str, rows: int = 1) -> None:
    path = raw_index_mins_path(root, source_freq, TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = [
        (
            "000001.SH",
            source_freq,
            TRADE_TIME,
            10.0,
            10.5,
            11.0,
            9.5,
            100.0,
            1000.0,
            "XSHG",
            10.25,
        )
        for _ in range(rows)
    ]
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              open DOUBLE,
              close DOUBLE,
              high DOUBLE,
              low DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM source_rows", path))


def _write_all_raw(root: Path, *, duplicate_source_freq: str | None = None) -> None:
    for frequency in INDEX_MINS_ASSET_FREQS:
        _write_raw_file(
            root,
            source_freq=INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ[frequency],
            rows=2 if INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ[frequency] == duplicate_source_freq else 1,
        )


def _write_invalid_silver_target(root: Path) -> None:
    path = silver_index_mins_path(root, 1, TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TABLE target_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              open DOUBLE,
              close DOUBLE,
              high DOUBLE,
              low DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO target_rows VALUES
              ('000001.SH', '1min', TIMESTAMP '2026-07-27 09:30:00', 10, 10.5, 11, 9.5, 100, 1000, 'XSHG', 10.25),
              ('000001.SH', '1min', TIMESTAMP '2026-07-27 09:30:00', 10, 10.5, 11, 9.5, 100, 1000, 'XSHG', 10.25)
            """
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM target_rows", path))


def test_raw_readiness_distinguishes_missing_files_and_bounds_window() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw_file(root, source_freq="1min")
        with DuckDBResource().connect() as connection:
            result = batch_raw_index_mins_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
            )
        status = result.status_for_trade_date(TRADE_DATE)
        assert status.materialized is False
        assert status.checks_passed is False
        assert status.ready is False
        assert status.summary["reason_code"] == "file_missing"
        assert result.scanned_file_count == 1

    with TemporaryDirectory() as directory:
        with DuckDBResource().connect() as connection:
            with pytest.raises(ValueError, match="bounded sensor limit"):
                batch_raw_index_mins_lake_readiness(
                    connection=connection,
                    lake_root=Path(directory),
                    expected_trade_dates=tuple(f"2026-07-{day:02d}" for day in range(1, 12)),
                    registered_trade_days=(),
                )


def test_raw_readiness_marks_existing_duplicate_data_as_materialized_failure() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_all_raw(root, duplicate_source_freq="1min")
        with DuckDBResource().connect() as connection:
            result = batch_raw_index_mins_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
            )
        status = result.status_for_trade_date(TRADE_DATE)
        assert status.materialized is True
        assert status.checks_passed is False
        assert status.ready is False
        assert status.summary["reason_code"] == "core_check_failed"
        assert any("business_key_unique" in rule for rule in status.summary["failed_rules"])


def test_silver_readiness_distinguishes_missing_targets_from_existing_bad_target() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_all_raw(root)
        _write_invalid_silver_target(root)
        with DuckDBResource().connect() as connection:
            result = batch_silver_index_mins_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
            )
        status = result.status_for_trade_date(TRADE_DATE)
        assert status.materialized is True
        assert status.checks_passed is False
        assert status.ready is False
        assert status.summary["reason_code"] == "core_check_failed"


def test_silver_readiness_missing_all_derived_targets_is_actionable() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_all_raw(root)
        with DuckDBResource().connect() as connection:
            result = batch_silver_index_mins_lake_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
            )
        status = result.status_for_trade_date(TRADE_DATE)
        assert status.materialized is False
        assert status.checks_passed is False
        assert status.summary["reason_code"] == "file_missing"
