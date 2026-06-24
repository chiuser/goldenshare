"""Lake-file readiness helpers for stock minute hot-path sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.stk_mins import (
    STK_MINS_RAW_COLUMN_TYPES,
    STK_MINS_SILVER_COLUMN_TYPES,
)
from orchestrator.defs.checks.stk_mins_checks import (
    GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK,
    GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK,
    GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK,
    GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE,
    RAW_STK_MINS_CONTRACT_CHECK,
    RAW_STK_MINS_KEY_INTEGRITY_CHECK,
    RAW_STK_MINS_VALUE_DOMAIN_CHECK,
    SILVER_STK_MINS_CONTRACT_CHECK,
    SILVER_STK_MINS_KEY_INTEGRITY_CHECK,
    SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
    SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
    GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK,
    GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
    GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
    GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
    GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK,
    GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
    GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    GoldStkMinsQfqCheckCounts,
    GoldStkMinsQfqDerivedCheckCounts,
    _gold_qfq_counts_sql,
    _gold_qfq_derived_expected_paths,
    _gold_qfq_expected_paths,
    _gold_qfq_formula_counts_sql,
    _gold_qfq_schema_mismatch_count,
    _gold_qfq_year_paths,
    _read_parquet_paths,
    _row_count,
)
from orchestrator.defs.duckdb_sql import (
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_cny_stock_lifecycle_select,
)
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    raw_stk_mins_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_FREQS,
    STK_MINS_QFQ_NATIVE_FREQS,
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
    qfq_source_freq_for_derived_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    build_daily_qfq_coverage_sql,
    build_daily_qfq_select_sql,
    build_gold_stk_mins_qfq_derived_diagnostics_sql,
    build_gold_stk_mins_qfq_derived_select_sql,
    _derived_window_completion_predicate,
    _derived_window_rows_sql,
)


@dataclass(frozen=True)
class StkMinsDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...]
    missing_file_paths: tuple[str, ...]
    expected_file_count: int
    existing_file_count: int
    checked_row_count: int = 0
    failed_row_count: int = 0
    sample_rows: tuple[dict[str, object], ...] = ()

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "materialized": self.materialized,
            "checks_passed": self.checks_passed,
            "reason": self.reason,
            "failed_check_names": list(self.failed_check_names),
            "missing_file_paths": list(self.missing_file_paths),
            "expected_file_count": self.expected_file_count,
            "existing_file_count": self.existing_file_count,
            "checked_row_count": self.checked_row_count,
            "failed_row_count": self.failed_row_count,
            "sample_rows": list(self.sample_rows),
        }


@dataclass(frozen=True)
class StkMinsBatchReadiness:
    dataset: str
    expected_start_date: str | None
    expected_end_date: str | None
    expected_count: int
    freq_count: int
    elapsed_ms: float
    statuses_by_trade_date: Mapping[str, StkMinsDateReadiness]

    def status_for_trade_date(self, trade_date: str) -> StkMinsDateReadiness:
        status = self.statuses_by_trade_date.get(trade_date)
        if status is not None:
            return status
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=(
                f"{self.dataset} lake readiness status is missing for {trade_date}"
            ),
            failed_check_names=(f"{self.dataset}_lake_readiness_status_missing",),
            missing_file_paths=(),
            expected_file_count=self.freq_count,
            existing_file_count=0,
        )


@dataclass(frozen=True)
class _RawPathPlan:
    trade_date: str
    freq: int
    path: Path


@dataclass(frozen=True)
class _RawPathMetrics:
    row_count: int = 0
    freq_failed_count: int = 0
    date_failed_count: int = 0
    duplicate_failed_count: int = 0
    sanity_failed_count: int = 0

    @property
    def failed_row_count(self) -> int:
        return (
            self.freq_failed_count
            + self.date_failed_count
            + self.duplicate_failed_count
            + self.sanity_failed_count
        )


@dataclass(frozen=True)
class _SilverPathPlan:
    trade_date: str
    freq: int
    path: Path
    stock_daily_path: Path
    suspend_path: Path


@dataclass(frozen=True)
class _SilverPathMetrics:
    row_count: int = 0
    freq_partition_failed_count: int = 0
    duplicate_failed_count: int = 0
    price_failed_count: int = 0
    volume_amount_failed_count: int = 0
    exchange_failed_count: int = 0
    missing_stock_daily_code_count: int = 0
    full_day_suspend_failed_count: int = 0
    lifecycle_failed_count: int = 0

    @property
    def failed_row_count(self) -> int:
        return (
            self.freq_partition_failed_count
            + self.duplicate_failed_count
            + self.price_failed_count
            + self.volume_amount_failed_count
            + self.exchange_failed_count
            + self.missing_stock_daily_code_count
            + self.full_day_suspend_failed_count
            + self.lifecycle_failed_count
        )


@dataclass(frozen=True)
class _GoldQfqNativePathPlan:
    trade_date: str
    freq: int
    silver_path: Path
    trade_adj_factor_path: Path
    expected_gold_paths: tuple[Path, ...]
    existing_gold_paths: tuple[Path, ...]
    missing_paths: tuple[Path, ...]


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _normalize_freqs(freqs: Sequence[int]) -> tuple[int, ...]:
    return tuple(normalize_stk_mins_freq(freq) for freq in freqs)


def _expected_bounds(
    expected_trade_dates: Sequence[str],
) -> tuple[str | None, str | None]:
    if not expected_trade_dates:
        return None, None
    return expected_trade_dates[0], expected_trade_dates[-1]


def _raw_path_plans(
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    freqs: Sequence[int],
) -> tuple[_RawPathPlan, ...]:
    return tuple(
        _RawPathPlan(
            trade_date=trade_date,
            freq=freq,
            path=raw_stk_mins_path(lake_root, freq, trade_date),
        )
        for trade_date in expected_trade_dates
        for freq in freqs
    )


def _silver_path_plans(
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    freqs: Sequence[int],
) -> tuple[_SilverPathPlan, ...]:
    return tuple(
        _SilverPathPlan(
            trade_date=trade_date,
            freq=freq,
            path=silver_stk_mins_path(lake_root, freq, trade_date),
            stock_daily_path=silver_stock_daily_path(lake_root, trade_date),
            suspend_path=silver_stock_suspend_daily_path(lake_root, trade_date),
        )
        for trade_date in expected_trade_dates
        for freq in freqs
    )


def _describe_columns(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _schema_matches_contract(
    connection,
    path: Path,
    expected_schema: Mapping[str, str],
) -> bool:
    observed_schema = _describe_columns(connection, path)
    missing_columns = [
        column for column in expected_schema if column not in observed_schema
    ]
    type_mismatches = [
        column
        for column, expected_type in expected_schema.items()
        if observed_schema.get(column) != expected_type
    ]
    return not missing_columns and not type_mismatches


def _has_required_columns(
    connection,
    path: Path,
    required_columns: Sequence[str],
) -> bool:
    observed_columns = set(_describe_columns(connection, path))
    return all(column in observed_columns for column in required_columns)


def _schema_matches_raw_contract(connection, path: Path) -> bool:
    return _schema_matches_contract(connection, path, STK_MINS_RAW_COLUMN_TYPES)


def _schema_matches_silver_contract(connection, path: Path) -> bool:
    return _schema_matches_contract(connection, path, STK_MINS_SILVER_COLUMN_TYPES)


def _path_list_sql(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _values_sql(values: Sequence[str]) -> str:
    return ",\n".join(f"({duckdb_string(value)})" for value in values)


def _path_plan_values_sql(path_plans: Sequence[_RawPathPlan]) -> str:
    return ",\n".join(
        f"({duckdb_string(path_plan.path)}, "
        f"{duckdb_string(path_plan.trade_date)}, {int(path_plan.freq)})"
        for path_plan in path_plans
    )


def _silver_path_plan_values_sql(path_plans: Sequence[_SilverPathPlan]) -> str:
    return ",\n".join(
        f"({duckdb_string(path_plan.path)}, "
        f"{duckdb_string(path_plan.trade_date)}, "
        f"{int(path_plan.freq)}, "
        f"{duckdb_string(path_plan.stock_daily_path)}, "
        f"{duckdb_string(path_plan.suspend_path)})"
        for path_plan in path_plans
    )


def _raw_path_metrics(
    connection,
    path_plans: Sequence[_RawPathPlan],
) -> dict[Path, _RawPathMetrics]:
    if not path_plans:
        return {}

    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    path_values_sql = _path_plan_values_sql(path_plans)
    rows = connection.execute(
        f"""
        WITH path_plan(file_path, expected_trade_date, expected_freq) AS (
          VALUES {path_values_sql}
        ),
        raw_rows AS (
          SELECT
            filename AS file_path,
            path_plan.expected_trade_date,
            path_plan.expected_freq,
            ts_code,
            trade_time,
            freq,
            open,
            close,
            high,
            low,
            vol,
            amount,
            vwap
          FROM read_parquet(
            {path_list_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          ) AS raw_file
          INNER JOIN path_plan
            ON raw_file.filename = path_plan.file_path
        ),
        row_checks AS (
          SELECT
            file_path,
            count(*) AS row_count,
            sum(
              CASE WHEN CAST(freq AS INTEGER) != expected_freq THEN 1 ELSE 0 END
            ) AS freq_failed_count,
            sum(
              CASE
                WHEN CAST(trade_time AS DATE)
                  != CAST(expected_trade_date AS DATE)
                THEN 1 ELSE 0
              END
            ) AS date_failed_count,
            sum(
              CASE
                WHEN ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
                  OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                  OR vol IS NULL OR amount IS NULL OR vwap IS NULL
                  OR open < 0 OR close < 0 OR high < 0 OR low < 0
                  OR vol < 0 OR amount < 0 OR vwap < 0
                THEN 1 ELSE 0
              END
            ) AS sanity_failed_count
          FROM raw_rows
          GROUP BY file_path
        ),
        duplicate_checks AS (
          SELECT file_path, count(*) AS duplicate_failed_count
          FROM (
            SELECT file_path, ts_code, trade_time, count(*) AS duplicate_count
            FROM raw_rows
            GROUP BY file_path, ts_code, trade_time
            HAVING count(*) > 1
          )
          GROUP BY file_path
        )
        SELECT
          path_plan.file_path,
          coalesce(row_checks.row_count, 0) AS row_count,
          coalesce(row_checks.freq_failed_count, 0) AS freq_failed_count,
          coalesce(row_checks.date_failed_count, 0) AS date_failed_count,
          coalesce(duplicate_checks.duplicate_failed_count, 0)
            AS duplicate_failed_count,
          coalesce(row_checks.sanity_failed_count, 0) AS sanity_failed_count
        FROM path_plan
        LEFT JOIN row_checks
          ON path_plan.file_path = row_checks.file_path
        LEFT JOIN duplicate_checks
          ON path_plan.file_path = duplicate_checks.file_path
        ORDER BY path_plan.expected_trade_date, path_plan.expected_freq
        """
    ).fetchall()
    return {
        Path(str(row[0])): _RawPathMetrics(
            row_count=int(row[1] or 0),
            freq_failed_count=int(row[2] or 0),
            date_failed_count=int(row[3] or 0),
            duplicate_failed_count=int(row[4] or 0),
            sanity_failed_count=int(row[5] or 0),
        )
        for row in rows
    }


def _raw_path_row_counts(
    connection,
    path_plans: Sequence[_RawPathPlan],
) -> dict[Path, int]:
    if not path_plans:
        return {}
    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    rows = connection.execute(
        f"""
        SELECT filename AS file_path, count(*) AS row_count
        FROM read_parquet(
          {path_list_sql},
          hive_partitioning=false,
          filename=true,
          union_by_name=true
        )
        GROUP BY filename
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _silver_path_row_counts(
    connection,
    path_plans: Sequence[_SilverPathPlan],
) -> dict[Path, int]:
    if not path_plans:
        return {}
    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    rows = connection.execute(
        f"""
        SELECT filename AS file_path, count(*) AS row_count
        FROM read_parquet(
          {path_list_sql},
          hive_partitioning=false,
          filename=true,
          union_by_name=true
        )
        GROUP BY filename
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _silver_path_metrics(
    connection,
    path_plans: Sequence[_SilverPathPlan],
) -> dict[Path, _SilverPathMetrics]:
    if not path_plans:
        return {}

    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    path_values_sql = _silver_path_plan_values_sql(path_plans)
    rows = connection.execute(
        f"""
        WITH path_plan(
          file_path,
          expected_trade_date,
          expected_freq,
          stock_daily_path,
          suspend_path
        ) AS (
          VALUES {path_values_sql}
        ),
        silver_rows AS (
          SELECT
            filename AS file_path,
            path_plan.expected_trade_date,
            path_plan.expected_freq,
            ts_code,
            trade_date,
            trade_time,
            freq,
            open,
            high,
            low,
            close,
            vol,
            amount,
            exchange
          FROM read_parquet(
            {path_list_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          ) AS silver_file
          INNER JOIN path_plan
            ON silver_file.filename = path_plan.file_path
        ),
        row_checks AS (
          SELECT
            file_path,
            count(*) AS row_count,
            sum(
              CASE
                WHEN CAST(freq AS INTEGER) != expected_freq
                  OR trade_date != CAST(expected_trade_date AS DATE)
                  OR CAST(trade_time AS DATE) != CAST(expected_trade_date AS DATE)
                THEN 1 ELSE 0
              END
            ) AS freq_partition_failed_count,
            sum(
              CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < low
                  OR open < low OR open > high
                  OR close < low OR close > high
                THEN 1 ELSE 0
              END
            ) AS price_failed_count,
            sum(
              CASE
                WHEN vol IS NULL OR amount IS NULL
                  OR vol < 0 OR amount < 0
                  OR (vol = 0 AND amount != 0)
                  OR (vol > 0 AND vol < 100)
                  OR (vol >= 100 AND amount <= 0)
                THEN 1 ELSE 0
              END
            ) AS volume_amount_failed_count,
            sum(
              CASE
                WHEN exchange IS NULL
                  OR exchange != CASE
                    WHEN upper(ts_code) LIKE '%.SH' THEN 'SSE'
                    WHEN upper(ts_code) LIKE '%.SZ' THEN 'SZSE'
                    WHEN upper(ts_code) LIKE '%.BJ' THEN 'BSE'
                    ELSE NULL
                  END
                THEN 1 ELSE 0
              END
            ) AS exchange_failed_count
          FROM silver_rows
          GROUP BY file_path
        ),
        duplicate_checks AS (
          SELECT file_path, count(*) AS duplicate_failed_count
          FROM (
            SELECT file_path, ts_code, trade_time, count(*) AS duplicate_count
            FROM silver_rows
            GROUP BY file_path, ts_code, trade_time
            HAVING count(*) > 1
          )
          GROUP BY file_path
        )
        SELECT
          path_plan.file_path,
          coalesce(row_checks.row_count, 0) AS row_count,
          coalesce(row_checks.freq_partition_failed_count, 0)
            AS freq_partition_failed_count,
          coalesce(duplicate_checks.duplicate_failed_count, 0)
            AS duplicate_failed_count,
          coalesce(row_checks.price_failed_count, 0) AS price_failed_count,
          coalesce(row_checks.volume_amount_failed_count, 0)
            AS volume_amount_failed_count,
          coalesce(row_checks.exchange_failed_count, 0) AS exchange_failed_count
        FROM path_plan
        LEFT JOIN row_checks
          ON path_plan.file_path = row_checks.file_path
        LEFT JOIN duplicate_checks
          ON path_plan.file_path = duplicate_checks.file_path
        ORDER BY path_plan.expected_trade_date, path_plan.expected_freq
        """
    ).fetchall()
    return {
        Path(str(row[0])): _SilverPathMetrics(
            row_count=int(row[1] or 0),
            freq_partition_failed_count=int(row[2] or 0),
            duplicate_failed_count=int(row[3] or 0),
            price_failed_count=int(row[4] or 0),
            volume_amount_failed_count=int(row[5] or 0),
            exchange_failed_count=int(row[6] or 0),
        )
        for row in rows
    }


def _merge_silver_metrics(
    base_metrics: Mapping[Path, _SilverPathMetrics],
    path: Path,
    **updates: int,
) -> _SilverPathMetrics:
    current = base_metrics.get(path, _SilverPathMetrics())
    values = {
        "row_count": current.row_count,
        "freq_partition_failed_count": current.freq_partition_failed_count,
        "duplicate_failed_count": current.duplicate_failed_count,
        "price_failed_count": current.price_failed_count,
        "volume_amount_failed_count": current.volume_amount_failed_count,
        "exchange_failed_count": current.exchange_failed_count,
        "missing_stock_daily_code_count": current.missing_stock_daily_code_count,
        "full_day_suspend_failed_count": current.full_day_suspend_failed_count,
        "lifecycle_failed_count": current.lifecycle_failed_count,
    }
    values.update(updates)
    return _SilverPathMetrics(**values)


def _silver_stock_daily_missing_code_counts(
    connection,
    path_plans: Sequence[_SilverPathPlan],
) -> dict[Path, int]:
    query_plans = tuple(
        path_plan for path_plan in path_plans if path_plan.stock_daily_path.exists()
    )
    if not query_plans:
        return {}

    silver_path_sql = _path_list_sql(tuple(path_plan.path for path_plan in query_plans))
    daily_path_sql = _path_list_sql(
        tuple(sorted({path_plan.stock_daily_path for path_plan in query_plans}))
    )
    path_values_sql = _silver_path_plan_values_sql(query_plans)
    rows = connection.execute(
        f"""
        WITH path_plan(
          file_path,
          expected_trade_date,
          expected_freq,
          stock_daily_path,
          suspend_path
        ) AS (
          VALUES {path_values_sql}
        ),
        silver_codes AS (
          SELECT DISTINCT
            filename AS file_path,
            CAST(ts_code AS VARCHAR) AS ts_code
          FROM read_parquet(
            {silver_path_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          )
        ),
        daily_rows AS (
          SELECT DISTINCT
            filename AS stock_daily_path,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM read_parquet(
            {daily_path_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          )
        ),
        missing_codes AS (
          SELECT silver_codes.file_path, count(*) AS failed_count
          FROM silver_codes
          INNER JOIN path_plan
            ON silver_codes.file_path = path_plan.file_path
          LEFT JOIN daily_rows
            ON daily_rows.stock_daily_path = path_plan.stock_daily_path
           AND daily_rows.ts_code = silver_codes.ts_code
           AND daily_rows.trade_date = CAST(path_plan.expected_trade_date AS DATE)
          WHERE daily_rows.ts_code IS NULL
          GROUP BY silver_codes.file_path
        )
        SELECT
          path_plan.file_path,
          coalesce(missing_codes.failed_count, 0) AS failed_count
        FROM path_plan
        LEFT JOIN missing_codes
          ON path_plan.file_path = missing_codes.file_path
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _silver_full_day_suspend_counts(
    connection,
    path_plans: Sequence[_SilverPathPlan],
) -> dict[Path, int]:
    query_plans = tuple(
        path_plan for path_plan in path_plans if path_plan.suspend_path.exists()
    )
    if not query_plans:
        return {}

    silver_path_sql = _path_list_sql(tuple(path_plan.path for path_plan in query_plans))
    suspend_path_sql = _path_list_sql(
        tuple(sorted({path_plan.suspend_path for path_plan in query_plans}))
    )
    rows = connection.execute(
        f"""
        WITH silver_rows AS (
          SELECT
            filename AS file_path,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            trade_time
          FROM read_parquet(
            {silver_path_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          )
        ),
        suspend_rows AS (
          SELECT
            filename AS suspend_path,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(suspend_type AS VARCHAR) AS suspend_type,
            CAST(suspend_timing AS VARCHAR) AS suspend_timing
          FROM read_parquet(
            {suspend_path_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          )
        )
        SELECT silver_rows.file_path, count(*) AS failed_count
        FROM silver_rows
        INNER JOIN suspend_rows
          ON silver_rows.ts_code = suspend_rows.ts_code
         AND silver_rows.trade_date = suspend_rows.trade_date
        WHERE suspend_rows.suspend_type = 'S'
          AND suspend_rows.suspend_timing IS NULL
        GROUP BY silver_rows.file_path
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _silver_lifecycle_failure_counts(
    connection,
    *,
    stock_lifecycle_path: Path,
    path_plans: Sequence[_SilverPathPlan],
) -> dict[Path, int]:
    if not path_plans or not stock_lifecycle_path.exists():
        return {}

    silver_path_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    lifecycle_relation = silver_cny_stock_lifecycle_select(stock_lifecycle_path)
    rows = connection.execute(
        f"""
        WITH silver_codes AS (
          SELECT DISTINCT
            filename AS file_path,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM read_parquet(
            {silver_path_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          )
        ),
        stock_lifecycle AS (
          {lifecycle_relation}
        ),
        lifecycle_failures AS (
          SELECT silver_codes.file_path
          FROM silver_codes
          LEFT JOIN stock_lifecycle
            ON stock_lifecycle.ts_code = silver_codes.ts_code
           AND silver_codes.trade_date >= stock_lifecycle.list_date
           AND (
             stock_lifecycle.delist_date IS NULL
             OR silver_codes.trade_date <= stock_lifecycle.delist_date
           )
          WHERE stock_lifecycle.ts_code IS NULL
        )
        SELECT file_path, count(*) AS failed_count
        FROM lifecycle_failures
        GROUP BY file_path
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _raw_status_for_trade_date(
    *,
    trade_date: str,
    path_plans: Sequence[_RawPathPlan],
    registered_trade_day_set: set[str],
    schema_valid_paths: set[Path],
    metrics_by_path: Mapping[Path, _RawPathMetrics],
    full_semantics: bool,
) -> StkMinsDateReadiness:
    missing_paths = tuple(
        str(path_plan.path) for path_plan in path_plans if not path_plan.path.exists()
    )
    if trade_date not in registered_trade_day_set:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"raw stk mins partition is not registered for {trade_date}",
            failed_check_names=(RAW_STK_MINS_KEY_INTEGRITY_CHECK,),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )
    if missing_paths:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"raw stk mins files are missing for {trade_date}",
            failed_check_names=(RAW_STK_MINS_CONTRACT_CHECK,),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )

    failed_check_names: list[str] = []
    checked_row_count = 0
    failed_row_count = 0
    for path_plan in path_plans:
        metrics = metrics_by_path.get(path_plan.path, _RawPathMetrics())
        checked_row_count += metrics.row_count
        failed_row_count += metrics.failed_row_count
        if metrics.row_count <= 0:
            failed_check_names.append(RAW_STK_MINS_CONTRACT_CHECK)
        if full_semantics and path_plan.path not in schema_valid_paths:
            failed_check_names.append(RAW_STK_MINS_CONTRACT_CHECK)
        if full_semantics and metrics.freq_failed_count:
            failed_check_names.append(RAW_STK_MINS_CONTRACT_CHECK)
        if full_semantics and metrics.date_failed_count:
            failed_check_names.append(RAW_STK_MINS_CONTRACT_CHECK)
        if full_semantics and metrics.duplicate_failed_count:
            failed_check_names.append(RAW_STK_MINS_KEY_INTEGRITY_CHECK)
        if full_semantics and metrics.sanity_failed_count:
            failed_check_names.append(RAW_STK_MINS_VALUE_DOMAIN_CHECK)

    failed_check_names = sorted(set(failed_check_names))
    checks_passed = not failed_check_names
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=checks_passed,
        materialized=True,
        checks_passed=checks_passed,
        reason=(
            "ready"
            if checks_passed
            else "raw stk mins blocking checks failed for "
            f"{trade_date}: {', '.join(failed_check_names)}"
        ),
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=(),
        expected_file_count=len(path_plans),
        existing_file_count=len(path_plans),
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
    )


def batch_raw_stk_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    freqs: Sequence[int] = STK_MINS_FREQS,
    full_semantics: bool = True,
) -> StkMinsBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = _normalize_trade_dates(expected_trade_dates)
    registered_trade_day_set = set(_normalize_trade_dates(registered_trade_days))
    freqs = _normalize_freqs(freqs)
    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    path_plans = _raw_path_plans(
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        freqs=freqs,
    )
    existing_path_plans = tuple(path_plan for path_plan in path_plans if path_plan.path.exists())

    schema_valid_paths: set[Path] = set()
    if full_semantics:
        for path_plan in existing_path_plans:
            if _schema_matches_raw_contract(connection, path_plan.path):
                schema_valid_paths.add(path_plan.path)
    else:
        schema_valid_paths = {path_plan.path for path_plan in existing_path_plans}

    data_check_path_plans = tuple(
        path_plan
        for path_plan in existing_path_plans
        if path_plan.path in schema_valid_paths
    )
    row_counts_by_path = _raw_path_row_counts(connection, existing_path_plans)
    metrics_by_path = {
        path: _RawPathMetrics(row_count=row_count)
        for path, row_count in row_counts_by_path.items()
    }
    metrics_by_path.update(_raw_path_metrics(connection, data_check_path_plans))
    path_plans_by_trade_date = {
        trade_date: tuple(
            path_plan for path_plan in path_plans if path_plan.trade_date == trade_date
        )
        for trade_date in expected_trade_dates
    }
    statuses_by_trade_date = {
        trade_date: _raw_status_for_trade_date(
            trade_date=trade_date,
            path_plans=path_plans_by_trade_date[trade_date],
            registered_trade_day_set=registered_trade_day_set,
            schema_valid_paths=schema_valid_paths,
            metrics_by_path=metrics_by_path,
            full_semantics=full_semantics,
        )
        for trade_date in expected_trade_dates
    }

    elapsed_ms = (perf_counter() - started_at) * 1000
    return StkMinsBatchReadiness(
        dataset="raw_stk_mins",
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        freq_count=len(freqs),
        elapsed_ms=elapsed_ms,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _silver_status_for_trade_date(
    *,
    trade_date: str,
    path_plans: Sequence[_SilverPathPlan],
    registered_trade_day_set: set[str],
    stock_lifecycle_path: Path,
    schema_valid_paths: set[Path],
    metrics_by_path: Mapping[Path, _SilverPathMetrics],
    full_semantics: bool,
) -> StkMinsDateReadiness:
    missing_paths = tuple(
        str(path_plan.path) for path_plan in path_plans if not path_plan.path.exists()
    )
    if trade_date not in registered_trade_day_set:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"silver stk mins partition is not registered for {trade_date}",
            failed_check_names=(SILVER_STK_MINS_KEY_INTEGRITY_CHECK,),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )
    if missing_paths:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"silver stk mins files are missing for {trade_date}",
            failed_check_names=(SILVER_STK_MINS_CONTRACT_CHECK,),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )

    failed_check_names: list[str] = []
    checked_row_count = 0
    failed_row_count = 0
    for path_plan in path_plans:
        metrics = metrics_by_path.get(path_plan.path, _SilverPathMetrics())
        checked_row_count += metrics.row_count
        failed_row_count += metrics.failed_row_count
        if metrics.row_count <= 0:
            failed_check_names.append(SILVER_STK_MINS_CONTRACT_CHECK)
        if full_semantics and path_plan.path not in schema_valid_paths:
            failed_check_names.append(SILVER_STK_MINS_CONTRACT_CHECK)
        if full_semantics and metrics.freq_partition_failed_count:
            failed_check_names.append(SILVER_STK_MINS_CONTRACT_CHECK)
        if full_semantics and metrics.duplicate_failed_count:
            failed_check_names.append(SILVER_STK_MINS_KEY_INTEGRITY_CHECK)
        if full_semantics and metrics.price_failed_count:
            failed_check_names.append(SILVER_STK_MINS_VALUE_DOMAIN_CHECK)
        if full_semantics and metrics.volume_amount_failed_count:
            failed_check_names.append(SILVER_STK_MINS_VALUE_DOMAIN_CHECK)
        if full_semantics and metrics.exchange_failed_count:
            failed_check_names.append(SILVER_STK_MINS_VALUE_DOMAIN_CHECK)
        if full_semantics and (
            not path_plan.stock_daily_path.exists()
            or metrics.missing_stock_daily_code_count
        ):
            failed_check_names.append(SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK)
        if full_semantics and (
            not path_plan.suspend_path.exists()
            or metrics.full_day_suspend_failed_count
        ):
            failed_check_names.append(SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK)
        if full_semantics and (
            not stock_lifecycle_path.exists() or metrics.lifecycle_failed_count
        ):
            failed_check_names.append(SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK)

    failed_check_names = sorted(set(failed_check_names))
    checks_passed = not failed_check_names
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=checks_passed,
        materialized=True,
        checks_passed=checks_passed,
        reason=(
            "ready"
            if checks_passed
            else "silver stk mins blocking checks failed for "
            f"{trade_date}: {', '.join(failed_check_names)}"
        ),
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=(),
        expected_file_count=len(path_plans),
        existing_file_count=len(path_plans),
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
    )


def batch_silver_stk_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    freqs: Sequence[int] = STK_MINS_FREQS,
    full_semantics: bool = True,
) -> StkMinsBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = _normalize_trade_dates(expected_trade_dates)
    registered_trade_day_set = set(_normalize_trade_dates(registered_trade_days))
    freqs = _normalize_freqs(freqs)
    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root)
    path_plans = _silver_path_plans(
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        freqs=freqs,
    )
    existing_path_plans = tuple(path_plan for path_plan in path_plans if path_plan.path.exists())

    schema_valid_paths: set[Path] = set()
    if full_semantics:
        for path_plan in existing_path_plans:
            if _schema_matches_silver_contract(connection, path_plan.path):
                schema_valid_paths.add(path_plan.path)
    else:
        schema_valid_paths = {path_plan.path for path_plan in existing_path_plans}

    data_check_path_plans = tuple(
        path_plan
        for path_plan in existing_path_plans
        if path_plan.path in schema_valid_paths
    )
    row_counts_by_path = _silver_path_row_counts(connection, existing_path_plans)
    metrics_by_path: dict[Path, _SilverPathMetrics] = {
        path: _SilverPathMetrics(row_count=row_count)
        for path, row_count in row_counts_by_path.items()
    }
    metrics_by_path.update(_silver_path_metrics(connection, data_check_path_plans))

    if full_semantics:
        for path, failed_count in _silver_stock_daily_missing_code_counts(
            connection,
            data_check_path_plans,
        ).items():
            metrics_by_path[path] = _merge_silver_metrics(
                metrics_by_path,
                path,
                missing_stock_daily_code_count=failed_count,
            )
        for path, failed_count in _silver_full_day_suspend_counts(
            connection,
            data_check_path_plans,
        ).items():
            metrics_by_path[path] = _merge_silver_metrics(
                metrics_by_path,
                path,
                full_day_suspend_failed_count=failed_count,
            )
        for path, failed_count in _silver_lifecycle_failure_counts(
            connection,
            stock_lifecycle_path=stock_lifecycle_path,
            path_plans=data_check_path_plans,
        ).items():
            metrics_by_path[path] = _merge_silver_metrics(
                metrics_by_path,
                path,
                lifecycle_failed_count=failed_count,
            )

    path_plans_by_trade_date = {
        trade_date: tuple(
            path_plan for path_plan in path_plans if path_plan.trade_date == trade_date
        )
        for trade_date in expected_trade_dates
    }
    statuses_by_trade_date = {
        trade_date: _silver_status_for_trade_date(
            trade_date=trade_date,
            path_plans=path_plans_by_trade_date[trade_date],
            registered_trade_day_set=registered_trade_day_set,
            stock_lifecycle_path=stock_lifecycle_path,
            schema_valid_paths=schema_valid_paths,
            metrics_by_path=metrics_by_path,
            full_semantics=full_semantics,
        )
        for trade_date in expected_trade_dates
    }

    elapsed_ms = (perf_counter() - started_at) * 1000
    return StkMinsBatchReadiness(
        dataset="silver_stk_mins",
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        freq_count=len(freqs),
        elapsed_ms=elapsed_ms,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _gold_qfq_native_expected_paths_by_date(
    connection,
    *,
    lake_root: Path,
    freq: int,
    expected_trade_dates: Sequence[str],
    silver_paths: Sequence[Path],
) -> dict[str, tuple[Path, ...]]:
    if not silver_paths:
        return {trade_date: () for trade_date in expected_trade_dates}
    source = _read_parquet_paths(silver_paths)
    rows = connection.execute(
        f"""
        SELECT
          strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM {source}
        GROUP BY partition_key, ts_code, year
        ORDER BY partition_key, ts_code
        """
    ).fetchall()
    paths_by_date: dict[str, list[Path]] = {
        trade_date: [] for trade_date in expected_trade_dates
    }
    for partition_key, ts_code, year in rows:
        paths_by_date.setdefault(str(partition_key), []).append(
            gold_stk_mins_qfq_path(lake_root, freq, str(ts_code), str(year))
        )
    return {key: tuple(paths) for key, paths in paths_by_date.items()}


def _gold_qfq_native_path_plans(
    connection,
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[_GoldQfqNativePathPlan, ...]:
    plans: list[_GoldQfqNativePathPlan] = []
    for freq in STK_MINS_QFQ_NATIVE_FREQS:
        silver_paths_by_date = {
            trade_date: silver_stk_mins_path(lake_root, freq, trade_date)
            for trade_date in expected_trade_dates
        }
        existing_silver_paths = tuple(
            path for path in silver_paths_by_date.values() if path.exists()
        )
        expected_paths_by_date = _gold_qfq_native_expected_paths_by_date(
            connection,
            lake_root=lake_root,
            freq=freq,
            expected_trade_dates=expected_trade_dates,
            silver_paths=existing_silver_paths,
        )
        for trade_date in expected_trade_dates:
            silver_path = silver_paths_by_date[trade_date]
            trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
            if not silver_path.exists():
                expected_gold_paths: tuple[Path, ...] = ()
                existing_gold_paths: tuple[Path, ...] = ()
                missing_paths = (silver_path,)
            else:
                expected_gold_paths = expected_paths_by_date.get(trade_date, ())
                existing_gold_paths = tuple(
                    path for path in expected_gold_paths if path.exists()
                )
                missing_paths = tuple(
                    path for path in expected_gold_paths if not path.exists()
                )
            plans.append(
                _GoldQfqNativePathPlan(
                    trade_date=trade_date,
                    freq=freq,
                    silver_path=silver_path,
                    trade_adj_factor_path=trade_adj_factor_path,
                    expected_gold_paths=expected_gold_paths,
                    existing_gold_paths=existing_gold_paths,
                    missing_paths=missing_paths,
                )
            )
    return tuple(plans)


def _gold_qfq_batch_gold_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    freq: int,
) -> dict[str, dict[str, int]]:
    if not gold_paths:
        return {
            partition_key: {
                "gold_target_row_count": 0,
                "path_mismatch_row_count": 0,
                "duplicate_key_count": 0,
                "invalid_price_row_count": 0,
            }
            for partition_key in partition_keys
        }
    source = _read_parquet_paths(gold_paths, filename=True)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS (VALUES {_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(filename AS VARCHAR) AS filename,
            regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
              AS path_ts_code,
            regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
              AS path_year
          FROM {source}
        ),
        target_rows AS (
          SELECT gold_rows.*
          FROM gold_rows
          INNER JOIN selected
            ON gold_rows.partition_key = selected.partition_key
        ),
        duplicate_groups AS (
          SELECT partition_key, ts_code, trade_time, count(*) AS duplicate_count
          FROM target_rows
          GROUP BY partition_key, ts_code, trade_time
          HAVING count(*) > 1
        ),
        gold_aggregates AS (
          SELECT
            partition_key,
            count(*) AS gold_target_row_count,
            sum(
              CASE
                WHEN freq != {freq}
                  OR ts_code != path_ts_code
                  OR strftime(trade_date, '%Y') != path_year
                  OR CAST(trade_time AS DATE) != trade_date
                THEN 1 ELSE 0
              END
            ) AS path_mismatch_row_count,
            sum(
              CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < low
                  OR open < low OR open > high
                  OR close < low OR close > high
                THEN 1 ELSE 0
              END
            ) AS invalid_price_row_count
          FROM target_rows
          GROUP BY partition_key
        ),
        duplicate_aggregates AS (
          SELECT partition_key, count(*) AS duplicate_key_count
          FROM duplicate_groups
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(gold_aggregates.gold_target_row_count, 0)
            AS gold_target_row_count,
          coalesce(gold_aggregates.path_mismatch_row_count, 0)
            AS path_mismatch_row_count,
          coalesce(duplicate_aggregates.duplicate_key_count, 0)
            AS duplicate_key_count,
          coalesce(gold_aggregates.invalid_price_row_count, 0)
            AS invalid_price_row_count
        FROM selected
        LEFT JOIN gold_aggregates
          ON selected.partition_key = gold_aggregates.partition_key
        LEFT JOIN duplicate_aggregates
          ON selected.partition_key = duplicate_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "gold_target_row_count": int(gold_target_row_count),
            "path_mismatch_row_count": int(path_mismatch_row_count),
            "duplicate_key_count": int(duplicate_key_count),
            "invalid_price_row_count": int(invalid_price_row_count),
        }
        for (
            partition_key,
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
        ) in rows
    }


def _gold_qfq_native_batch_coverage_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    silver_paths: Sequence[Path],
    trade_adj_factor_paths: Sequence[Path],
) -> dict[str, dict[str, int]]:
    if not silver_paths:
        return {
            partition_key: {
                "qfq_output_row_count": 0,
                "missing_trade_adj_factor_row_count": 0,
                "missing_as_of_adj_factor_row_count": 0,
            }
            for partition_key in partition_keys
        }
    silver_source = _read_parquet_paths(silver_paths)
    trade_adj_source = (
        _read_parquet_paths(trade_adj_factor_paths)
        if trade_adj_factor_paths
        else None
    )
    trade_adj_cte = (
        f"""
        trade_adj_factor AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(adj_factor AS DOUBLE) AS adj_factor
          FROM {trade_adj_source}
        )
        """
        if trade_adj_source is not None
        else """
        trade_adj_factor AS (
          SELECT
            CAST(NULL AS VARCHAR) AS ts_code,
            CAST(NULL AS DATE) AS trade_date,
            CAST(NULL AS DOUBLE) AS adj_factor
          WHERE false
        )
        """
    )
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS (VALUES {_values_sql(partition_keys)}),
        silver_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key
          FROM {silver_source}
        ),
        {trade_adj_cte},
        joined_rows AS (
          SELECT
            silver_rows.partition_key,
            silver_rows.ts_code,
            trade_adj_factor.adj_factor AS trade_adj_factor,
            as_of_adj_factor.adj_factor AS as_of_adj_factor
          FROM silver_rows
          LEFT JOIN trade_adj_factor
            ON silver_rows.ts_code = trade_adj_factor.ts_code
           AND silver_rows.trade_date = trade_adj_factor.trade_date
          LEFT JOIN trade_adj_factor AS as_of_adj_factor
            ON silver_rows.ts_code = as_of_adj_factor.ts_code
           AND silver_rows.trade_date = as_of_adj_factor.trade_date
        )
        SELECT
          selected.partition_key,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.trade_adj_factor IS NOT NULL
              AND joined_rows.as_of_adj_factor IS NOT NULL
          ) AS qfq_output_row_count,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.trade_adj_factor IS NULL
          ) AS missing_trade_adj_factor_row_count,
          count(joined_rows.ts_code) FILTER (
            WHERE joined_rows.as_of_adj_factor IS NULL
          ) AS missing_as_of_adj_factor_row_count
        FROM selected
        LEFT JOIN joined_rows
          ON selected.partition_key = joined_rows.partition_key
        GROUP BY selected.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "qfq_output_row_count": int(qfq_output_row_count),
            "missing_trade_adj_factor_row_count": int(
                missing_trade_adj_factor_row_count
            ),
            "missing_as_of_adj_factor_row_count": int(
                missing_as_of_adj_factor_row_count
            ),
        }
        for (
            partition_key,
            qfq_output_row_count,
            missing_trade_adj_factor_row_count,
            missing_as_of_adj_factor_row_count,
        ) in rows
    }


