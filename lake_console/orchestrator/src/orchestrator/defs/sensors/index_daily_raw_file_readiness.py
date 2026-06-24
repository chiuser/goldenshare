"""Raw index daily file readiness checks for silver sensor gates."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_SAMPLE_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_index_daily_path, raw_index_daily_by_code_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_DAILY_SCHEMA

MAX_RAW_GAP_SAMPLE_COUNT = 500
RAW_GAP_AUDIT_TRADE_DAY_LIMIT = 10
RAW_INDEX_DAILY_READINESS_TRADE_DAY_LIMIT = 10
RAW_INDEX_DAILY_FILE_CONTRACT_CHECK = "raw_index_daily_file_contract_check"
RAW_INDEX_DAILY_CODE_COVERAGE_CHECK = "raw_index_daily_code_coverage_check"
_RAW_INDEX_DAILY_COLUMN_TYPES = {
    column.name: column.type for column in RAW_INDEX_DAILY_SCHEMA
}


@dataclass(frozen=True)
class IndexDailyRawFileReadiness:
    trade_date: str
    registered_code_count: int
    ready_code_count: int
    missing_file_codes: tuple[str, ...]
    missing_trade_date_codes: tuple[str, ...]
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.scan_error is None
            and self.registered_code_count > 0
            and self.ready_code_count == self.registered_code_count
        )

    @property
    def missing_file_count(self) -> int:
        return len(self.missing_file_codes)

    @property
    def missing_trade_date_count(self) -> int:
        return len(self.missing_trade_date_codes)


@dataclass(frozen=True)
class IndexDailyRawGapAudit:
    trade_dates: tuple[str, ...]
    registered_code_count: int
    trade_date_count: int
    expected_pair_count: int
    ready_pair_count: int
    missing_file_codes: tuple[str, ...]
    missing_trade_date_pair_count: int
    missing_pair_count: int
    first_missing_trade_date: str | None
    first_missing_code_count: int
    first_missing_codes: tuple[str, ...]
    missing_pair_samples: tuple[tuple[str, str], ...]
    raw_started_code_count: int = 0
    no_raw_history_codes: tuple[str, ...] = ()
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.scan_error is None
            and self.registered_code_count > 0
            and self.trade_date_count > 0
            and self.missing_pair_count == 0
        )

    @property
    def missing_file_count(self) -> int:
        return len(self.missing_file_codes)

    @property
    def no_raw_history_count(self) -> int:
        return len(self.no_raw_history_codes)


def _values_table_sql(values: tuple[str, ...], column_name: str) -> str:
    if not values:
        return f"(SELECT CAST(NULL AS VARCHAR) AS {column_name} WHERE FALSE)"
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS values_table({column_name})"


def _trade_dates_table_sql(trade_dates: tuple[str, ...]) -> str:
    if not trade_dates:
        return (
            "(SELECT CAST(NULL AS VARCHAR) AS trade_date, "
            "CAST(NULL AS VARCHAR) AS compact_trade_date WHERE FALSE)"
        )
    rows = ", ".join(
        f"({duckdb_string(trade_date)}, {duckdb_string(trade_date.replace('-', ''))})"
        for trade_date in trade_dates
    )
    return f"(VALUES {rows}) AS values_table(trade_date, compact_trade_date)"


def _raw_files_query(paths: tuple[Path, ...]) -> str:
    path_values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_values}], hive_partitioning=false, union_by_name=true)"


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


def _empty_observed_raw_sql() -> str:
    return """
    SELECT
      CAST(NULL AS VARCHAR) AS ts_code,
      CAST(NULL AS VARCHAR) AS compact_trade_date
    WHERE FALSE
    """


def _observed_raw_sql(
    paths: tuple[Path, ...],
    *,
    filter_to_target_dates: bool,
) -> str:
    if not paths:
        return _empty_observed_raw_sql()
    where_clause = ""
    if filter_to_target_dates:
        where_clause = """
    WHERE CAST(trade_date AS VARCHAR) IN (
      SELECT compact_trade_date FROM target_dates
    )
        """
    return f"""
    SELECT DISTINCT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS VARCHAR) AS compact_trade_date
    FROM {_raw_files_query(paths)}
    {where_clause}
    """


def _continuity_expected_pairs_sql(*, use_index_basic: bool) -> str:
    join_clause = ""
    where_clause = ""
    if use_index_basic:
        join_clause = """
        LEFT JOIN index_basic
          ON raw_bounds.ts_code = index_basic.ts_code
        """
        where_clause = """
        WHERE (index_basic.exp_date IS NULL
               OR index_basic.exp_date > target_dates.trade_date_value)
        """
    return f"""
    SELECT DISTINCT
      target_dates.trade_date,
      target_dates.compact_trade_date,
      raw_bounds.ts_code
    FROM target_dates
    INNER JOIN raw_bounds
      ON raw_bounds.raw_start_compact_trade_date IS NOT NULL
     AND raw_bounds.raw_start_compact_trade_date <= target_dates.compact_trade_date
    {join_clause}
    {where_clause}
    """


def _target_presence_expected_codes_sql(*, use_index_basic: bool) -> str:
    join_clause = ""
    where_clause = ""
    if use_index_basic:
        join_clause = """
        LEFT JOIN index_basic
          ON registered_codes.ts_code = index_basic.ts_code
        """
        where_clause = """
        WHERE (index_basic.exp_date IS NULL
               OR index_basic.exp_date > target_dates.trade_date_value)
        """
    return f"""
    SELECT DISTINCT registered_codes.ts_code
    FROM registered_codes
    CROSS JOIN target_dates
    {join_clause}
    {where_clause}
    """


def audit_index_daily_raw_gaps(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_dates: tuple[str, ...],
    index_basic_path: Path | None = None,
    sample_limit: int = MAX_RAW_GAP_SAMPLE_COUNT,
) -> IndexDailyRawGapAudit:
    """Audit local raw index daily continuity after each code's first raw date."""

    registered_codes = tuple(sorted(set(registered_index_codes)))
    target_trade_dates = tuple(sorted(set(trade_dates)))
    sample_limit = max(1, sample_limit)
    raw_paths_by_code = {
        index_code: raw_index_daily_by_code_path(lake_root_path, index_code)
        for index_code in registered_codes
    }
    raw_missing_file_codes = tuple(
        index_code
        for index_code, raw_path in raw_paths_by_code.items()
        if not raw_path.exists()
    )
    existing_paths = tuple(
        raw_path for raw_path in raw_paths_by_code.values() if raw_path.exists()
    )
    expected_pair_count = len(registered_codes) * len(target_trade_dates)

    try:
        with connect_configured_duckdb() as connection:
            use_index_basic = index_basic_path is not None
            if index_basic_path is not None and not index_basic_path.exists():
                raise FileNotFoundError(
                    f"Missing silver index basic file for raw gap audit: {index_basic_path}"
                )
            connection.execute(
                f"""
                CREATE TEMP TABLE registered_codes AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code
                FROM {_values_table_sql(registered_codes, "ts_code")}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE target_dates AS
                SELECT
                  CAST(trade_date AS VARCHAR) AS trade_date,
                  CAST(compact_trade_date AS VARCHAR) AS compact_trade_date,
                  CAST(trade_date AS DATE) AS trade_date_value
                FROM {_trade_dates_table_sql(target_trade_dates)}
                """
            )
            if index_basic_path is not None:
                connection.execute(
                    f"""
                    CREATE TEMP TABLE index_basic AS
                    SELECT
                      CAST(ts_code AS VARCHAR) AS ts_code,
                      CAST(exp_date AS DATE) AS exp_date
                    FROM read_parquet(
                      {duckdb_string(index_basic_path)},
                      hive_partitioning=false,
                      union_by_name=true
                    )
                    """
                )
            connection.execute(
                f"""
                CREATE TEMP TABLE raw_missing_file_codes AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code
                FROM {_values_table_sql(raw_missing_file_codes, "ts_code")}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE observed_raw_index_daily AS
                {_observed_raw_sql(existing_paths, filter_to_target_dates=False)}
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE raw_bounds AS
                SELECT
                  registered_codes.ts_code,
                  min(observed.compact_trade_date) AS raw_start_compact_trade_date
                FROM registered_codes
                LEFT JOIN observed_raw_index_daily observed
                  ON registered_codes.ts_code = observed.ts_code
                GROUP BY registered_codes.ts_code
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE expected_pairs AS
                {_continuity_expected_pairs_sql(use_index_basic=use_index_basic)}
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE missing_pairs AS
                SELECT expected_pairs.trade_date, expected_pairs.ts_code
                FROM expected_pairs
                LEFT JOIN observed_raw_index_daily observed
                  ON expected_pairs.ts_code = observed.ts_code
                 AND expected_pairs.compact_trade_date = observed.compact_trade_date
                WHERE observed.ts_code IS NULL
                """
            )
            no_raw_history_codes = tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT ts_code
                    FROM raw_bounds
                    WHERE raw_start_compact_trade_date IS NULL
                    ORDER BY ts_code
                    """
                ).fetchall()
            )
            raw_started_code_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM raw_bounds
                    WHERE raw_start_compact_trade_date IS NOT NULL
                    """
                ).fetchone()[0]
            )
            expected_pair_count = int(
                connection.execute("SELECT count(*) FROM expected_pairs").fetchone()[0]
            )
            ready_pair_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM expected_pairs
                    INNER JOIN observed_raw_index_daily observed
                      ON expected_pairs.ts_code = observed.ts_code
                     AND expected_pairs.compact_trade_date = observed.compact_trade_date
                    """
                ).fetchone()[0]
            )
            missing_pair_count = int(
                connection.execute("SELECT count(*) FROM missing_pairs").fetchone()[0]
            )
            missing_trade_date_pair_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM missing_pairs
                    """
                ).fetchone()[0]
            )
            first_missing_row = connection.execute(
                """
                SELECT trade_date
                FROM missing_pairs
                ORDER BY trade_date, ts_code
                LIMIT 1
                """
            ).fetchone()
            first_missing_trade_date = first_missing_row[0] if first_missing_row else None
            if first_missing_trade_date is None:
                first_missing_code_count = 0
                first_missing_codes = ()
            else:
                first_missing_code_count = int(
                    connection.execute(
                        """
                        SELECT count(*)
                        FROM missing_pairs
                        WHERE trade_date = ?
                        """,
                        [first_missing_trade_date],
                    ).fetchone()[0]
                )
                first_missing_codes = tuple(
                    row[0]
                    for row in connection.execute(
                        f"""
                        SELECT ts_code
                        FROM missing_pairs
                        WHERE trade_date = ?
                        ORDER BY ts_code
                        LIMIT {sample_limit}
                        """,
                        [first_missing_trade_date],
                    ).fetchall()
                )
            missing_pair_samples = tuple(
                (row[0], row[1])
                for row in connection.execute(
                    f"""
                    SELECT trade_date, ts_code
                    FROM missing_pairs
                    ORDER BY trade_date, ts_code
                    LIMIT {sample_limit}
                    """
                ).fetchall()
            )
    except Exception as exc:
        return IndexDailyRawGapAudit(
            trade_dates=target_trade_dates,
            registered_code_count=len(registered_codes),
            trade_date_count=len(target_trade_dates),
            expected_pair_count=expected_pair_count,
            ready_pair_count=0,
            missing_file_codes=(),
            missing_trade_date_pair_count=0,
            missing_pair_count=expected_pair_count,
            first_missing_trade_date=target_trade_dates[0]
            if target_trade_dates
            else None,
            first_missing_code_count=0,
            first_missing_codes=(),
            missing_pair_samples=(),
            raw_started_code_count=0,
            no_raw_history_codes=raw_missing_file_codes,
            scan_error_code=type(exc).__name__,
            scan_error=str(exc),
        )

    return IndexDailyRawGapAudit(
        trade_dates=target_trade_dates,
        registered_code_count=len(registered_codes),
        trade_date_count=len(target_trade_dates),
        expected_pair_count=expected_pair_count,
        ready_pair_count=ready_pair_count,
        missing_file_codes=(),
        missing_trade_date_pair_count=missing_trade_date_pair_count,
        missing_pair_count=missing_pair_count,
        first_missing_trade_date=first_missing_trade_date,
        first_missing_code_count=first_missing_code_count,
        first_missing_codes=first_missing_codes,
        missing_pair_samples=missing_pair_samples,
        raw_started_code_count=raw_started_code_count,
        no_raw_history_codes=no_raw_history_codes,
    )


