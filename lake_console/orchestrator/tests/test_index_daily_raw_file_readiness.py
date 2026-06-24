from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_index_daily_path,
    raw_index_daily_by_code_path,
    silver_index_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    audit_index_daily_raw_gaps,
    check_index_daily_raw_files_for_trade_date,
    raw_index_daily_lake_readiness_for_trade_dates,
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


def _write_index_basic_file(
    root: Path,
    rows: tuple[tuple[str, str, str | None], ...],
) -> Path:
    path = silver_index_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "("
        f"{duckdb_string(ts_code)}, "
        f"DATE {duckdb_string(list_date)}, "
        f"{'NULL' if exp_date is None else 'DATE ' + duckdb_string(exp_date)}"
        ")"
        for ts_code, list_date, exp_date in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, list_date, exp_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


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


def test_index_daily_raw_gap_audit_reports_earliest_middle_gap(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260601", "20260602"))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260529", "20260602"))

    result = audit_index_daily_raw_gaps(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_dates=("2026-06-01", "2026-06-02"),
    )

    assert not result.ready
    assert result.expected_pair_count == 4
    assert result.ready_pair_count == 3
    assert result.missing_pair_count == 1
    assert result.missing_trade_date_pair_count == 1
    assert result.first_missing_trade_date == "2026-06-01"
    assert result.first_missing_code_count == 1
    assert result.first_missing_codes == ("000300.SH",)
    assert result.missing_pair_samples == (("2026-06-01", "000300.SH"),)


def test_index_daily_raw_gap_audit_reports_no_raw_history_without_blocking(
    tmp_path: Path,
) -> None:
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260601", "20260602"))

    result = audit_index_daily_raw_gaps(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_dates=("2026-06-01", "2026-06-02"),
    )

    assert result.ready
    assert result.raw_started_code_count == 1
    assert result.no_raw_history_codes == ("000300.SH",)
    assert result.no_raw_history_count == 1
    assert result.missing_file_codes == ()
    assert result.missing_file_count == 0
    assert result.expected_pair_count == 2
    assert result.ready_pair_count == 2
    assert result.missing_pair_count == 0
    assert result.missing_trade_date_pair_count == 0
    assert result.first_missing_trade_date is None
    assert result.first_missing_codes == ()


def test_index_daily_raw_gap_audit_uses_raw_start_and_exp_date_not_list_date(
    tmp_path: Path,
) -> None:
    index_basic_path = _write_index_basic_file(
        tmp_path,
        (
            ("000001.SH", "2000-01-01", None),
            ("000300.SH", "2026-06-02", None),
            ("000999.SH", "2026-06-03", None),
            ("000888.SH", "2000-01-01", "2026-06-01"),
        ),
    )
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260601", "20260602"))
    _write_raw_index_daily_file(tmp_path, "000300.SH", ("20260602",))

    result = audit_index_daily_raw_gaps(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH", "000888.SH", "000999.SH"),
        trade_dates=("2026-06-01", "2026-06-02"),
        index_basic_path=index_basic_path,
    )

    assert result.ready
    assert result.expected_pair_count == 3
    assert result.ready_pair_count == 3
    assert result.missing_file_codes == ()
    assert result.no_raw_history_codes == ("000888.SH", "000999.SH")
    assert result.missing_pair_count == 0


def test_index_daily_raw_gap_audit_does_not_expect_before_local_raw_start(
    tmp_path: Path,
) -> None:
    index_basic_path = _write_index_basic_file(
        tmp_path,
        (("950228.SH", "2024-08-23", None),),
    )
    _write_raw_index_daily_file(tmp_path, "950228.SH", ("20250718",))

    result = audit_index_daily_raw_gaps(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("950228.SH",),
        trade_dates=("2024-08-23", "2025-07-17", "2025-07-18"),
        index_basic_path=index_basic_path,
    )

    assert result.ready
    assert result.expected_pair_count == 1
    assert result.ready_pair_count == 1
    assert result.missing_pair_count == 0


def test_index_daily_raw_file_readiness_ignores_list_date_for_target_presence(
    tmp_path: Path,
) -> None:
    index_basic_path = _write_index_basic_file(
        tmp_path,
        (
            ("000001.SH", "2000-01-01", None),
            ("000300.SH", "2026-06-03", None),
        ),
    )
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_date="2026-06-02",
        index_basic_path=index_basic_path,
    )

    assert not result.ready
    assert result.registered_code_count == 2
    assert result.ready_code_count == 1
    assert result.missing_file_codes == ("000300.SH",)
    assert result.missing_trade_date_codes == ()


def test_index_daily_raw_file_readiness_excludes_expired_codes(
    tmp_path: Path,
) -> None:
    index_basic_path = _write_index_basic_file(
        tmp_path,
        (
            ("000001.SH", "2000-01-01", None),
            ("000300.SH", "2005-04-08", "2026-06-01"),
        ),
    )
    _write_raw_index_daily_file(tmp_path, "000001.SH", ("20260602",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("000001.SH", "000300.SH"),
        trade_date="2026-06-02",
        index_basic_path=index_basic_path,
    )

    assert result.ready
    assert result.registered_code_count == 1
    assert result.ready_code_count == 1
    assert result.missing_file_codes == ()
    assert result.missing_trade_date_codes == ()


def test_index_daily_raw_file_readiness_still_blocks_target_date_before_raw_start(
    tmp_path: Path,
) -> None:
    index_basic_path = _write_index_basic_file(
        tmp_path,
        (("950228.SH", "2024-08-23", None),),
    )
    _write_raw_index_daily_file(tmp_path, "950228.SH", ("20250718",))

    result = check_index_daily_raw_files_for_trade_date(
        lake_root_path=tmp_path,
        duckdb=DuckDBResource(),
        registered_index_codes=("950228.SH",),
        trade_date="2025-07-17",
        index_basic_path=index_basic_path,
    )

    assert not result.ready
    assert result.registered_code_count == 1
    assert result.ready_code_count == 0
    assert result.missing_file_codes == ()
    assert result.missing_trade_date_codes == ("950228.SH",)


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

    def test_all_codes_ready(self) -> None:
        self._run_with_tmp_path(test_index_daily_raw_file_readiness_all_codes_ready)

    def test_reports_missing_files(self) -> None:
        self._run_with_tmp_path(test_index_daily_raw_file_readiness_reports_missing_files)

    def test_reports_missing_trade_date(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_file_readiness_reports_missing_trade_date
        )

    def test_empty_registered_codes_not_ready(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_file_readiness_empty_registered_codes_not_ready
        )

    def test_reports_scan_errors(self) -> None:
        self._run_with_tmp_path(test_index_daily_raw_file_readiness_reports_scan_errors)

    def test_reports_earliest_middle_gap(self) -> None:
        self._run_with_tmp_path(test_index_daily_raw_gap_audit_reports_earliest_middle_gap)

    def test_reports_no_raw_history_without_blocking(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_gap_audit_reports_no_raw_history_without_blocking
        )

    def test_uses_raw_start_and_exp_date_not_list_date(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_gap_audit_uses_raw_start_and_exp_date_not_list_date
        )

    def test_does_not_expect_before_local_raw_start(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_gap_audit_does_not_expect_before_local_raw_start
        )

    def test_ignores_list_date_for_target_presence(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_file_readiness_ignores_list_date_for_target_presence
        )

    def test_excludes_expired_codes(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_file_readiness_excludes_expired_codes
        )

    def test_still_blocks_target_date_before_raw_start(self) -> None:
        self._run_with_tmp_path(
            test_index_daily_raw_file_readiness_still_blocks_target_date_before_raw_start
        )

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
