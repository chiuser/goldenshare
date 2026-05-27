from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    check_index_daily_raw_files_for_trade_date,
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


def _write_raw_index_daily_file_without_trade_date(root: Path, ts_code: str) -> None:
    path = raw_index_daily_by_code_path(root, ts_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT {duckdb_string(ts_code)} AS ts_code
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def test_index_daily_raw_file_readiness_all_codes_ready(tmp_path: Path) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260525", "20260526"))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260526",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_date="2026-05-26",
    )

    assert result.ready
    assert result.registered_code_count == 2
    assert result.ready_code_count == 2
    assert result.missing_file_codes == ()
    assert result.missing_trade_date_codes == ()


def test_index_daily_raw_file_readiness_reports_missing_files(tmp_path: Path) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260526",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_date="2026-05-26",
    )

    assert not result.ready
    assert result.ready_code_count == 1
    assert result.missing_file_codes == ("000300.SH",)
    assert result.missing_trade_date_codes == ()


def test_index_daily_raw_file_readiness_reports_missing_trade_date(tmp_path: Path) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260526",))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260525",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_date="2026-05-26",
    )

    assert not result.ready
    assert result.ready_code_count == 1
    assert result.missing_file_codes == ()
    assert result.missing_trade_date_codes == ("000300.SH",)


def test_index_daily_raw_file_readiness_empty_registered_codes_not_ready(
    tmp_path: Path,
) -> None:
    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=(),
        trade_date="2026-05-26",
    )

    assert not result.ready
    assert result.registered_code_count == 0
    assert result.ready_code_count == 0


def test_index_daily_raw_file_readiness_reports_scan_errors(tmp_path: Path) -> None:
    _write_raw_index_daily_file_without_trade_date(tmp_path, "000001.SH")

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH",),
        trade_date="2026-05-26",
    )

    assert not result.ready
    assert result.scan_error_code
    assert result.scan_error