def _gold_qfq_native_batch_formula_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    silver_paths: Sequence[Path],
    trade_adj_factor_paths: Sequence[Path],
    freq: int,
) -> dict[str, dict[str, int]]:
    if not gold_paths or not silver_paths or not trade_adj_factor_paths:
        return {
            partition_key: {
                "formula_missing_gold_row_count": 0,
                "formula_unexpected_gold_row_count": 0,
                "formula_mismatch_row_count": 0,
                "gold_target_row_count": 0,
                "path_mismatch_row_count": 0,
                "duplicate_key_count": 0,
                "invalid_price_row_count": 0,
            }
            for partition_key in partition_keys
        }
    gold_source = _read_parquet_paths(gold_paths)
    silver_source = _read_parquet_paths(silver_paths)
    trade_adj_source = _read_parquet_paths(trade_adj_factor_paths)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS (VALUES {_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(filename AS VARCHAR) AS filename,
            regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
              AS path_ts_code,
            regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
              AS path_year
          FROM {gold_source}
        ),
        target_gold_rows AS (
          SELECT gold_rows.*
          FROM gold_rows
          INNER JOIN selected
            ON gold_rows.partition_key = selected.partition_key
        ),
        silver_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
          FROM {silver_source}
        ),
        adj_factor AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(adj_factor AS DOUBLE) AS adj_factor
          FROM {trade_adj_source}
        ),
        expected_rows AS (
          SELECT
            silver_rows.ts_code,
            silver_rows.partition_key,
            silver_rows.trade_time,
            CAST(silver_rows.open * trade_adj_factor.adj_factor / as_of_adj_factor.adj_factor AS DOUBLE) AS open,
            CAST(silver_rows.high * trade_adj_factor.adj_factor / as_of_adj_factor.adj_factor AS DOUBLE) AS high,
            CAST(silver_rows.low * trade_adj_factor.adj_factor / as_of_adj_factor.adj_factor AS DOUBLE) AS low,
            CAST(silver_rows.close * trade_adj_factor.adj_factor / as_of_adj_factor.adj_factor AS DOUBLE) AS close
          FROM silver_rows
          INNER JOIN selected
            ON silver_rows.partition_key = selected.partition_key
          INNER JOIN adj_factor AS trade_adj_factor
            ON silver_rows.ts_code = trade_adj_factor.ts_code
           AND silver_rows.trade_date = trade_adj_factor.trade_date
          INNER JOIN adj_factor AS as_of_adj_factor
            ON silver_rows.ts_code = as_of_adj_factor.ts_code
           AND silver_rows.trade_date = as_of_adj_factor.trade_date
          WHERE trade_adj_factor.adj_factor IS NOT NULL
            AND as_of_adj_factor.adj_factor IS NOT NULL
        ),
        duplicate_groups AS (
          SELECT partition_key, ts_code, trade_time, count(*) AS duplicate_count
          FROM target_gold_rows
          GROUP BY partition_key, ts_code, trade_time
          HAVING count(*) > 1
        ),
        compared_rows AS (
          SELECT
            coalesce(target_gold_rows.partition_key, expected_rows.partition_key)
              AS partition_key,
            target_gold_rows.open AS gold_open,
            expected_rows.open AS expected_open,
            target_gold_rows.high AS gold_high,
            expected_rows.high AS expected_high,
            target_gold_rows.low AS gold_low,
            expected_rows.low AS expected_low,
            target_gold_rows.close AS gold_close,
            expected_rows.close AS expected_close,
            target_gold_rows.ts_code IS NULL AS missing_gold_row,
            expected_rows.ts_code IS NULL AS unexpected_gold_row
          FROM target_gold_rows
          FULL OUTER JOIN expected_rows
            ON target_gold_rows.partition_key = expected_rows.partition_key
           AND target_gold_rows.ts_code = expected_rows.ts_code
           AND target_gold_rows.trade_time = expected_rows.trade_time
        ),
        formula_aggregates AS (
          SELECT
            partition_key,
            count(*) FILTER (WHERE missing_gold_row)
              AS formula_missing_gold_row_count,
            count(*) FILTER (WHERE unexpected_gold_row)
              AS formula_unexpected_gold_row_count,
            count(*) FILTER (
              WHERE NOT missing_gold_row
                AND NOT unexpected_gold_row
                AND (
                  abs(gold_open - expected_open) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_high - expected_high) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_low - expected_low) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_close - expected_close) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                )
            ) AS formula_mismatch_row_count
          FROM compared_rows
          GROUP BY partition_key
        ),
        target_gold_aggregates AS (
          SELECT
            partition_key,
            count(*) AS gold_target_row_count,
            sum(
              CASE
                WHEN freq != {freq}
                  OR ts_code != path_ts_code
                  OR strftime(trade_date, '%Y') != path_year
                  OR CAST(trade_time AS DATE) != trade_date
                THEN 1 ELSE 0
              END
            ) AS path_mismatch_row_count,
            sum(
              CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < low
                  OR open < low OR open > high
                  OR close < low OR close > high
                THEN 1 ELSE 0
              END
            ) AS invalid_price_row_count
          FROM target_gold_rows
          GROUP BY partition_key
        ),
        duplicate_aggregates AS (
          SELECT partition_key, count(*) AS duplicate_key_count
          FROM duplicate_groups
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(target_gold_aggregates.gold_target_row_count, 0)
            AS gold_target_row_count,
          coalesce(target_gold_aggregates.path_mismatch_row_count, 0)
            AS path_mismatch_row_count,
          coalesce(duplicate_aggregates.duplicate_key_count, 0)
            AS duplicate_key_count,
          coalesce(target_gold_aggregates.invalid_price_row_count, 0)
            AS invalid_price_row_count,
          coalesce(formula_aggregates.formula_missing_gold_row_count, 0)
            AS formula_missing_gold_row_count,
          coalesce(formula_aggregates.formula_unexpected_gold_row_count, 0)
            AS formula_unexpected_gold_row_count,
          coalesce(formula_aggregates.formula_mismatch_row_count, 0)
            AS formula_mismatch_row_count
        FROM selected
        LEFT JOIN target_gold_aggregates
          ON selected.partition_key = target_gold_aggregates.partition_key
        LEFT JOIN duplicate_aggregates
          ON selected.partition_key = duplicate_aggregates.partition_key
        LEFT JOIN formula_aggregates
          ON selected.partition_key = formula_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "gold_target_row_count": int(gold_target_row_count),
            "path_mismatch_row_count": int(path_mismatch_row_count),
            "duplicate_key_count": int(duplicate_key_count),
            "invalid_price_row_count": int(invalid_price_row_count),
            "formula_missing_gold_row_count": int(formula_missing_gold_row_count),
            "formula_unexpected_gold_row_count": int(
                formula_unexpected_gold_row_count
            ),
            "formula_mismatch_row_count": int(formula_mismatch_row_count),
        }
        for (
            partition_key,
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
            formula_missing_gold_row_count,
            formula_unexpected_gold_row_count,
            formula_mismatch_row_count,
        ) in rows
    }


