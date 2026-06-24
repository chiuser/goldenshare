from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_index_daily_path
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    raw_index_daily_lake_readiness_for_trade_dates,
)


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return duckdb_string(value)
    return str(value)


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


def test_raw_index_daily_by_date_lake_readiness_passes_complete_codes(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        "2026-06-02",
        (
            ("000001.SH", "20260602", None, 2.0, 1.0, 1.5, None, None, 1.0, 10.0, 20.0),
            ("000300.SH", "20260602", 2.0, 3.0, 1.5, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
        ),
    )

    with duckdb.connect(database=":memory:") as connection:
        result = raw_index_daily_lake_readiness_for_trade_dates(
            connection,
            lake_root_path=tmp_path,
            trade_dates=("2026-06-02",),
            expected_index_codes=("000001.SH", "000300.SH"),
        )

    status = result.status_for_trade_date("2026-06-02")
    assert status.ready
    assert status.summary["observed_code_count"] == 2


def test_raw_index_daily_by_date_lake_readiness_reports_missing_file(
    tmp_path: Path,
) -> None:
    with duckdb.connect(database=":memory:") as connection:
        result = raw_index_daily_lake_readiness_for_trade_dates(
            connection,
            lake_root_path=tmp_path,
            trade_dates=("2026-06-02",),
            expected_index_codes=("000001.SH",),
        )

    status = result.status_for_trade_date("2026-06-02")
    assert not status.ready
    assert not status.materialized
    assert status.missing_check_names == ("raw_index_daily_file_contract_check",)


def test_raw_index_daily_by_date_lake_readiness_fails_duplicate_key(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        "2026-06-02",
        (
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
        ),
    )

    with duckdb.connect(database=":memory:") as connection:
        result = raw_index_daily_lake_readiness_for_trade_dates(
            connection,
            lake_root_path=tmp_path,
            trade_dates=("2026-06-02",),
            expected_index_codes=("000001.SH",),
        )

    status = result.status_for_trade_date("2026-06-02")
    assert not status.ready
    assert status.materialized
    assert status.failed_check_names == ("raw_index_daily_file_contract_check",)
    assert status.summary["duplicate_key_count"] == 1


def test_raw_index_daily_by_date_lake_readiness_fails_missing_or_extra_code(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_by_date_file(
        tmp_path,
        "2026-06-02",
        (
            ("000001.SH", "20260602", 1.0, 2.0, 1.0, 1.5, 1.0, 0.5, 1.0, 10.0, 20.0),
            ("399001.SZ", "20260602", 2.0, 3.0, 1.5, 2.5, 2.0, 0.5, 2.0, 30.0, 40.0),
        ),
    )

    with duckdb.connect(database=":memory:") as connection:
        result = raw_index_daily_lake_readiness_for_trade_dates(
            connection,
            lake_root_path=tmp_path,
            trade_dates=("2026-06-02",),
            expected_index_codes=("000001.SH", "000300.SH"),
        )

    status = result.status_for_trade_date("2026-06-02")
    assert not status.ready
    assert status.failed_check_names == ("raw_index_daily_code_coverage_check",)
    assert status.summary["missing_code_count"] == 1
    assert status.summary["extra_code_count"] == 1


class IndexDailyRawFileReadinessTests(unittest.TestCase):
    def _run_with_tmp_path(self, test_func) -> None:
        with TemporaryDirectory() as directory:
            test_func(Path(directory))

    def test_by_date_lake_readiness_passes_complete_codes(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_by_date_lake_readiness_passes_complete_codes
        )

    def test_by_date_lake_readiness_reports_missing_file(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_by_date_lake_readiness_reports_missing_file
        )

    def test_by_date_lake_readiness_fails_duplicate_key(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_by_date_lake_readiness_fails_duplicate_key
        )

    def test_by_date_lake_readiness_fails_missing_or_extra_code(self) -> None:
        self._run_with_tmp_path(
            test_raw_index_daily_by_date_lake_readiness_fails_missing_or_extra_code
        )


if __name__ == "__main__":
    unittest.main()