def check_index_daily_raw_files_for_trade_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_date: str,
    index_basic_path: Path | None = None,
) -> IndexDailyRawFileReadiness:
    """Check raw by-code files directly instead of inferring readiness from run tags."""

    registered_codes = tuple(sorted(set(registered_index_codes)))
    raw_paths_by_code = {
        index_code: raw_index_daily_by_code_path(lake_root_path, index_code)
        for index_code in registered_codes
    }
    raw_missing_file_codes = tuple(
        index_code
        for index_code, raw_path in raw_paths_by_code.items()
        if not raw_path.exists()
    )
    existing_paths = tuple(
        raw_path for raw_path in raw_paths_by_code.values() if raw_path.exists()
    )

    try:
        with connect_configured_duckdb() as connection:
            use_index_basic = index_basic_path is not None
            if index_basic_path is not None and not index_basic_path.exists():
                raise FileNotFoundError(
                    "Missing silver index basic file for target raw presence check: "
                    f"{index_basic_path}"
                )
            connection.execute(
                f"""
                CREATE TEMP TABLE registered_codes AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code
                FROM {_values_table_sql(registered_codes, "ts_code")}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE target_dates AS
                SELECT
                  CAST(trade_date AS VARCHAR) AS trade_date,
                  CAST(compact_trade_date AS VARCHAR) AS compact_trade_date,
                  CAST(trade_date AS DATE) AS trade_date_value
                FROM {_trade_dates_table_sql((trade_date,))}
                """
            )
            if index_basic_path is not None:
                connection.execute(
                    f"""
                    CREATE TEMP TABLE index_basic AS
                    SELECT
                      CAST(ts_code AS VARCHAR) AS ts_code,
                      CAST(exp_date AS DATE) AS exp_date
                    FROM read_parquet(
                      {duckdb_string(index_basic_path)},
                      hive_partitioning=false,
                      union_by_name=true
                    )
                    """
                )
            connection.execute(
                f"""
                CREATE TEMP TABLE raw_missing_file_codes AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code
                FROM {_values_table_sql(raw_missing_file_codes, "ts_code")}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE expected_codes AS
                {_target_presence_expected_codes_sql(use_index_basic=use_index_basic)}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE observed_target_raw AS
                {_observed_raw_sql(existing_paths, filter_to_target_dates=True)}
                """
            )
            missing_file_codes = tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT expected_codes.ts_code
                    FROM expected_codes
                    INNER JOIN raw_missing_file_codes
                      ON expected_codes.ts_code = raw_missing_file_codes.ts_code
                    ORDER BY expected_codes.ts_code
                    """
                ).fetchall()
            )
            missing_trade_date_codes = tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT expected_codes.ts_code
                    FROM expected_codes
                    LEFT JOIN observed_target_raw observed
                      ON expected_codes.ts_code = observed.ts_code
                    LEFT JOIN raw_missing_file_codes
                      ON expected_codes.ts_code = raw_missing_file_codes.ts_code
                    WHERE observed.ts_code IS NULL
                      AND raw_missing_file_codes.ts_code IS NULL
                    ORDER BY expected_codes.ts_code
                    """
                ).fetchall()
            )
            expected_code_count = int(
                connection.execute("SELECT count(*) FROM expected_codes").fetchone()[0]
            )
    except Exception as exc:
        return IndexDailyRawFileReadiness(
            trade_date=trade_date,
            registered_code_count=len(registered_codes),
            ready_code_count=0,
            missing_file_codes=raw_missing_file_codes,
            missing_trade_date_codes=(),
            scan_error_code=type(exc).__name__,
            scan_error=str(exc),
        )

    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=expected_code_count,
        ready_code_count=max(
            0,
            expected_code_count
            - len(missing_file_codes)
            - len(missing_trade_date_codes),
        ),
        missing_file_codes=missing_file_codes,
        missing_trade_date_codes=missing_trade_date_codes,
    )