def _gold_qfq_native_batch_counts(
    connection,
    *,
    native_plans: Sequence[_GoldQfqNativePathPlan],
) -> Mapping[tuple[str, int], GoldStkMinsQfqCheckCounts]:
    counts_by_key: dict[tuple[str, int], GoldStkMinsQfqCheckCounts] = {}
    for freq in STK_MINS_QFQ_NATIVE_FREQS:
        freq_plans = tuple(plan for plan in native_plans if plan.freq == freq)
        data_plans = tuple(plan for plan in freq_plans if plan.silver_path.exists())
        complete_data_plans = tuple(plan for plan in data_plans if not plan.missing_paths)
        partition_keys = tuple(plan.trade_date for plan in complete_data_plans)
        silver_paths = tuple(
            dict.fromkeys(plan.silver_path for plan in complete_data_plans)
        )
        trade_adj_paths = tuple(
            dict.fromkeys(
                plan.trade_adj_factor_path
                for plan in complete_data_plans
                if plan.trade_adj_factor_path.exists()
            )
        )
        existing_gold_paths = tuple(
            dict.fromkeys(
                path for plan in complete_data_plans for path in plan.existing_gold_paths
            )
        )
        silver_row_counts = _raw_path_row_counts(
            connection,
            tuple(
                _RawPathPlan(plan.trade_date, plan.freq, plan.silver_path)
                for plan in complete_data_plans
            ),
        )
        coverage_counts = _gold_qfq_native_batch_coverage_counts(
            connection,
            partition_keys=partition_keys,
            silver_paths=silver_paths,
            trade_adj_factor_paths=trade_adj_paths,
        )
        formula_partition_keys = tuple(
            plan.trade_date
            for plan in complete_data_plans
            if plan.trade_adj_factor_path.exists()
        )
        formula_counts = _gold_qfq_native_batch_formula_counts(
            connection,
            partition_keys=formula_partition_keys,
            gold_paths=existing_gold_paths,
            silver_paths=tuple(
                dict.fromkeys(
                    plan.silver_path
                    for plan in complete_data_plans
                    if plan.trade_adj_factor_path.exists()
                )
            ),
            trade_adj_factor_paths=trade_adj_paths,
            freq=freq,
        )
        no_formula_partition_keys = tuple(
            plan.trade_date
            for plan in complete_data_plans
            if not plan.trade_adj_factor_path.exists()
        )
        fallback_gold_counts = (
            _gold_qfq_batch_gold_counts(
                connection,
                partition_keys=no_formula_partition_keys,
                gold_paths=existing_gold_paths,
                freq=freq,
            )
            if no_formula_partition_keys
            else {}
        )
        schema_mismatch_by_key: dict[tuple[str, int], int] = {}
        freq_schema_mismatch_count, _observed_schema, _schema_error = (
            _gold_qfq_schema_mismatch_count(connection, existing_gold_paths)
        )
        if freq_schema_mismatch_count == 0:
            schema_mismatch_by_key = {
                (plan.trade_date, plan.freq): 0 for plan in complete_data_plans
            }
        else:
            for plan in complete_data_plans:
                schema_mismatch_count, _observed_schema, _schema_error = (
                    _gold_qfq_schema_mismatch_count(
                        connection,
                        plan.existing_gold_paths,
                    )
                )
                schema_mismatch_by_key[(plan.trade_date, plan.freq)] = (
                    schema_mismatch_count
                )

        for plan in freq_plans:
            if not plan.silver_path.exists():
                counts_by_key[(plan.trade_date, plan.freq)] = GoldStkMinsQfqCheckCounts(
                    silver_row_count=0,
                    expected_file_count=0,
                    existing_file_count=0,
                    missing_file_count=1,
                    gold_target_row_count=0,
                    missing_trade_adj_factor_row_count=0,
                    missing_as_of_adj_factor_row_count=0,
                    qfq_output_row_count=0,
                    schema_mismatch_file_count=0,
                    path_mismatch_row_count=0,
                    duplicate_key_count=0,
                    invalid_price_row_count=0,
                    formula_missing_gold_row_count=0,
                    formula_unexpected_gold_row_count=0,
                    formula_mismatch_row_count=0,
                )
                continue
            if plan.missing_paths:
                counts_by_key[(plan.trade_date, plan.freq)] = GoldStkMinsQfqCheckCounts(
                    silver_row_count=0,
                    expected_file_count=len(plan.expected_gold_paths),
                    existing_file_count=len(plan.existing_gold_paths),
                    missing_file_count=len(plan.missing_paths),
                    gold_target_row_count=0,
                    missing_trade_adj_factor_row_count=0,
                    missing_as_of_adj_factor_row_count=0,
                    qfq_output_row_count=0,
                    schema_mismatch_file_count=0,
                    path_mismatch_row_count=0,
                    duplicate_key_count=0,
                    invalid_price_row_count=0,
                    formula_missing_gold_row_count=0,
                    formula_unexpected_gold_row_count=0,
                    formula_mismatch_row_count=0,
                )
                continue
            gold = formula_counts.get(plan.trade_date, {})
            if not gold:
                gold = fallback_gold_counts.get(plan.trade_date, {})
            coverage = coverage_counts.get(plan.trade_date, {})
            formula = formula_counts.get(plan.trade_date, {})
            counts_by_key[(plan.trade_date, plan.freq)] = GoldStkMinsQfqCheckCounts(
                silver_row_count=silver_row_counts.get(plan.silver_path, 0),
                expected_file_count=len(plan.expected_gold_paths),
                existing_file_count=len(plan.existing_gold_paths),
                missing_file_count=len(plan.missing_paths),
                gold_target_row_count=int(gold.get("gold_target_row_count", 0)),
                missing_trade_adj_factor_row_count=int(
                    coverage.get("missing_trade_adj_factor_row_count", 0)
                ),
                missing_as_of_adj_factor_row_count=int(
                    coverage.get("missing_as_of_adj_factor_row_count", 0)
                ),
                qfq_output_row_count=int(coverage.get("qfq_output_row_count", 0)),
                schema_mismatch_file_count=schema_mismatch_by_key.get(
                    (plan.trade_date, plan.freq),
                    0,
                ),
                path_mismatch_row_count=int(gold.get("path_mismatch_row_count", 0)),
                duplicate_key_count=int(gold.get("duplicate_key_count", 0)),
                invalid_price_row_count=int(gold.get("invalid_price_row_count", 0)),
                formula_missing_gold_row_count=int(
                    formula.get("formula_missing_gold_row_count", 0)
                ),
                formula_unexpected_gold_row_count=int(
                    formula.get("formula_unexpected_gold_row_count", 0)
                ),
                formula_mismatch_row_count=int(
                    formula.get("formula_mismatch_row_count", 0)
                ),
            )
    return counts_by_key


