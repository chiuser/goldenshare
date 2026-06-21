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
    RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
    RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
    RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
    RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
    RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK,
    SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK,
    SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK,
    SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
    SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK,
    SILVER_STK_MINS_PRICE_SANITY_CHECK,
    SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK,
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
            failed_check_names=(RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,),
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
            failed_check_names=(
                RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            ),
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
            failed_check_names.append(
                RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
            )
        if full_semantics and path_plan.path not in schema_valid_paths:
            failed_check_names.append(RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK)
        if full_semantics and metrics.freq_failed_count:
            failed_check_names.append(RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK)
        if full_semantics and metrics.date_failed_count:
            failed_check_names.append(RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK)
        if full_semantics and metrics.duplicate_failed_count:
            failed_check_names.append(RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
        if full_semantics and metrics.sanity_failed_count:
            failed_check_names.append(RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK)

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
            failed_check_names=("silver_stk_mins_partition_not_registered",),
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
            failed_check_names=(
                SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            ),
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
            failed_check_names.append(
                SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
            )
        if full_semantics and path_plan.path not in schema_valid_paths:
            failed_check_names.append(SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK)
        if full_semantics and metrics.freq_partition_failed_count:
            failed_check_names.append(SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK)
        if full_semantics and metrics.duplicate_failed_count:
            failed_check_names.append(SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
        if full_semantics and metrics.price_failed_count:
            failed_check_names.append(SILVER_STK_MINS_PRICE_SANITY_CHECK)
        if full_semantics and metrics.volume_amount_failed_count:
            failed_check_names.append(SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK)
        if full_semantics and metrics.exchange_failed_count:
            failed_check_names.append(SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK)
        if full_semantics and (
            not path_plan.stock_daily_path.exists()
            or metrics.missing_stock_daily_code_count
        ):
            failed_check_names.append(SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK)
        if full_semantics and (
            not path_plan.suspend_path.exists()
            or metrics.full_day_suspend_failed_count
        ):
            failed_check_names.append(
                SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK
            )
        if full_semantics and (
            not stock_lifecycle_path.exists() or metrics.lifecycle_failed_count
        ):
            failed_check_names.append(SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK)

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
    statuses_by_trade_date = {
        trade_date: _gold_qfq_status_for_trade_date(
            trade_date=trade_date,
            lake_root=lake_root,
            registered_trade_day_set=registered_trade_day_set,
            full_semantics=full_semantics,
            connection=connection,
        )
        for trade_date in expected_trade_dates
    }
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
