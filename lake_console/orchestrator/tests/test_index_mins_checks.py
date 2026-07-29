from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from orchestrator.defs.assets.index_mins_silver import write_silver_index_mins_partition
from orchestrator.defs.checks.index_mins_checks import (
    _raw_core_result,
    _silver_core_result,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


PARTITION_KEY = "2026-07-28"
TRADE_TIME = datetime(2026, 7, 28, 9, 30)


def _write_raw(root: Path, *, duplicate: bool = False) -> Path:
    path = raw_index_mins_path(root, "1min", PARTITION_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            "000001.SH",
            "1min",
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
    ]
    if duplicate:
        rows.append(rows[0])
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
        connection.executemany("INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM source_rows",
                path,
            )
        )
    return path


def _context(*partition_keys: str) -> SimpleNamespace:
    return SimpleNamespace(partition_keys=partition_keys)


def test_raw_core_check_passes_for_a_valid_partition() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root)
        result = _raw_core_result(
            context=_context(PARTITION_KEY),
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb_resource=DuckDBResource(),
            source_freq="1min",
        )
        assert result.passed is True


def test_raw_core_check_rejects_duplicate_business_keys() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root, duplicate=True)
        result = _raw_core_result(
            context=_context(PARTITION_KEY),
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb_resource=DuckDBResource(),
            source_freq="1min",
        )
        assert result.passed is False
        assert result.metadata["goldenshare/reason_code"].value == "raw_core_check_failed"


def test_silver_core_check_passes_after_native_silver_write() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root)
        write_silver_index_mins_partition(
            lake_root=root,
            duckdb=DuckDBResource(),
            freq=1,
            partition_key=PARTITION_KEY,
        )
        result = _silver_core_result(
            context=_context(PARTITION_KEY),
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb_resource=DuckDBResource(),
            silver_freq=1,
        )
        assert result.passed is True
        assert silver_index_mins_path(root, 1, PARTITION_KEY).exists()


def test_silver_core_check_fails_closed_when_target_is_missing() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root)
        result = _silver_core_result(
            context=_context(PARTITION_KEY),
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb_resource=DuckDBResource(),
            silver_freq=1,
        )
        assert result.passed is False
        assert result.metadata["goldenshare/reason_code"].value == "file_missing"
