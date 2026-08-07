from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb

from orchestrator.defs.checks.major_index_mins_checks import (
    evaluate_major_index_mins_core_check,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_major_index_mins_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_mins import (
    effective_raw_request_codes_for_date,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)


PARTITION_KEY = "2026-08-04"


def _write_raw(root: Path, *, omit_last_code: bool = False) -> Path:
    path = raw_major_index_mins_path(root, "60min", PARTITION_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    expected_codes = effective_raw_request_codes_for_date(PARTITION_KEY)
    if omit_last_code:
        expected_codes = expected_codes[:-1]
    for code in expected_codes:
        exchange = major_index_mins_exchange_for_code(code)
        for index, source_time in enumerate(
            major_index_mins_session_times(
                exchange=exchange,
                source_freq="60min",
            )
        ):
            value = float(index + 1)
            rows.append(
                (
                    code,
                    "60min",
                    f"{PARTITION_KEY} {source_time}",
                    value,
                    value + 0.5,
                    value + 1.0,
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
    return path


def _context(*partition_keys: str) -> SimpleNamespace:
    return SimpleNamespace(partition_keys=partition_keys)


def test_core_check_passes_for_exact_raw_partition(tmp_path: Path) -> None:
    _write_raw(tmp_path)
    result = evaluate_major_index_mins_core_check(
        context=_context(PARTITION_KEY),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=DuckDBResource(),
        layer="raw",
        frequency="60min",
    )
    assert result.passed is True
    assert result.metadata["goldenshare/reason_code"].value == "ready"


def test_core_check_rejects_missing_expected_code(tmp_path: Path) -> None:
    _write_raw(tmp_path, omit_last_code=True)
    result = evaluate_major_index_mins_core_check(
        context=_context(PARTITION_KEY),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=DuckDBResource(),
        layer="raw",
        frequency="60min",
    )
    assert result.passed is False
    failed_rules = result.metadata["goldenshare/failed_rule_names"].value
    assert "missing_codes" in failed_rules
    assert "session_grid" in failed_rules


def test_core_check_fails_closed_for_multi_partition_context(tmp_path: Path) -> None:
    result = evaluate_major_index_mins_core_check(
        context=_context("2026-08-01", PARTITION_KEY),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=DuckDBResource(),
        layer="raw",
        frequency="60min",
    )
    assert result.passed is False
    assert (
        result.metadata["goldenshare/reason_code"].value
        == "multiple_partition_execution"
    )
