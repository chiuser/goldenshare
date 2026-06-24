"""Raw index daily file readiness checks for silver sensor gates."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_SAMPLE_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_index_daily_path
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_DAILY_SCHEMA

RAW_INDEX_DAILY_READINESS_TRADE_DAY_LIMIT = 10
RAW_INDEX_DAILY_FILE_CONTRACT_CHECK = "raw_index_daily_file_contract_check"
RAW_INDEX_DAILY_CODE_COVERAGE_CHECK = "raw_index_daily_code_coverage_check"
_RAW_INDEX_DAILY_COLUMN_TYPES = {
    column.name: column.type for column in RAW_INDEX_DAILY_SCHEMA
}

def _values_table_sql(values: tuple[str, ...], column_name: str) -> str:
    if not values:
        return f"(SELECT CAST(NULL AS VARCHAR) AS {column_name} WHERE FALSE)"
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS values_table({column_name})"


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _raw_by_date_missing_file_status(
    *,
    trade_date: str,
    file_path: Path,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="missing_raw_index_daily_file",
        missing_check_names=(RAW_INDEX_DAILY_FILE_CONTRACT_CHECK,),
        missing_file_paths=(str(file_path),),
        summary={"file_path": str(file_path)},
    )


def _raw_by_date_failed_status(
    *,
    trade_date: str,
    reason: str,
    failed_check_names: Sequence[str],
    summary: Mapping[str, object],
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason=reason,
        failed_check_names=tuple(dict.fromkeys(failed_check_names)),
        summary=dict(summary),
    )


def _raw_by_date_ready_status(
    *,
    trade_date: str,
    summary: Mapping[str, object],
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
        summary=dict(summary),
    )


def _raw_by_date_scan_error_status(
    *,
    trade_date: str,
    file_path: Path,
    error: Exception,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=file_path.exists(),
        checks_passed=False,
        reason="scan_error",
        failed_check_names=("raw_index_daily_lake_readiness_scan_error",),
        summary={
            "file_path": str(file_path),
            "scan_error_code": type(error).__name__,
            "scan_error": str(error),
        },
    )


def _parquet_columns_and_types(connection, path: Path) -> tuple[list[str], dict[str, str]]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [str(row[0]) for row in rows], {str(row[0]): str(row[1]).upper() for row in rows}


def _raw_by_date_status_for_trade_date(
    connection,
    *,
    lake_root_path: Path,
    trade_date: str,
    expected_index_codes: tuple[str, ...],
    sample_limit: int,
) -> ContinuityDateReadiness:
    raw_path = raw_index_daily_path(lake_root_path, trade_date)
    if not raw_path.exists():
        return _raw_by_date_missing_file_status(
            trade_date=trade_date,
            file_path=raw_path,
        )

    expected_trade_date = trade_date.replace("-", "")
    expected_codes_sql = _values_table_sql(expected_index_codes, "ts_code")
    observed_codes_sql = f"""
    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
    FROM {read_parquet(raw_path, hive_partitioning=False)}
    """
    columns, column_types = _parquet_columns_and_types(connection, raw_path)
    missing_columns = [
        column for column in INDEX_DAILY_RAW_COLUMNS if column not in columns
    ]
    unexpected_columns = [
        column for column in columns if column not in INDEX_DAILY_RAW_COLUMNS
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in _RAW_INDEX_DAILY_COLUMN_TYPES.items()
        if column in column_types and column_types[column] != expected_type
    }
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(raw_path, hive_partitioning=False)}"
        ).fetchone()[0]
    )
    null_key_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(raw_path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR trade_date IS NULL
               OR trim(CAST(trade_date AS VARCHAR)) = ''
            """
        ).fetchone()[0]
    )
    date_mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(raw_path, hive_partitioning=False)}
            WHERE CAST(trade_date AS VARCHAR) != {duckdb_string(expected_trade_date)}
            """
        ).fetchone()[0]
    )
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(raw_path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    summary: dict[str, object] = {
        "file_path": str(raw_path),
        "row_count": row_count,
        "observed_columns": columns,
        "column_types": column_types,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
        "null_key_count": null_key_count,
        "date_mismatch_count": date_mismatch_count,
        "duplicate_key_count": duplicate_key_count,
    }
    if (
        row_count <= 0
        or missing_columns
        or unexpected_columns
        or type_mismatches
        or null_key_count
        or date_mismatch_count
        or duplicate_key_count
    ):
        return _raw_by_date_failed_status(
            trade_date=trade_date,
            reason="file_contract_failed",
            failed_check_names=(RAW_INDEX_DAILY_FILE_CONTRACT_CHECK,),
            summary=summary,
        )

    coverage_row = connection.execute(
        f"""
        WITH expected AS (
          SELECT ts_code FROM {expected_codes_sql}
        ),
        observed AS (
          {observed_codes_sql}
        )
        SELECT
          (SELECT count(*) FROM expected) AS expected_code_count,
          (SELECT count(*) FROM observed) AS observed_code_count,
          (
            SELECT count(*)
            FROM expected
            LEFT JOIN observed USING (ts_code)
            WHERE observed.ts_code IS NULL
          ) AS missing_code_count,
          (
            SELECT count(*)
            FROM observed
            LEFT JOIN expected USING (ts_code)
            WHERE expected.ts_code IS NULL
          ) AS extra_code_count
        """
    ).fetchone()
    missing_rows = connection.execute(
        f"""
        WITH expected AS (
          SELECT ts_code FROM {expected_codes_sql}
        ),
        observed AS (
          {observed_codes_sql}
        )
        SELECT expected.ts_code
        FROM expected
        LEFT JOIN observed USING (ts_code)
        WHERE observed.ts_code IS NULL
        ORDER BY expected.ts_code
        LIMIT {int(sample_limit)}
        """
    ).fetchall()
    extra_rows = connection.execute(
        f"""
        WITH expected AS (
          SELECT ts_code FROM {expected_codes_sql}
        ),
        observed AS (
          {observed_codes_sql}
        )
        SELECT observed.ts_code
        FROM observed
        LEFT JOIN expected USING (ts_code)
        WHERE expected.ts_code IS NULL
        ORDER BY observed.ts_code
        LIMIT {int(sample_limit)}
        """
    ).fetchall()
    expected_count = int(coverage_row[0])
    observed_count = int(coverage_row[1])
    missing_count = int(coverage_row[2])
    extra_count = int(coverage_row[3])
    summary.update(
        {
            "expected_code_count": expected_count,
            "observed_code_count": observed_count,
            "missing_code_count": missing_count,
            "extra_code_count": extra_count,
            "missing_code_samples": [str(row[0]) for row in missing_rows],
            "extra_code_samples": [str(row[0]) for row in extra_rows],
        }
    )
    if missing_count or extra_count:
        return _raw_by_date_failed_status(
            trade_date=trade_date,
            reason="code_coverage_failed",
            failed_check_names=(RAW_INDEX_DAILY_CODE_COVERAGE_CHECK,),
            summary=summary,
        )
    return _raw_by_date_ready_status(trade_date=trade_date, summary=summary)


def raw_index_daily_lake_readiness_for_trade_dates(
    connection,
    *,
    lake_root_path: Path,
    trade_dates: Sequence[str],
    expected_index_codes: Sequence[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    target_trade_dates = tuple(sorted(set(str(value) for value in trade_dates)))
    if len(target_trade_dates) > RAW_INDEX_DAILY_READINESS_TRADE_DAY_LIMIT:
        raise ValueError(
            "raw_index_daily readiness hot path is limited to "
            f"{RAW_INDEX_DAILY_READINESS_TRADE_DAY_LIMIT} trade dates: "
            f"{len(target_trade_dates)}."
        )
    expected_codes = tuple(sorted(set(str(code).strip() for code in expected_index_codes)))
    if not expected_codes or any(not code for code in expected_codes):
        raise ValueError("expected_index_codes must not be empty or blank.")
    sample_limit = max(1, int(sample_limit))

    statuses: dict[str, ContinuityDateReadiness] = {}
    scanned_file_count = 0
    for trade_date in target_trade_dates:
        raw_path = raw_index_daily_path(lake_root_path, trade_date)
        if raw_path.exists():
            scanned_file_count += 1
        try:
            statuses[trade_date] = _raw_by_date_status_for_trade_date(
                connection,
                lake_root_path=lake_root_path,
                trade_date=trade_date,
                expected_index_codes=expected_codes,
                sample_limit=sample_limit,
            )
        except Exception as error:  # noqa: BLE001 - sensor readiness must fail closed.
            statuses[trade_date] = _raw_by_date_scan_error_status(
                trade_date=trade_date,
                file_path=raw_path,
                error=error,
            )

    return ContinuityBatchReadiness(
        expected_trade_dates=target_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=scanned_file_count,
    )