def _gold_qfq_native_counts_for_trade_date(
    connection,
    *,
    lake_root: Path,
    trade_date: str,
    freq: int,
) -> tuple[GoldStkMinsQfqCheckCounts, tuple[Path, ...]]:
    silver_path = silver_stk_mins_path(lake_root, freq, trade_date)
    trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    if not silver_path.exists():
        return (
            GoldStkMinsQfqCheckCounts(
                silver_row_count=0,
                expected_file_count=0,
                existing_file_count=0,
                missing_file_count=1,
                gold_target_row_count=0,
                missing_trade_adj_factor_row_count=0,
                missing_as_of_adj_factor_row_count=0,
                qfq_output_row_count=0,
                schema_mismatch_file_count=0,
                path_mismatch_row_count=0,
                duplicate_key_count=0,
                invalid_price_row_count=0,
                formula_missing_gold_row_count=0,
                formula_unexpected_gold_row_count=0,
                formula_mismatch_row_count=0,
            ),
            (silver_path,),
        )

    expected_paths = _gold_qfq_expected_paths(
        connection,
        lake_root=lake_root,
        freq=freq,
        partition_key=trade_date,
        silver_path=silver_path,
    )
    missing_gold_paths = tuple(path for path in expected_paths if not path.exists())
    existing_gold_paths = tuple(path for path in expected_paths if path.exists())
    silver_row_count = _row_count(connection, silver_path)
    schema_mismatch_count, _observed_schema, _schema_error = (
        _gold_qfq_schema_mismatch_count(connection, existing_gold_paths)
    )

    gold_target_row_count = 0
    path_mismatch_row_count = 0
    duplicate_key_count = 0
    invalid_price_row_count = 0
    formula_missing_gold_row_count = 0
    formula_unexpected_gold_row_count = 0
    formula_mismatch_row_count = 0

    if existing_gold_paths and schema_mismatch_count == 0:
        gold_source = _read_parquet_paths(existing_gold_paths, filename=True)
        (
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
        ) = (
            int(value or 0)
            for value in connection.execute(
                _gold_qfq_counts_sql(
                    gold_source=gold_source,
                    partition_key=trade_date,
                    freq=freq,
                )
            ).fetchone()
        )
        if trade_adj_factor_path.exists():
            qfq_select_sql = build_daily_qfq_select_sql(
                silver_paths=[silver_path],
                trade_adj_factor_paths=[trade_adj_factor_path],
                as_of_adj_factor_paths=[trade_adj_factor_path],
            )
            (
                formula_missing_gold_row_count,
                formula_unexpected_gold_row_count,
                formula_mismatch_row_count,
            ) = (
                int(value or 0)
                for value in connection.execute(
                    _gold_qfq_formula_counts_sql(
                        gold_source=gold_source,
                        qfq_select_sql=qfq_select_sql,
                        partition_key=trade_date,
                    )
                ).fetchone()
            )

    if trade_adj_factor_path.exists():
        (
            _coverage_silver_row_count,
            qfq_output_row_count,
            missing_trade_adj_factor_row_count,
            missing_as_of_adj_factor_row_count,
        ) = (
            int(value or 0)
            for value in connection.execute(
                build_daily_qfq_coverage_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_adj_factor_path],
                    as_of_adj_factor_paths=[trade_adj_factor_path],
                )
            ).fetchone()
        )
    else:
        qfq_output_row_count = 0
        missing_trade_adj_factor_row_count = silver_row_count
        missing_as_of_adj_factor_row_count = silver_row_count

    return (
        GoldStkMinsQfqCheckCounts(
            silver_row_count=silver_row_count,
            expected_file_count=len(expected_paths),
            existing_file_count=len(existing_gold_paths),
            missing_file_count=len(missing_gold_paths),
            gold_target_row_count=gold_target_row_count,
            missing_trade_adj_factor_row_count=missing_trade_adj_factor_row_count,
            missing_as_of_adj_factor_row_count=missing_as_of_adj_factor_row_count,
            qfq_output_row_count=qfq_output_row_count,
            schema_mismatch_file_count=schema_mismatch_count,
            path_mismatch_row_count=path_mismatch_row_count,
            duplicate_key_count=duplicate_key_count,
            invalid_price_row_count=invalid_price_row_count,
            formula_missing_gold_row_count=formula_missing_gold_row_count,
            formula_unexpected_gold_row_count=formula_unexpected_gold_row_count,
            formula_mismatch_row_count=formula_mismatch_row_count,
        ),
        missing_gold_paths,
    )


