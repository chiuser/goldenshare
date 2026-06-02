from pathlib import Path

import duckdb

from orchestrator.defs.checks import index_daily_checks as checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import silver_index_basic_path, silver_index_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors import readiness


TARGET_TRADE_DATE = "2026-06-02"


def _write_index_basic_file(root: Path) -> None:
    path = silver_index_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (
                VALUES
                  ('000001.SH', DATE '2000-01-01', CAST(NULL AS DATE)),
                  ('000300.SH', DATE '2005-04-08', CAST(NULL AS DATE))
              ) rows(ts_code, list_date, exp_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_silver_index_daily_file(root: Path, ts_codes: tuple[str, ...]) -> None:
    path = silver_index_daily_path(root, TARGET_TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(f"({duckdb_string(ts_code)})" for ts_code in ts_codes)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT ts_code
              FROM (VALUES {values_sql}) rows(ts_code)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def test_silver_index_daily_coverage_check_is_blocking_readiness_gate() -> None:
    assert (
        "silver_index_daily_registered_code_coverage"
        in readiness.SILVER_INDEX_DAILY_BLOCKING_CHECKS
    )


def test_silver_index_daily_coverage_check_fails_missing_effective_code(
    tmp_path: Path,
) -> None:
    _write_index_basic_file(tmp_path)
    _write_silver_index_daily_file(tmp_path, ("000001.SH",))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert not result.passed


def test_silver_index_daily_coverage_check_passes_complete_effective_codes(
    tmp_path: Path,
) -> None:
    _write_index_basic_file(tmp_path)
    _write_silver_index_daily_file(tmp_path, ("000001.SH", "000300.SH"))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert result.passed
