from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from orchestrator.defs.checks import index_daily_checks as checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_index_daily_path,
    raw_index_daily_by_code_path,
    silver_index_basic_path,
    silver_index_daily_path,
)
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


def _write_raw_index_daily_file(root: Path, ts_code: str, trade_dates: tuple[str, ...]) -> None:
    path = raw_index_daily_by_code_path(root, ts_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({duckdb_string(ts_code)}, {duckdb_string(trade_date)})"
        for trade_date in trade_dates
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, trade_date)
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


def _write_raw_index_daily_by_date_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[object, ...], ...],
) -> None:
    path = raw_index_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")" for row in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS VARCHAR) AS trade_date,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(pre_close AS DOUBLE) AS pre_close,
                CAST(change AS DOUBLE) AS change,
                CAST(pct_chg AS DOUBLE) AS pct_chg,
                CAST(vol AS DOUBLE) AS vol,
                CAST(amount AS DOUBLE) AS amount
              FROM (
                VALUES {values_sql}
              ) rows(
                ts_code, trade_date, open, high, low, close, pre_close,
                change, pct_chg, vol, amount
              )
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return duckdb_string(value)
    return str(value)


def test_silver_index_daily_coverage_check_is_blocking_readiness_gate() -> None:
    assert (
        "silver_index_daily_registered_code_coverage"
        in readiness.SILVER_INDEX_DAILY_BLOCKING_CHECKS
    )


def test_silver_index_daily_blocking_checks_do_not_include_history_raw_gap_audit() -> None:
    forbidden_fragments = ("raw_gap", "raw_continuity", "history", "full", "250")

    assert all(
        not any(fragment in check_name for fragment in forbidden_fragments)
        for check_name in readiness.SILVER_INDEX_DAILY_BLOCKING_CHECKS
    )


def test_silver_index_daily_coverage_check_fails_missing_raw_present_code(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260602",))
    _write_silver_index_daily_file(tmp_path, ("000001.SH",))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert not result.passed


def test_silver_index_daily_coverage_check_passes_complete_raw_present_codes(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260602",))
    _write_silver_index_daily_file(tmp_path, ("000001.SH", "000300.SH"))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert result.passed


def test_silver_index_daily_coverage_check_does_not_use_index_basic_list_date(
    tmp_path: Path,
) -> None:
    _write_index_basic_file(tmp_path)
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))
    _write_silver_index_daily_file(tmp_path, ("000001.SH",))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH", "950228.SH"),
    )

    assert result.passed


def test_silver_index_daily_coverage_check_fails_extra_code_not_present_in_raw(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))
    _write_silver_index_daily_file(tmp_path, ("000001.SH", "000300.SH"))

    result = checks.evaluate_silver_index_daily_registered_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert not result.passed


def test_raw_index_daily_file_contract_check_passes_with_nullable_ohlc(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        TARGET_TRADE_DATE,
        (
            ("000001.SH", "20260602", None, 2.0, 1.0, 1.5, None, None, 1.0, 10.0, 20.0),
            ("000300.SH", "20260602", 2.0, 3.0, 1.5, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
        ),
    )

    result = checks.evaluate_raw_index_daily_file_contract(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
    )

    assert result.passed


def test_raw_index_daily_file_contract_check_fails_duplicate_key(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        TARGET_TRADE_DATE,
        (
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
        ),
    )

    result = checks.evaluate_raw_index_daily_file_contract(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
    )

    assert not result.passed


def test_raw_index_daily_file_contract_check_fails_date_mismatch(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        TARGET_TRADE_DATE,
        (("000001.SH", "20260601", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),),
    )

    result = checks.evaluate_raw_index_daily_file_contract(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
    )

    assert not result.passed


def test_raw_index_daily_code_coverage_check_passes_complete_dg_codes(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        TARGET_TRADE_DATE,
        (
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
            ("000300.SH", "20260602", 2.0, 3.0, 1.5, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
        ),
    )

    result = checks.evaluate_raw_index_daily_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert result.passed


def test_raw_index_daily_code_coverage_check_fails_missing_or_extra_code(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        TARGET_TRADE_DATE,
        (
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
            ("399001.SZ", "20260602", 2.0, 3.0, 1.5, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
        ),
    )

    result = checks.evaluate_raw_index_daily_code_coverage(
        (TARGET_TRADE_DATE,),
        tmp_path,
        DuckDBResource(),
        ("000001.SH", "000300.SH"),
    )

    assert not result.passed


class SilverIndexDailyCoverageCheckTests(unittest.TestCase):
    def _run_with_tmp_path(self, test_func) -> None:
        with TemporaryDirectory() as directory:
            test_func(Path(directory))

    def test_coverage_check_is_blocking_readiness_gate(self) -> None:
        test_silver_index_daily_coverage_check_is_blocking_readiness_gate()

    def test_blocking_checks_do_not_include_history_raw_gap_audit(self) -> None:
        test_silver_index_daily_blocking_checks_do_not_include_history_raw_gap_audit()

    def test_fails_missing_raw_present_code(self) -> None:
        self._run_with_tmp_path(
            test_silver_index_daily_coverage_check_fails_missing_raw_present_code
        )

    def test_passes_complete_raw_present_codes(self) -> None:
        self._run_with_tmp_path(
            test_silver_index_daily_coverage_check_passes_complete_raw_present_codes
        )

    def test_does_not_use_index_basic_list_date(self) -> None:
        self._run_with_tmp_path(
            test_silver_index_daily_coverage_check_does_not_use_index_basic_list_date
        )

    def test_fails_extra_code_not_present_in_raw(self) -> None:
        self._run_with_tmp_path(
            test_silver_index_daily_coverage_check_fails_extra_code_not_present_in_raw
        )

    def test_raw_file_contract_check_passes_with_nullable_ohlc(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_file_contract_check_passes_with_nullable_ohlc
        )

    def test_raw_file_contract_check_fails_duplicate_key(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_file_contract_check_fails_duplicate_key
        )

    def test_raw_file_contract_check_fails_date_mismatch(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_file_contract_check_fails_date_mismatch
        )

    def test_raw_code_coverage_check_passes_complete_dg_codes(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_code_coverage_check_passes_complete_dg_codes
        )

    def test_raw_code_coverage_check_fails_missing_or_extra_code(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_code_coverage_check_fails_missing_or_extra_code
        )


if __name__ == "__main__":
    unittest.main()
