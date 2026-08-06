from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.asset_guards.major_index_mins_lake_readiness import (
    batch_raw_major_index_mins_lake_readiness,
    batch_silver_major_index_mins_lake_readiness,
)
from orchestrator.defs.asset_guards import major_index_mins_lake_readiness
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.major_index_mins_silver_writer import (
    write_major_index_mins_silver_partition,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    effective_codes_for_date,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)


TRADE_DATE = "2026-08-04"


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _write_raw(
    root: Path,
    frequency: str,
    *,
    trade_date: str = TRADE_DATE,
    omit_code: str | None = None,
) -> None:
    path = raw_major_index_mins_path(root, frequency, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for code in effective_codes_for_date(trade_date):
        if code == omit_code:
            continue
        exchange = major_index_mins_exchange_for_code(code)
        for index, source_time in enumerate(
            major_index_mins_session_times(
                exchange=exchange,
                source_freq=frequency,
            )
        ):
            value = float(index + 1)
            rows.append(
                (
                    code,
                    frequency,
                    f"{trade_date} {source_time}",
                    value,
                    value + 0.5,
                    value + 1,
                    value - 0.5,
                    value * 10,
                    value * 100,
                    exchange,
                    value + 0.25,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM source_rows", path))


def _write_all_raw(root: Path, *, trade_date: str = TRADE_DATE) -> None:
    for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
        _write_raw(root, frequency, trade_date=trade_date)


def _write_all_silver(root: Path) -> None:
    for frequency in MAJOR_INDEX_MINS_SILVER_FREQS:
        write_major_index_mins_silver_partition(
            lake_root_path=root,
            duckdb_resource=_MemoryDuckDB(),
            freq=frequency,
            partition_key=TRADE_DATE,
            run_id=f"p5-{frequency}",
        )


def test_readiness_accepts_complete_raw_and_silver(tmp_path: Path) -> None:
    _write_all_raw(tmp_path)
    _write_all_silver(tmp_path)
    with duckdb.connect(":memory:") as connection:
        raw = batch_raw_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
        )
        silver = batch_silver_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
        )
    assert raw.status_for_trade_date(TRADE_DATE).ready is True
    assert silver.status_for_trade_date(TRADE_DATE).ready is True
    assert raw.scanned_file_count == 5
    assert silver.scanned_file_count == 7


def test_missing_raw_file_is_actionable_not_materialized(tmp_path: Path) -> None:
    _write_all_raw(tmp_path)
    raw_major_index_mins_path(tmp_path, "60min", TRADE_DATE).unlink()
    with duckdb.connect(":memory:") as connection:
        batch = batch_raw_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
        )
    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is False


def test_existing_invalid_raw_file_blocks_automatic_overwrite(tmp_path: Path) -> None:
    _write_all_raw(tmp_path)
    _write_raw(tmp_path, "60min", omit_code=effective_codes_for_date(TRADE_DATE)[-1])
    with duckdb.connect(":memory:") as connection:
        batch = batch_raw_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
        )
    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is True
    assert status.checks_passed is False


def test_readiness_rejects_windows_larger_than_ten() -> None:
    dates = tuple(f"2026-07-{day:02d}" for day in range(1, 12))
    with duckdb.connect(":memory:") as connection, pytest.raises(ValueError):
        batch_raw_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=Path("/tmp/not-used"),
            expected_trade_dates=dates,
            registered_trade_days=dates,
        )


def test_raw_readiness_reuses_expected_tables_for_same_scope_dates(
    tmp_path: Path,
) -> None:
    trade_dates = ("2026-08-03", TRADE_DATE)
    for trade_date in trade_dates:
        _write_all_raw(tmp_path, trade_date=trade_date)
    original = major_index_mins_lake_readiness.prepare_major_index_mins_expected_tables
    with (
        duckdb.connect(":memory:") as connection,
        patch.object(
            major_index_mins_lake_readiness,
            "prepare_major_index_mins_expected_tables",
            wraps=original,
        ) as prepare,
    ):
        batch = batch_raw_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=trade_dates,
            registered_trade_days=trade_dates,
        )
    assert all(batch.status_for_trade_date(value).ready for value in trade_dates)
    assert prepare.call_count == len(MAJOR_INDEX_MINS_SOURCE_FREQS)


def test_silver_missing_is_actionable_after_valid_existing_files(
    tmp_path: Path,
) -> None:
    _write_all_raw(tmp_path)
    _write_all_silver(tmp_path)
    silver_major_index_mins_path(tmp_path, "120min", TRADE_DATE).unlink()
    with duckdb.connect(":memory:") as connection:
        batch = batch_silver_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
        )
    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is False
