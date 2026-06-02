"""Raw index daily file readiness checks for silver sensor gates."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.resources import DuckDBResource

MAX_RAW_GAP_SAMPLE_COUNT = 500


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


def _empty_observed_raw_sql() -> str:
    return """
    SELECT
      CAST(NULL AS VARCHAR) AS ts_code,
      CAST(NULL AS VARCHAR) AS compact_trade_date
    WHERE FALSE
    """


def _observed_raw_sql(paths: tuple[Path, ...]) -> str:
    if not paths:
        return _empty_observed_raw_sql()
    return f"""
    SELECT DISTINCT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS VARCHAR) AS compact_trade_date
    FROM {_raw_files_query(paths)}
    WHERE CAST(trade_date AS VARCHAR) IN (
      SELECT compact_trade_date FROM target_dates
    )
    """


def audit_index_daily_raw_gaps(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_dates: tuple[str, ...],
    sample_limit: int = MAX_RAW_GAP_SAMPLE_COUNT,
) -> IndexDailyRawGapAudit:
    """Audit raw index daily coverage with DuckDB set operations."""

    registered_codes = tuple(sorted(set(registered_index_codes)))
    target_trade_dates = tuple(sorted(set(trade_dates)))
    sample_limit = max(1, sample_limit)
    raw_paths_by_code = {
        index_code: raw_index_daily_by_code_path(lake_root_path, index_code)
        for index_code in registered_codes
    }
    missing_file_codes = tuple(
        index_code
        for index_code, raw_path in raw_paths_by_code.items()
        if not raw_path.exists()
    )
    existing_paths = tuple(
        raw_path for raw_path in raw_paths_by_code.values() if raw_path.exists()
    )
    expected_pair_count = len(registered_codes) * len(target_trade_dates)

    try:
        with duckdb.connect() as connection:
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
                  CAST(compact_trade_date AS VARCHAR) AS compact_trade_date
                FROM {_trade_dates_table_sql(target_trade_dates)}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE missing_file_codes AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code
                FROM {_values_table_sql(missing_file_codes, "ts_code")}
                """
            )
            connection.execute(
                f"""
                CREATE TEMP TABLE observed_raw_index_daily AS
                {_observed_raw_sql(existing_paths)}
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE expected_pairs AS
                SELECT
                  target_dates.trade_date,
                  target_dates.compact_trade_date,
                  registered_codes.ts_code
                FROM target_dates
                CROSS JOIN registered_codes
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
                    LEFT JOIN missing_file_codes USING (ts_code)
                    WHERE missing_file_codes.ts_code IS NULL
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
            missing_file_codes=missing_file_codes,
            missing_trade_date_pair_count=0,
            missing_pair_count=expected_pair_count,
            first_missing_trade_date=target_trade_dates[0]
            if target_trade_dates
            else None,
            first_missing_code_count=0,
            first_missing_codes=(),
            missing_pair_samples=(),
            scan_error_code=type(exc).__name__,
            scan_error=str(exc),
        )

    return IndexDailyRawGapAudit(
        trade_dates=target_trade_dates,
        registered_code_count=len(registered_codes),
        trade_date_count=len(target_trade_dates),
        expected_pair_count=expected_pair_count,
        ready_pair_count=ready_pair_count,
        missing_file_codes=missing_file_codes,
        missing_trade_date_pair_count=missing_trade_date_pair_count,
        missing_pair_count=missing_pair_count,
        first_missing_trade_date=first_missing_trade_date,
        first_missing_code_count=first_missing_code_count,
        first_missing_codes=first_missing_codes,
        missing_pair_samples=missing_pair_samples,
    )


def check_index_daily_raw_files_for_trade_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: tuple[str, ...],
    trade_date: str,
) -> IndexDailyRawFileReadiness:
    """Check raw by-code files directly instead of inferring readiness from run tags."""

    registered_codes = tuple(sorted(set(registered_index_codes)))
    audit = audit_index_daily_raw_gaps(
        lake_root_path=lake_root_path,
        duckdb=duckdb,
        registered_index_codes=registered_codes,
        trade_dates=(trade_date,),
        sample_limit=max(len(registered_codes), 1),
    )
    missing_file_codes = audit.missing_file_codes
    missing_trade_date_codes = tuple(
        ts_code
        for missing_trade_date, ts_code in audit.missing_pair_samples
        if missing_trade_date == trade_date and ts_code not in missing_file_codes
    )

    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=len(registered_codes),
        ready_code_count=max(
            0,
            len(registered_codes)
            - len(missing_file_codes)
            - len(missing_trade_date_codes),
        ),
        missing_file_codes=missing_file_codes,
        missing_trade_date_codes=missing_trade_date_codes,
        scan_error_code=audit.scan_error_code,
        scan_error=audit.scan_error,
    )
