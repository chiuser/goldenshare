"""Raw index daily file readiness checks for silver sensor gates."""

from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.resources import DuckDBResource

MAX_RAW_GAP_SAMPLE_COUNT = 500
RAW_GAP_AUDIT_TRADE_DAY_LIMIT = 60


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
        with duckdb.connect() as connection:
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
        with duckdb.connect() as connection:
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