def _gold_qfq_native_failed_check_names(
    counts: GoldStkMinsQfqCheckCounts,
) -> tuple[str, ...]:
    failed_check_names: list[str] = []
    factor_coverage_failed_count = (
        counts.missing_trade_adj_factor_row_count
        + counts.missing_as_of_adj_factor_row_count
        + abs(counts.silver_row_count - counts.qfq_output_row_count)
    )
    formula_failed_count = (
        counts.formula_missing_gold_row_count
        + counts.formula_unexpected_gold_row_count
        + counts.formula_mismatch_row_count
    )
    if not (
        counts.expected_file_count > 0
        and counts.missing_file_count == 0
        and counts.gold_target_row_count > 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK)
    if not (
        counts.missing_file_count == 0 and counts.schema_mismatch_file_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.path_mismatch_row_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.duplicate_key_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.invalid_price_row_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.gold_target_row_count == counts.silver_row_count
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK)
    if factor_coverage_failed_count:
        failed_check_names.append(GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and formula_failed_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK)
    return tuple(failed_check_names)


def _gold_qfq_derived_expected_paths_by_date(
    connection,
    *,
    lake_root: Path,
    target_freq: int,
    expected_select_sql: str,
    expected_trade_dates: Sequence[str],
) -> dict[str, tuple[Path, ...]]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT
          strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM ({expected_select_sql})
        ORDER BY partition_key, ts_code
        """
    ).fetchall()
    paths_by_date: dict[str, list[Path]] = {
        trade_date: [] for trade_date in expected_trade_dates
    }
    for partition_key, ts_code, year in rows:
        paths_by_date.setdefault(str(partition_key), []).append(
            gold_stk_mins_qfq_path(lake_root, target_freq, str(ts_code), str(year))
        )
    return {key: tuple(paths) for key, paths in paths_by_date.items()}


def _gold_qfq_derived_batch_diagnostics_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    source_paths: Sequence[Path],
    source_freq: int,
    target_freq: int,
) -> dict[str, dict[str, int]]:
    if not source_paths:
        return {
            partition_key: {
                "source_row_count": 0,
                "source_stock_day_count": 0,
                "expected_window_count": 0,
                "generated_window_count": 0,
                "incomplete_window_count": 0,
                "exchange_mismatch_window_count": 0,
            }
            for partition_key in partition_keys
        }
    source = _read_parquet_paths(source_paths)
    window_rows_sql = _derived_window_rows_sql(target_freq)
    completion_predicate = _derived_window_completion_predicate(
        target_freq,
        source_row_count_column="coalesce(actual_windows.source_row_count, 0)",
        window_id_column="expected_windows.window_id",
    )
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS (VALUES {_values_sql(partition_keys)}),
        source_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(exchange AS VARCHAR) AS exchange
          FROM {source}
          WHERE CAST(freq AS INTEGER) = {source_freq}
        ),
        selected_source_rows AS (
          SELECT source_rows.*
          FROM source_rows
          INNER JOIN selected
            ON source_rows.partition_key = selected.partition_key
        ),
        source_stock_days AS (
          SELECT DISTINCT partition_key, ts_code, trade_date
          FROM selected_source_rows
        ),
        window_map AS (
          {window_rows_sql}
        ),
        expected_windows AS (
          SELECT
            source_stock_days.partition_key,
            source_stock_days.ts_code,
            source_stock_days.trade_date,
            window_map.window_id,
            max(window_map.target_time) AS target_time,
            count(*) AS expected_source_row_count
          FROM source_stock_days
          CROSS JOIN window_map
          GROUP BY
            source_stock_days.partition_key,
            source_stock_days.ts_code,
            source_stock_days.trade_date,
            window_map.window_id
        ),
        windowed_rows AS (
          SELECT
            selected_source_rows.partition_key,
            selected_source_rows.ts_code,
            selected_source_rows.trade_date,
            selected_source_rows.trade_time,
            selected_source_rows.exchange,
            window_map.window_id,
            window_map.target_time
          FROM selected_source_rows
          INNER JOIN window_map
            ON strftime(selected_source_rows.trade_time, '%H:%M:%S')
             = window_map.source_time
        ),
        actual_windows AS (
          SELECT
            partition_key,
            ts_code,
            trade_date,
            window_id,
            max(trade_time) AS trade_time,
            max(target_time) AS target_time,
            count(*) AS source_row_count,
            count(DISTINCT exchange) AS exchange_count
          FROM windowed_rows
          GROUP BY partition_key, ts_code, trade_date, window_id
        ),
        window_status AS (
          SELECT
            expected_windows.partition_key,
            expected_windows.window_id,
            coalesce(actual_windows.source_row_count, 0) AS source_row_count,
            coalesce(actual_windows.exchange_count, 0) AS exchange_count,
            actual_windows.trade_time,
            expected_windows.target_time,
            actual_windows.source_row_count IS NOT NULL
              AND strftime(actual_windows.trade_time, '%H:%M:%S')
                = expected_windows.target_time
              AND ({completion_predicate}) AS generated
          FROM expected_windows
          LEFT JOIN actual_windows
            ON expected_windows.partition_key = actual_windows.partition_key
           AND expected_windows.ts_code = actual_windows.ts_code
           AND expected_windows.trade_date = actual_windows.trade_date
           AND expected_windows.window_id = actual_windows.window_id
        ),
        source_aggregates AS (
          SELECT
            partition_key,
            count(*) AS source_row_count,
            count(DISTINCT ts_code || '|' || CAST(trade_date AS VARCHAR))
              AS source_stock_day_count
          FROM selected_source_rows
          GROUP BY partition_key
        ),
        window_aggregates AS (
          SELECT
            partition_key,
            count(*) AS expected_window_count,
            count(*) FILTER (WHERE generated AND exchange_count = 1)
              AS generated_window_count,
            count(*) FILTER (WHERE source_row_count > 0 AND NOT generated)
              AS incomplete_window_count,
            count(*) FILTER (WHERE exchange_count > 1)
              AS exchange_mismatch_window_count
          FROM window_status
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(source_aggregates.source_row_count, 0)
            AS source_row_count,
          coalesce(source_aggregates.source_stock_day_count, 0)
            AS source_stock_day_count,
          coalesce(window_aggregates.expected_window_count, 0)
            AS expected_window_count,
          coalesce(window_aggregates.generated_window_count, 0)
            AS generated_window_count,
          coalesce(window_aggregates.incomplete_window_count, 0)
            AS incomplete_window_count,
          coalesce(window_aggregates.exchange_mismatch_window_count, 0)
            AS exchange_mismatch_window_count
        FROM selected
        LEFT JOIN source_aggregates
          ON selected.partition_key = source_aggregates.partition_key
        LEFT JOIN window_aggregates
          ON selected.partition_key = window_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "source_row_count": int(source_row_count),
            "source_stock_day_count": int(source_stock_day_count),
            "expected_window_count": int(expected_window_count),
            "generated_window_count": int(generated_window_count),
            "incomplete_window_count": int(incomplete_window_count),
            "exchange_mismatch_window_count": int(exchange_mismatch_window_count),
        }
        for (
            partition_key,
            source_row_count,
            source_stock_day_count,
            expected_window_count,
            generated_window_count,
            incomplete_window_count,
            exchange_mismatch_window_count,
        ) in rows
    }


def _gold_qfq_derived_batch_formula_counts(
    connection,
    *,
    partition_keys: Sequence[str],
    gold_paths: Sequence[Path],
    expected_select_sql: str,
    target_freq: int,
) -> dict[str, dict[str, int]]:
    if not gold_paths:
        return {
            partition_key: {
                "gold_target_row_count": 0,
                "path_mismatch_row_count": 0,
                "duplicate_key_count": 0,
                "invalid_price_row_count": 0,
                "formula_missing_gold_row_count": 0,
                "formula_unexpected_gold_row_count": 0,
                "formula_mismatch_row_count": 0,
            }
            for partition_key in partition_keys
        }
    gold_source = _read_parquet_paths(gold_paths)
    rows = connection.execute(
        f"""
        WITH selected(partition_key) AS (VALUES {_values_sql(partition_keys)}),
        gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(filename AS VARCHAR) AS filename,
            regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
              AS path_ts_code,
            regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
              AS path_year
          FROM {gold_source}
        ),
        target_gold_rows AS (
          SELECT gold_rows.*
          FROM gold_rows
          INNER JOIN selected
            ON gold_rows.partition_key = selected.partition_key
        ),
        expected_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS partition_key,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
          FROM ({expected_select_sql})
        ),
        compared_rows AS (
          SELECT
            coalesce(target_gold_rows.partition_key, expected_rows.partition_key)
              AS partition_key,
            target_gold_rows.open AS gold_open,
            expected_rows.open AS expected_open,
            target_gold_rows.high AS gold_high,
            expected_rows.high AS expected_high,
            target_gold_rows.low AS gold_low,
            expected_rows.low AS expected_low,
            target_gold_rows.close AS gold_close,
            expected_rows.close AS expected_close,
            target_gold_rows.ts_code IS NULL AS missing_gold_row,
            expected_rows.ts_code IS NULL AS unexpected_gold_row
          FROM target_gold_rows
          FULL OUTER JOIN expected_rows
            ON target_gold_rows.partition_key = expected_rows.partition_key
           AND target_gold_rows.ts_code = expected_rows.ts_code
           AND target_gold_rows.trade_time = expected_rows.trade_time
        ),
        duplicate_groups AS (
          SELECT partition_key, ts_code, trade_time, count(*) AS duplicate_count
          FROM target_gold_rows
          GROUP BY partition_key, ts_code, trade_time
          HAVING count(*) > 1
        ),
        target_gold_aggregates AS (
          SELECT
            partition_key,
            count(*) AS gold_target_row_count,
            sum(
              CASE
                WHEN freq != {target_freq}
                  OR ts_code != path_ts_code
                  OR strftime(trade_date, '%Y') != path_year
                  OR CAST(trade_time AS DATE) != trade_date
                THEN 1 ELSE 0
              END
            ) AS path_mismatch_row_count,
            sum(
              CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < low
                  OR open < low OR open > high
                  OR close < low OR close > high
                THEN 1 ELSE 0
              END
            ) AS invalid_price_row_count
          FROM target_gold_rows
          GROUP BY partition_key
        ),
        duplicate_aggregates AS (
          SELECT partition_key, count(*) AS duplicate_key_count
          FROM duplicate_groups
          GROUP BY partition_key
        ),
        formula_aggregates AS (
          SELECT
            partition_key,
            count(*) FILTER (WHERE missing_gold_row)
              AS formula_missing_gold_row_count,
            count(*) FILTER (WHERE unexpected_gold_row)
              AS formula_unexpected_gold_row_count,
            count(*) FILTER (
              WHERE NOT missing_gold_row
                AND NOT unexpected_gold_row
                AND (
                  abs(gold_open - expected_open) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_high - expected_high) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_low - expected_low) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                  OR abs(gold_close - expected_close) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
                )
            ) AS formula_mismatch_row_count
          FROM compared_rows
          GROUP BY partition_key
        )
        SELECT
          selected.partition_key,
          coalesce(target_gold_aggregates.gold_target_row_count, 0)
            AS gold_target_row_count,
          coalesce(target_gold_aggregates.path_mismatch_row_count, 0)
            AS path_mismatch_row_count,
          coalesce(duplicate_aggregates.duplicate_key_count, 0)
            AS duplicate_key_count,
          coalesce(target_gold_aggregates.invalid_price_row_count, 0)
            AS invalid_price_row_count,
          coalesce(formula_aggregates.formula_missing_gold_row_count, 0)
            AS formula_missing_gold_row_count,
          coalesce(formula_aggregates.formula_unexpected_gold_row_count, 0)
            AS formula_unexpected_gold_row_count,
          coalesce(formula_aggregates.formula_mismatch_row_count, 0)
            AS formula_mismatch_row_count
        FROM selected
        LEFT JOIN target_gold_aggregates
          ON selected.partition_key = target_gold_aggregates.partition_key
        LEFT JOIN duplicate_aggregates
          ON selected.partition_key = duplicate_aggregates.partition_key
        LEFT JOIN formula_aggregates
          ON selected.partition_key = formula_aggregates.partition_key
        ORDER BY selected.partition_key
        """
    ).fetchall()
    return {
        str(partition_key): {
            "gold_target_row_count": int(gold_target_row_count),
            "path_mismatch_row_count": int(path_mismatch_row_count),
            "duplicate_key_count": int(duplicate_key_count),
            "invalid_price_row_count": int(invalid_price_row_count),
            "formula_missing_gold_row_count": int(formula_missing_gold_row_count),
            "formula_unexpected_gold_row_count": int(
                formula_unexpected_gold_row_count
            ),
            "formula_mismatch_row_count": int(formula_mismatch_row_count),
        }
        for (
            partition_key,
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
            formula_missing_gold_row_count,
            formula_unexpected_gold_row_count,
            formula_mismatch_row_count,
        ) in rows
    }


def _gold_qfq_derived_batch_counts(
    connection,
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[
    Mapping[tuple[str, int], GoldStkMinsQfqDerivedCheckCounts],
    Mapping[tuple[str, int], tuple[Path, ...]],
]:
    counts_by_key: dict[tuple[str, int], GoldStkMinsQfqDerivedCheckCounts] = {}
    missing_paths_by_key: dict[tuple[str, int], tuple[Path, ...]] = {}
    dates_by_year: dict[str, tuple[str, ...]] = {
        year: tuple(date for date in expected_trade_dates if date.startswith(year))
        for year in sorted({date[:4] for date in expected_trade_dates})
    }
    for target_freq in STK_MINS_QFQ_DERIVED_FREQS:
        source_freq = qfq_source_freq_for_derived_freq(target_freq)
        for year, partition_keys in dates_by_year.items():
            source_paths = _gold_qfq_year_paths(
                lake_root=lake_root,
                freq=source_freq,
                year=year,
            )
            if not source_paths:
                source_root_path = gold_stk_mins_qfq_path(
                    lake_root,
                    source_freq,
                    "{ts_code}",
                    year,
                ).parents[2]
                for trade_date in partition_keys:
                    counts_by_key[(trade_date, target_freq)] = (
                        GoldStkMinsQfqDerivedCheckCounts(
                            source_freq=source_freq,
                            source_file_count=0,
                            source_row_count=0,
                            source_stock_day_count=0,
                            expected_window_count=0,
                            generated_window_count=0,
                            incomplete_window_count=0,
                            exchange_mismatch_window_count=0,
                            expected_file_count=0,
                            existing_file_count=0,
                            missing_file_count=1,
                            gold_target_row_count=0,
                            schema_mismatch_file_count=0,
                            path_mismatch_row_count=0,
                            duplicate_key_count=0,
                            invalid_price_row_count=0,
                            formula_missing_gold_row_count=0,
                            formula_unexpected_gold_row_count=0,
                            formula_mismatch_row_count=0,
                        )
                    )
                    missing_paths_by_key[(trade_date, target_freq)] = (
                        source_root_path,
                    )
                continue

            expected_select_sql = build_gold_stk_mins_qfq_derived_select_sql(
                source_qfq_paths=source_paths,
                target_freq=target_freq,
                partition_keys=partition_keys,
            )
            diagnostics_by_date = _gold_qfq_derived_batch_diagnostics_counts(
                connection,
                partition_keys=partition_keys,
                source_paths=source_paths,
                source_freq=source_freq,
                target_freq=target_freq,
            )
            expected_paths_by_date = _gold_qfq_derived_expected_paths_by_date(
                connection,
                lake_root=lake_root,
                target_freq=target_freq,
                expected_select_sql=expected_select_sql,
                expected_trade_dates=partition_keys,
            )
            missing_paths_by_date = {
                trade_date: tuple(
                    path
                    for path in expected_paths_by_date.get(trade_date, ())
                    if not path.exists()
                )
                for trade_date in partition_keys
            }
            complete_partition_keys = tuple(
                trade_date
                for trade_date in partition_keys
                if not missing_paths_by_date.get(trade_date, ())
            )
            complete_expected_paths = tuple(
                dict.fromkeys(
                    path
                    for trade_date in complete_partition_keys
                    for path in expected_paths_by_date.get(trade_date, ())
                )
            )
            existing_paths = tuple(path for path in complete_expected_paths if path.exists())
            schema_mismatch_count = 0
            if existing_paths:
                schema_mismatch_count, _observed_schema, _schema_error = (
                    _gold_qfq_schema_mismatch_count(connection, existing_paths)
                )
            formula_counts = _gold_qfq_derived_batch_formula_counts(
                connection,
                partition_keys=complete_partition_keys,
                gold_paths=existing_paths,
                expected_select_sql=expected_select_sql,
                target_freq=target_freq,
            )
            for trade_date in partition_keys:
                expected_paths = expected_paths_by_date.get(trade_date, ())
                missing_paths = missing_paths_by_date.get(trade_date, ())
                diagnostics = diagnostics_by_date.get(trade_date, {})
                formula = formula_counts.get(trade_date, {})
                target_schema_mismatch_count = 0 if missing_paths else schema_mismatch_count
                counts_by_key[(trade_date, target_freq)] = (
                    GoldStkMinsQfqDerivedCheckCounts(
                        source_freq=source_freq,
                        source_file_count=len(source_paths),
                        source_row_count=int(diagnostics.get("source_row_count", 0)),
                        source_stock_day_count=int(
                            diagnostics.get("source_stock_day_count", 0)
                        ),
                        expected_window_count=int(
                            diagnostics.get("expected_window_count", 0)
                        ),
                        generated_window_count=int(
                            diagnostics.get("generated_window_count", 0)
                        ),
                        incomplete_window_count=int(
                            diagnostics.get("incomplete_window_count", 0)
                        ),
                        exchange_mismatch_window_count=int(
                            diagnostics.get("exchange_mismatch_window_count", 0)
                        ),
                        expected_file_count=len(expected_paths),
                        existing_file_count=len(expected_paths) - len(missing_paths),
                        missing_file_count=len(missing_paths),
                        gold_target_row_count=int(
                            formula.get("gold_target_row_count", 0)
                        ),
                        schema_mismatch_file_count=int(target_schema_mismatch_count),
                        path_mismatch_row_count=int(
                            formula.get("path_mismatch_row_count", 0)
                        ),
                        duplicate_key_count=int(
                            formula.get("duplicate_key_count", 0)
                        ),
                        invalid_price_row_count=int(
                            formula.get("invalid_price_row_count", 0)
                        ),
                        formula_missing_gold_row_count=int(
                            formula.get("formula_missing_gold_row_count", 0)
                        ),
                        formula_unexpected_gold_row_count=int(
                            formula.get("formula_unexpected_gold_row_count", 0)
                        ),
                        formula_mismatch_row_count=int(
                            formula.get("formula_mismatch_row_count", 0)
                        ),
                    )
                )
                missing_paths_by_key[(trade_date, target_freq)] = missing_paths
    return counts_by_key, missing_paths_by_key


def _gold_qfq_derived_counts_for_trade_date(
    connection,
    *,
    lake_root: Path,
    trade_date: str,
    freq: int,
) -> tuple[GoldStkMinsQfqDerivedCheckCounts, tuple[Path, ...]]:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    source_freq = qfq_source_freq_for_derived_freq(normalized_freq)
    year = trade_date[:4]
    source_paths = _gold_qfq_year_paths(
        lake_root=lake_root,
        freq=source_freq,
        year=year,
    )
    if not source_paths:
        source_root_path = gold_stk_mins_qfq_path(
            lake_root,
            source_freq,
            "{ts_code}",
            year,
        ).parents[2]
        return (
            GoldStkMinsQfqDerivedCheckCounts(
                source_freq=source_freq,
                source_file_count=0,
                source_row_count=0,
                source_stock_day_count=0,
                expected_window_count=0,
                generated_window_count=0,
                incomplete_window_count=0,
                exchange_mismatch_window_count=0,
                expected_file_count=0,
                existing_file_count=0,
                missing_file_count=1,
                gold_target_row_count=0,
                schema_mismatch_file_count=0,
                path_mismatch_row_count=0,
                duplicate_key_count=0,
                invalid_price_row_count=0,
                formula_missing_gold_row_count=0,
                formula_unexpected_gold_row_count=0,
                formula_mismatch_row_count=0,
            ),
            (source_root_path,),
        )

    expected_select_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=source_paths,
        target_freq=normalized_freq,
        partition_keys=[trade_date],
    )
    (
        source_freq_from_sql,
        _target_freq,
        source_row_count,
        source_stock_day_count,
        expected_window_count,
        generated_window_count,
        incomplete_window_count,
        exchange_mismatch_window_count,
    ) = (
        int(value or 0)
        for value in connection.execute(
            build_gold_stk_mins_qfq_derived_diagnostics_sql(
                source_qfq_paths=source_paths,
                target_freq=normalized_freq,
                partition_keys=[trade_date],
            )
        ).fetchone()
    )
    expected_paths = _gold_qfq_derived_expected_paths(
        connection,
        lake_root=lake_root,
        target_freq=normalized_freq,
        partition_key=trade_date,
        expected_select_sql=expected_select_sql,
    )
    missing_gold_paths = tuple(path for path in expected_paths if not path.exists())
    existing_gold_paths = tuple(path for path in expected_paths if path.exists())
    schema_mismatch_count, _observed_schema, _schema_error = (
        _gold_qfq_schema_mismatch_count(connection, existing_gold_paths)
    )

    gold_target_row_count = 0
    path_mismatch_row_count = 0
    duplicate_key_count = 0
    invalid_price_row_count = 0
    formula_missing_gold_row_count = 0
    formula_unexpected_gold_row_count = 0
    formula_mismatch_row_count = 0

    if existing_gold_paths and schema_mismatch_count == 0:
        gold_source = _read_parquet_paths(existing_gold_paths, filename=True)
        (
            gold_target_row_count,
            path_mismatch_row_count,
            duplicate_key_count,
            invalid_price_row_count,
        ) = (
            int(value or 0)
            for value in connection.execute(
                _gold_qfq_counts_sql(
                    gold_source=gold_source,
                    partition_key=trade_date,
                    freq=normalized_freq,
                )
            ).fetchone()
        )
        (
            formula_missing_gold_row_count,
            formula_unexpected_gold_row_count,
            formula_mismatch_row_count,
        ) = (
            int(value or 0)
            for value in connection.execute(
                _gold_qfq_formula_counts_sql(
                    gold_source=gold_source,
                    qfq_select_sql=expected_select_sql,
                    partition_key=trade_date,
                )
            ).fetchone()
        )

    return (
        GoldStkMinsQfqDerivedCheckCounts(
            source_freq=source_freq_from_sql,
            source_file_count=len(source_paths),
            source_row_count=source_row_count,
            source_stock_day_count=source_stock_day_count,
            expected_window_count=expected_window_count,
            generated_window_count=generated_window_count,
            incomplete_window_count=incomplete_window_count,
            exchange_mismatch_window_count=exchange_mismatch_window_count,
            expected_file_count=len(expected_paths),
            existing_file_count=len(existing_gold_paths),
            missing_file_count=len(missing_gold_paths),
            gold_target_row_count=gold_target_row_count,
            schema_mismatch_file_count=schema_mismatch_count,
            path_mismatch_row_count=path_mismatch_row_count,
            duplicate_key_count=duplicate_key_count,
            invalid_price_row_count=invalid_price_row_count,
            formula_missing_gold_row_count=formula_missing_gold_row_count,
            formula_unexpected_gold_row_count=formula_unexpected_gold_row_count,
            formula_mismatch_row_count=formula_mismatch_row_count,
        ),
        missing_gold_paths,
    )


def _gold_qfq_derived_failed_check_names(
    counts: GoldStkMinsQfqDerivedCheckCounts,
) -> tuple[str, ...]:
    failed_check_names: list[str] = []
    formula_failed_count = (
        counts.formula_missing_gold_row_count
        + counts.formula_unexpected_gold_row_count
        + counts.formula_mismatch_row_count
    )
    if not (
        counts.expected_file_count > 0
        and counts.missing_file_count == 0
        and counts.gold_target_row_count > 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK)
    if not (
        counts.missing_file_count == 0 and counts.schema_mismatch_file_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.path_mismatch_row_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.duplicate_key_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.invalid_price_row_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK)
    if not (
        counts.source_file_count > 0
        and counts.source_row_count > 0
        and counts.source_stock_day_count > 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK)
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and counts.exchange_mismatch_window_count == 0
        and counts.gold_target_row_count == counts.generated_window_count
    ):
        failed_check_names.append(
            GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK
        )
    if not (
        counts.missing_file_count == 0
        and counts.schema_mismatch_file_count == 0
        and formula_failed_count == 0
    ):
        failed_check_names.append(GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK)
    return tuple(failed_check_names)


def _gold_qfq_status_for_trade_date(
    *,
    trade_date: str,
    lake_root: Path,
    registered_trade_day_set: set[str],
    full_semantics: bool,
    connection,
) -> StkMinsDateReadiness:
    if trade_date not in registered_trade_day_set:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"gold qfq upstream silver partition is not registered for {trade_date}",
            failed_check_names=("gold_stk_mins_qfq_upstream_partition_not_registered",),
            missing_file_paths=(),
            expected_file_count=len(STK_MINS_QFQ_FREQS),
            existing_file_count=0,
        )

    failed_check_names: list[str] = []
    missing_paths: list[Path] = []
    expected_file_count = 0
    existing_file_count = 0
    checked_row_count = 0
    failed_row_count = 0

    for freq in STK_MINS_QFQ_NATIVE_FREQS:
        counts, freq_missing_paths = _gold_qfq_native_counts_for_trade_date(
            connection,
            lake_root=lake_root,
            trade_date=trade_date,
            freq=freq,
        )
        expected_file_count += counts.expected_file_count
        existing_file_count += counts.existing_file_count
        checked_row_count += counts.gold_target_row_count
        failed_row_count += (
            counts.missing_file_count
            + counts.schema_mismatch_file_count
            + counts.path_mismatch_row_count
            + counts.duplicate_key_count
            + counts.invalid_price_row_count
            + counts.missing_trade_adj_factor_row_count
            + counts.missing_as_of_adj_factor_row_count
            + counts.formula_missing_gold_row_count
            + counts.formula_unexpected_gold_row_count
            + counts.formula_mismatch_row_count
        )
        missing_paths.extend(freq_missing_paths)
        if full_semantics:
            failed_check_names.extend(_gold_qfq_native_failed_check_names(counts))

    for freq in STK_MINS_QFQ_DERIVED_FREQS:
        counts, freq_missing_paths = _gold_qfq_derived_counts_for_trade_date(
            connection,
            lake_root=lake_root,
            trade_date=trade_date,
            freq=freq,
        )
        expected_file_count += counts.expected_file_count
        existing_file_count += counts.existing_file_count
        checked_row_count += counts.gold_target_row_count
        failed_row_count += (
            counts.missing_file_count
            + counts.schema_mismatch_file_count
            + counts.path_mismatch_row_count
            + counts.duplicate_key_count
            + counts.invalid_price_row_count
            + counts.incomplete_window_count
            + counts.exchange_mismatch_window_count
            + counts.formula_missing_gold_row_count
            + counts.formula_unexpected_gold_row_count
            + counts.formula_mismatch_row_count
        )
        missing_paths.extend(freq_missing_paths)
        if full_semantics:
            failed_check_names.extend(_gold_qfq_derived_failed_check_names(counts))

    missing_path_strings = tuple(str(path) for path in missing_paths)
    if missing_path_strings:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"gold qfq files are missing for {trade_date}",
            failed_check_names=(
                GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            ),
            missing_file_paths=missing_path_strings,
            expected_file_count=expected_file_count,
            existing_file_count=existing_file_count,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
        )

    if (
        expected_file_count > 0
        and existing_file_count == expected_file_count
        and checked_row_count == 0
    ):
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"gold qfq rows are missing for {trade_date}",
            failed_check_names=(
                GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            ),
            missing_file_paths=(),
            expected_file_count=expected_file_count,
            existing_file_count=existing_file_count,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
        )

    failed_check_names = sorted(set(failed_check_names))
    checks_passed = not failed_check_names
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=checks_passed,
        materialized=True,
        checks_passed=checks_passed,
        reason=(
            "ready"
            if checks_passed
            else "gold qfq blocking checks failed for "
            f"{trade_date}: {', '.join(failed_check_names)}"
        ),
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=(),
        expected_file_count=expected_file_count,
        existing_file_count=existing_file_count,
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
    )


def _gold_qfq_statuses_from_batch_counts(
    *,
    expected_trade_dates: Sequence[str],
    registered_trade_day_set: set[str],
    native_plans: Sequence[_GoldQfqNativePathPlan],
    native_counts_by_key: Mapping[tuple[str, int], GoldStkMinsQfqCheckCounts],
    derived_counts_by_key: Mapping[tuple[str, int], GoldStkMinsQfqDerivedCheckCounts],
    derived_missing_paths_by_key: Mapping[tuple[str, int], tuple[Path, ...]],
    full_semantics: bool,
) -> dict[str, StkMinsDateReadiness]:
    native_plans_by_key = {
        (plan.trade_date, plan.freq): plan for plan in native_plans
    }
    statuses_by_trade_date: dict[str, StkMinsDateReadiness] = {}
    for trade_date in expected_trade_dates:
        if trade_date not in registered_trade_day_set:
            statuses_by_trade_date[trade_date] = StkMinsDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=(
                    "gold qfq upstream silver partition is not registered "
                    f"for {trade_date}"
                ),
                failed_check_names=(
                    "gold_stk_mins_qfq_upstream_partition_not_registered",
                ),
                missing_file_paths=(),
                expected_file_count=len(STK_MINS_QFQ_FREQS),
                existing_file_count=0,
            )
            continue

        failed_check_names: list[str] = []
        missing_paths: list[Path] = []
        expected_file_count = 0
        existing_file_count = 0
        checked_row_count = 0
        failed_row_count = 0

        for freq in STK_MINS_QFQ_NATIVE_FREQS:
            key = (trade_date, freq)
            counts = native_counts_by_key[key]
            plan = native_plans_by_key[key]
            expected_file_count += counts.expected_file_count
            existing_file_count += counts.existing_file_count
            checked_row_count += counts.gold_target_row_count
            failed_row_count += (
                counts.missing_file_count
                + counts.schema_mismatch_file_count
                + counts.path_mismatch_row_count
                + counts.duplicate_key_count
                + counts.invalid_price_row_count
                + counts.missing_trade_adj_factor_row_count
                + counts.missing_as_of_adj_factor_row_count
                + counts.formula_missing_gold_row_count
                + counts.formula_unexpected_gold_row_count
                + counts.formula_mismatch_row_count
            )
            missing_paths.extend(plan.missing_paths)
            if full_semantics:
                failed_check_names.extend(_gold_qfq_native_failed_check_names(counts))

        for freq in STK_MINS_QFQ_DERIVED_FREQS:
            key = (trade_date, freq)
            counts = derived_counts_by_key[key]
            expected_file_count += counts.expected_file_count
            existing_file_count += counts.existing_file_count
            checked_row_count += counts.gold_target_row_count
            failed_row_count += (
                counts.missing_file_count
                + counts.schema_mismatch_file_count
                + counts.path_mismatch_row_count
                + counts.duplicate_key_count
                + counts.invalid_price_row_count
                + counts.incomplete_window_count
                + counts.exchange_mismatch_window_count
                + counts.formula_missing_gold_row_count
                + counts.formula_unexpected_gold_row_count
                + counts.formula_mismatch_row_count
            )
            missing_paths.extend(derived_missing_paths_by_key.get(key, ()))
            if full_semantics:
                failed_check_names.extend(_gold_qfq_derived_failed_check_names(counts))

        missing_path_strings = tuple(str(path) for path in missing_paths)
        if missing_path_strings:
            statuses_by_trade_date[trade_date] = StkMinsDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=f"gold qfq files are missing for {trade_date}",
                failed_check_names=(
                    GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                ),
                missing_file_paths=missing_path_strings,
                expected_file_count=expected_file_count,
                existing_file_count=existing_file_count,
                checked_row_count=checked_row_count,
                failed_row_count=failed_row_count,
            )
            continue

        if (
            expected_file_count > 0
            and existing_file_count == expected_file_count
            and checked_row_count == 0
        ):
            statuses_by_trade_date[trade_date] = StkMinsDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=f"gold qfq rows are missing for {trade_date}",
                failed_check_names=(
                    GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                ),
                missing_file_paths=(),
                expected_file_count=expected_file_count,
                existing_file_count=existing_file_count,
                checked_row_count=checked_row_count,
                failed_row_count=failed_row_count,
            )
            continue

        failed_check_names = sorted(set(failed_check_names))
        checks_passed = not failed_check_names
        statuses_by_trade_date[trade_date] = StkMinsDateReadiness(
            trade_date=trade_date,
            ready=checks_passed,
            materialized=True,
            checks_passed=checks_passed,
            reason=(
                "ready"
                if checks_passed
                else "gold qfq blocking checks failed for "
                f"{trade_date}: {', '.join(failed_check_names)}"
            ),
            failed_check_names=tuple(failed_check_names),
            missing_file_paths=(),
            expected_file_count=expected_file_count,
            existing_file_count=existing_file_count,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
        )
    return statuses_by_trade_date


def batch_gold_stk_mins_qfq_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    full_semantics: bool = True,
) -> StkMinsBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = _normalize_trade_dates(expected_trade_dates)
    registered_trade_day_set = set(_normalize_trade_dates(registered_trade_days))
    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    native_plans = _gold_qfq_native_path_plans(
        connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
    )
    native_counts_by_key = _gold_qfq_native_batch_counts(
        connection,
        native_plans=native_plans,
    )
    derived_counts_by_key, derived_missing_paths_by_key = (
        _gold_qfq_derived_batch_counts(
            connection,
            lake_root=lake_root,
            expected_trade_dates=expected_trade_dates,
        )
    )
    statuses_by_trade_date = _gold_qfq_statuses_from_batch_counts(
        expected_trade_dates=expected_trade_dates,
        registered_trade_day_set=registered_trade_day_set,
        native_plans=native_plans,
        native_counts_by_key=native_counts_by_key,
        derived_counts_by_key=derived_counts_by_key,
        derived_missing_paths_by_key=derived_missing_paths_by_key,
        full_semantics=full_semantics,
    )
    elapsed_ms = (perf_counter() - started_at) * 1000
    return StkMinsBatchReadiness(
        dataset="gold_stk_mins_qfq",
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        freq_count=len(STK_MINS_QFQ_FREQS),
        elapsed_ms=elapsed_ms,
        statuses_by_trade_date=statuses_by_trade_date,
    )
