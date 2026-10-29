"""Lake-file readiness helpers for adj factor hot-path sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.assets.adj_factor import (
    ADJ_FACTOR_RAW_COLUMN_TYPES,
    ADJ_FACTOR_SILVER_COLUMN_TYPES,
)
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    adj_factor_required_stock_predicate_sql,
    adj_factor_required_stock_select,
    adj_factor_retained_record_predicate_sql,
    adj_factor_retained_stock_select,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_adj_factor_select_from_relations,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
from orchestrator.defs.stock_factor_price_checks import (
    ADJ_FACTOR_INVALID_VALUE_PREDICATE,
)

RAW_ADJ_FACTOR_FILE_EXISTS_CHECK = "raw_adj_factor_file_exists"
RAW_ADJ_FACTOR_PARTITION_DATE_MATCHES_CHECK = "raw_adj_factor_partition_date_matches"
RAW_ADJ_FACTOR_POSITIVE_FACTOR_CHECK = "raw_adj_factor_positive_factor"
RAW_ADJ_FACTOR_REQUIRED_COLUMNS_CHECK = "raw_adj_factor_required_columns"
RAW_ADJ_FACTOR_ROW_COUNT_POSITIVE_CHECK = "raw_adj_factor_row_count_positive"
RAW_ADJ_FACTOR_SCHEMA_MATCHES_TUSHARE_CONTRACT_CHECK = (
    "raw_adj_factor_schema_matches_tushare_contract"
)
RAW_ADJ_FACTOR_STOCK_CURRENT_PARTITION_KEY_ALLOWED_CHECK = (
    "raw_adj_factor_stock_current_partition_key_allowed"
)
RAW_ADJ_FACTOR_UNIQUE_TS_CODE_TRADE_DATE_CHECK = (
    "raw_adj_factor_unique_ts_code_trade_date"
)
SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK = "silver_adj_factor_coverage_complete"
SILVER_ADJ_FACTOR_FILE_EXISTS_CHECK = "silver_adj_factor_file_exists"
SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK = "silver_adj_factor_listed_stock_only"
SILVER_ADJ_FACTOR_PARTITION_DATE_MATCHES_CHECK = (
    "silver_adj_factor_partition_date_matches"
)
SILVER_ADJ_FACTOR_POSITIVE_FACTOR_CHECK = "silver_adj_factor_positive_factor"
SILVER_ADJ_FACTOR_REQUIRED_COLUMNS_CHECK = "silver_adj_factor_required_columns"
SILVER_ADJ_FACTOR_ROW_COUNT_POSITIVE_CHECK = "silver_adj_factor_row_count_positive"
SILVER_ADJ_FACTOR_SCHEMA_MATCHES_CONTRACT_CHECK = (
    "silver_adj_factor_schema_matches_contract"
)
SILVER_ADJ_FACTOR_STOCK_CURRENT_PARTITION_KEY_ALLOWED_CHECK = (
    "silver_adj_factor_stock_current_partition_key_allowed"
)
SILVER_ADJ_FACTOR_UNIQUE_TS_CODE_TRADE_DATE_CHECK = (
    "silver_adj_factor_unique_ts_code_trade_date"
)
SILVER_ADJ_FACTOR_LIFECYCLE_REBUILDABLE_CHECKS = frozenset(
    {
        SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK,
        SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
    }
)


@dataclass(frozen=True)
class _AdjFactorPathPlan:
    trade_date: str
    raw_path: Path
    silver_path: Path


@dataclass(frozen=True)
class _AdjFactorPathMetrics:
    raw_row_count: int = 0
    silver_row_count: int = 0
    raw_date_failed_count: int = 0
    raw_duplicate_failed_count: int = 0
    raw_positive_failed_count: int = 0
    silver_date_failed_count: int = 0
    silver_duplicate_failed_count: int = 0
    silver_positive_failed_count: int = 0
    silver_listed_failed_count: int = 0
    silver_missing_code_count: int = 0
    silver_unexpected_code_count: int = 0
    silver_retained_source_failed_count: int = 0


@dataclass(frozen=True)
class SilverAdjFactorLifecycleRebuildAssessment:
    """Whether one failed silver partition can be safely rebuilt from current inputs."""

    eligible: bool
    reason_code: str
    failed_check_names: tuple[str, ...]
    expected_code_count: int = 0
    raw_missing_code_count: int = 0
    raw_missing_code_samples: tuple[str, ...] = ()


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


def _expected_bounds(values: Sequence[str]) -> tuple[str | None, str | None]:
    if not values:
        return None, None
    return values[0], values[-1]


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


def _path_list_sql(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(duckdb_string(str(path)) for path in paths) + "]"


def _values_relation(rows: Sequence[tuple[str, str]]) -> str:
    if not rows:
        return "SELECT NULL::VARCHAR AS filename, NULL::DATE AS trade_date WHERE false"
    values = ", ".join(
        f"({duckdb_string(filename)}, CAST({duckdb_string(trade_date)} AS DATE))"
        for filename, trade_date in rows
    )
    return f"(VALUES {values}) AS path_plan(filename, trade_date)"


def _adj_factor_path_plans(
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[_AdjFactorPathPlan, ...]:
    return tuple(
        _AdjFactorPathPlan(
            trade_date=trade_date,
            raw_path=raw_adj_factor_path(lake_root, trade_date),
            silver_path=silver_adj_factor_path(lake_root, trade_date),
        )
        for trade_date in expected_trade_dates
    )


def _raw_metrics_by_trade_date(
    connection,
    path_plans: Sequence[_AdjFactorPathPlan],
    *, source_sql: str | None = None,
) -> dict[str, _AdjFactorPathMetrics]:
    existing_plans = tuple(path_plan for path_plan in path_plans if path_plan.raw_path.exists())
    if not existing_plans:
        return {}

    path_relation = _values_relation(
        tuple((str(path_plan.raw_path), path_plan.trade_date) for path_plan in existing_plans)
    )
    paths = tuple(path_plan.raw_path for path_plan in existing_plans)
    source_sql = source_sql or f"read_parquet({_path_list_sql(paths)}, filename=true, hive_partitioning=false)"
    rows = connection.execute(
        f"""
        WITH path_plan AS (
          SELECT filename, trade_date FROM {path_relation}
        ),
        raw_rows AS (
          SELECT
            path_plan.trade_date AS expected_trade_date,
            CAST(raw.ts_code AS VARCHAR) AS ts_code,
            try_strptime(CAST(raw.trade_date AS VARCHAR), '%Y%m%d')::DATE AS trade_date,
            CAST(raw.adj_factor AS DOUBLE) AS adj_factor
          FROM {source_sql} raw
          INNER JOIN path_plan USING (filename)
        ),
        duplicate_keys AS (
          SELECT expected_trade_date, count(*) AS duplicate_failed_count
          FROM (
            SELECT expected_trade_date, ts_code, trade_date, count(*) AS row_count
            FROM raw_rows
            GROUP BY expected_trade_date, ts_code, trade_date
            HAVING count(*) > 1
          )
          GROUP BY expected_trade_date
        )
        SELECT
          raw_rows.expected_trade_date,
          count(*) AS row_count,
          count(*) FILTER (
            WHERE raw_rows.trade_date IS NULL
               OR raw_rows.trade_date != raw_rows.expected_trade_date
          ) AS date_failed_count,
          coalesce(max(duplicate_keys.duplicate_failed_count), 0)
            AS duplicate_failed_count,
          count(*) FILTER (
            WHERE {ADJ_FACTOR_INVALID_VALUE_PREDICATE.replace('adj_factor', 'raw_rows.adj_factor')}
          ) AS positive_failed_count
        FROM raw_rows
        LEFT JOIN duplicate_keys USING (expected_trade_date)
        GROUP BY raw_rows.expected_trade_date
        """
    ).fetchall()
    return {
        str(row[0]): _AdjFactorPathMetrics(
            raw_row_count=int(row[1] or 0),
            raw_date_failed_count=int(row[2] or 0),
            raw_duplicate_failed_count=int(row[3] or 0),
            raw_positive_failed_count=int(row[4] or 0),
        )
        for row in rows
    }


def _silver_metrics_by_trade_date(
    connection, *, path_plans: Sequence[_AdjFactorPathPlan], stock_lifecycle_path: Path,
    raw_source_sql: str | None = None,
) -> dict[str, _AdjFactorPathMetrics]:
    """One vectorized date batch: allowed, required, and retained Raw rows."""
    existing = tuple(p for p in path_plans if p.silver_path.exists())
    if not existing:
        return {}
    relation = _values_relation(tuple((str(p.silver_path), p.trade_date) for p in existing))
    raw_plans = tuple(p for p in existing if p.raw_path.exists()
                      and p.trade_date >= ADJ_FACTOR_RETIRED_RETENTION_START_DATE)
    raw_relation = _values_relation(tuple((str(p.raw_path), p.trade_date) for p in raw_plans))
    raw_plan_sql = f"SELECT filename,trade_date FROM {raw_relation}" if raw_plans else raw_relation
    raw_source_sql = raw_source_sql or (
        f"read_parquet({_path_list_sql(tuple(p.raw_path for p in raw_plans))}, filename=true,hive_partitioning=false)"
        if raw_plans else None
    )
    raw_rows = (
        f"""SELECT raw_plan.trade_date expected_trade_date,CAST(raw.ts_code AS VARCHAR) ts_code,
          try_strptime(CAST(raw.trade_date AS VARCHAR),'%Y%m%d')::DATE trade_date,
          CAST(raw.adj_factor AS DOUBLE) adj_factor
          FROM {raw_source_sql} raw
          JOIN raw_plan USING(filename)"""
        if raw_plans else
        "SELECT NULL::DATE expected_trade_date,NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::DOUBLE adj_factor WHERE false"
    )
    lifecycle = adj_factor_retained_stock_select(stock_lifecycle_path)
    boundary = f"DATE {duckdb_string(ADJ_FACTOR_RETIRED_RETENTION_START_DATE)}"
    rows = connection.execute(f"""
      WITH path_plan AS (SELECT filename,trade_date FROM {relation}),
      raw_plan AS ({raw_plan_sql}),
      lifecycle AS MATERIALIZED ({lifecycle}),
      silver_rows AS MATERIALIZED (
        SELECT path_plan.trade_date expected_trade_date,CAST(silver.ts_code AS VARCHAR) ts_code,
          CAST(silver.trade_date AS DATE) trade_date,CAST(silver.adj_factor AS DOUBLE) adj_factor
        FROM read_parquet({_path_list_sql(tuple(p.silver_path for p in existing))},
          filename=true,hive_partitioning=false) silver JOIN path_plan USING(filename)
      ),
      duplicate_keys AS (
        SELECT expected_trade_date,count(*) duplicate_failed_count FROM (
          SELECT expected_trade_date,ts_code,trade_date FROM silver_rows
          GROUP BY expected_trade_date,ts_code,trade_date HAVING count(*)>1
        ) GROUP BY expected_trade_date
      ),
      expected_codes AS (
        SELECT path_plan.trade_date expected_trade_date,lifecycle.ts_code
        FROM path_plan JOIN lifecycle ON {adj_factor_required_stock_predicate_sql("path_plan.trade_date")}
      ),
      allowed_codes AS (
        SELECT path_plan.trade_date expected_trade_date,lifecycle.ts_code
        FROM path_plan JOIN lifecycle ON {adj_factor_retained_record_predicate_sql("path_plan.trade_date")}
      ),
      actual_codes AS (SELECT DISTINCT expected_trade_date,ts_code FROM silver_rows),
      missing AS (SELECT * FROM expected_codes EXCEPT SELECT * FROM actual_codes),
      unexpected AS (SELECT * FROM actual_codes EXCEPT SELECT * FROM allowed_codes),
      raw_rows AS MATERIALIZED ({raw_rows}),
      retained_source AS (
        {silver_adj_factor_select_from_relations(
            f"SELECT * FROM raw_rows WHERE expected_trade_date >= {boundary}",
            "SELECT * FROM lifecycle",
        )}
      ),
      new_silver AS (SELECT * FROM silver_rows WHERE expected_trade_date>={boundary}),
      source_differences AS (
        (SELECT * FROM retained_source EXCEPT ALL SELECT * FROM new_silver)
        UNION ALL
        (SELECT * FROM new_silver EXCEPT ALL SELECT * FROM retained_source)
      )
      SELECT silver_rows.expected_trade_date,count(*),
        count(*) FILTER(WHERE silver_rows.trade_date IS NULL
          OR silver_rows.trade_date<>silver_rows.expected_trade_date),
        coalesce(max(duplicate_keys.duplicate_failed_count),0),
        count(*) FILTER(WHERE {ADJ_FACTOR_INVALID_VALUE_PREDICATE.replace('adj_factor','silver_rows.adj_factor')}),
        count(*) FILTER(WHERE NOT ({adj_factor_retained_record_predicate_sql("silver_rows.trade_date")})),
        (SELECT count(*) FROM missing WHERE missing.expected_trade_date=silver_rows.expected_trade_date),
        (SELECT count(*) FROM unexpected WHERE unexpected.expected_trade_date=silver_rows.expected_trade_date),
        (SELECT count(*) FROM source_differences d WHERE d.expected_trade_date=silver_rows.expected_trade_date)
          + CASE WHEN silver_rows.expected_trade_date>={boundary}
            AND NOT EXISTS(SELECT 1 FROM raw_plan WHERE raw_plan.trade_date=silver_rows.expected_trade_date)
            THEN 1 ELSE 0 END
      FROM silver_rows LEFT JOIN duplicate_keys USING(expected_trade_date)
      LEFT JOIN lifecycle USING(ts_code) GROUP BY silver_rows.expected_trade_date
    """).fetchall()
    fields = ("silver_row_count", "silver_date_failed_count", "silver_duplicate_failed_count",
              "silver_positive_failed_count", "silver_listed_failed_count", "silver_missing_code_count",
              "silver_unexpected_code_count", "silver_retained_source_failed_count")
    return {str(row[0]): _AdjFactorPathMetrics(**dict(zip(fields, (int(value or 0) for value in row[1:]), strict=True)))
            for row in rows}


def _merge_metrics(
    raw_metrics: _AdjFactorPathMetrics,
    silver_metrics: _AdjFactorPathMetrics,
) -> _AdjFactorPathMetrics:
    return _AdjFactorPathMetrics(
        raw_row_count=raw_metrics.raw_row_count,
        silver_row_count=silver_metrics.silver_row_count,
        raw_date_failed_count=raw_metrics.raw_date_failed_count,
        raw_duplicate_failed_count=raw_metrics.raw_duplicate_failed_count,
        raw_positive_failed_count=raw_metrics.raw_positive_failed_count,
        silver_date_failed_count=silver_metrics.silver_date_failed_count,
        silver_duplicate_failed_count=silver_metrics.silver_duplicate_failed_count,
        silver_positive_failed_count=silver_metrics.silver_positive_failed_count,
        silver_listed_failed_count=silver_metrics.silver_listed_failed_count,
        silver_missing_code_count=silver_metrics.silver_missing_code_count,
        silver_unexpected_code_count=silver_metrics.silver_unexpected_code_count,
        silver_retained_source_failed_count=silver_metrics.silver_retained_source_failed_count,
    )


def _metrics_by_trade_date(
    connection, *, path_plans: Sequence[_AdjFactorPathPlan], stock_lifecycle_path: Path,
    layer: str = "combined",
) -> dict[str, _AdjFactorPathMetrics]:
    if layer == "raw":
        return _raw_metrics_by_trade_date(connection, path_plans)
    if layer == "silver":
        return _silver_metrics_by_trade_date(connection, path_plans=path_plans,
                                            stock_lifecycle_path=stock_lifecycle_path)
    # The combined consumer needs both checks. Read the bounded Raw batch once,
    # then reuse an in-memory table, never a second scan or persistent cache.
    paths = tuple(p.raw_path for p in path_plans if p.raw_path.exists())
    raw_source = None
    if paths:
        raw_source = "_adj_factor_readiness_raw"
        connection.execute(f"""CREATE TEMP TABLE {raw_source} AS
          SELECT CAST(ts_code AS VARCHAR) ts_code,CAST(trade_date AS VARCHAR) trade_date,
            CAST(adj_factor AS DOUBLE) adj_factor,filename
          FROM read_parquet({_path_list_sql(paths)},filename=true,hive_partitioning=false)""")
    try:
        raw_metrics = _raw_metrics_by_trade_date(connection, path_plans, source_sql=raw_source)
        silver_metrics = _silver_metrics_by_trade_date(connection, path_plans=path_plans,
            stock_lifecycle_path=stock_lifecycle_path, raw_source_sql=raw_source)
        return {
            p.trade_date: _merge_metrics(raw_metrics.get(p.trade_date, _AdjFactorPathMetrics()),
                                        silver_metrics.get(p.trade_date, _AdjFactorPathMetrics()))
            for p in path_plans
        }
    finally:
        if raw_source is not None:
            connection.execute(f"DROP TABLE {raw_source}")


def assess_silver_adj_factor_lifecycle_rebuildability(
    *,
    connection,
    lake_root: Path,
    trade_date: str,
    raw_status: ContinuityDateReadiness,
    silver_status: ContinuityDateReadiness,
    sample_limit: int = 5,
) -> SilverAdjFactorLifecycleRebuildAssessment:
    """Assess the narrow lifecycle-only rebuild path for one silver partition.

    The normal sensor path must not call this helper. It is only for an existing
    silver file whose physical readiness reports lifecycle-derived failures.
    """

    if sample_limit < 1:
        raise ValueError("sample_limit must be at least 1")

    failed_check_names = tuple(silver_status.failed_check_names)
    if silver_status.ready:
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="silver_already_ready",
            failed_check_names=failed_check_names,
        )
    if trade_date < ADJ_FACTOR_RETIRED_RETENTION_START_DATE:
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False, reason_code="historical_partition_requires_explicit_restore",
            failed_check_names=failed_check_names,
        )
    if not silver_status.materialized:
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="silver_not_materialized",
            failed_check_names=failed_check_names,
        )
    if not raw_status.ready:
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="raw_not_ready",
            failed_check_names=failed_check_names,
        )

    failed_check_set = set(failed_check_names)
    if (
        not failed_check_set
        or not failed_check_set.issubset(SILVER_ADJ_FACTOR_LIFECYCLE_REBUILDABLE_CHECKS)
    ):
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="non_lifecycle_silver_check_failed",
            failed_check_names=failed_check_names,
        )

    raw_path = raw_adj_factor_path(lake_root, trade_date)
    silver_path = silver_adj_factor_path(lake_root, trade_date)
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root)
    if not raw_path.exists():
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="raw_file_missing",
            failed_check_names=failed_check_names,
        )
    if not silver_path.exists():
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="silver_file_missing",
            failed_check_names=failed_check_names,
        )
    if not stock_lifecycle_path.exists():
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="stock_lifecycle_file_missing",
            failed_check_names=failed_check_names,
        )

    expected_codes_sql = adj_factor_required_stock_select(stock_lifecycle_path, trade_date)
    raw_codes_sql = f"""
        SELECT DISTINCT CAST(raw.ts_code AS VARCHAR) AS ts_code
        FROM {read_parquet(raw_path, hive_partitioning=False)} raw
        WHERE try_strptime(CAST(raw.trade_date AS VARCHAR), '%Y%m%d')::DATE
          = DATE {duckdb_string(trade_date)}
    """
    expected_code_count, raw_missing_code_count = connection.execute(
        f"""
        WITH expected_codes AS ({expected_codes_sql}),
        raw_codes AS ({raw_codes_sql})
        SELECT
          count(*) AS expected_code_count,
          count(*) FILTER (WHERE raw_codes.ts_code IS NULL) AS raw_missing_code_count
        FROM expected_codes
        LEFT JOIN raw_codes USING (ts_code)
        """
    ).fetchone()
    expected_code_count = int(expected_code_count or 0)
    raw_missing_code_count = int(raw_missing_code_count or 0)
    if raw_missing_code_count:
        rows = connection.execute(
            f"""
            WITH expected_codes AS ({expected_codes_sql}),
            raw_codes AS ({raw_codes_sql})
            SELECT expected_codes.ts_code
            FROM expected_codes
            LEFT JOIN raw_codes USING (ts_code)
            WHERE raw_codes.ts_code IS NULL
            ORDER BY expected_codes.ts_code
            LIMIT {sample_limit}
            """
        ).fetchall()
        return SilverAdjFactorLifecycleRebuildAssessment(
            eligible=False,
            reason_code="raw_missing_lifecycle_coverage",
            failed_check_names=failed_check_names,
            expected_code_count=expected_code_count,
            raw_missing_code_count=raw_missing_code_count,
            raw_missing_code_samples=tuple(str(row[0]) for row in rows),
        )

    return SilverAdjFactorLifecycleRebuildAssessment(
        eligible=True,
        reason_code="lifecycle_rebuild_eligible",
        failed_check_names=failed_check_names,
        expected_code_count=expected_code_count,
    )


def _raw_status_for_trade_date(
    *,
    trade_date: str,
    path_plan: _AdjFactorPathPlan,
    registered_trade_day_set: set[str],
    raw_schema_valid_paths: set[Path],
    raw_required_column_valid_paths: set[Path],
    metrics: _AdjFactorPathMetrics,
    full_semantics: bool,
) -> ContinuityDateReadiness:
    missing_file_paths = [] if path_plan.raw_path.exists() else [str(path_plan.raw_path)]
    failed_check_names: list[str] = []
    if trade_date not in registered_trade_day_set:
        failed_check_names.append(RAW_ADJ_FACTOR_STOCK_CURRENT_PARTITION_KEY_ALLOWED_CHECK)
    if missing_file_paths:
        failed_check_names.append(RAW_ADJ_FACTOR_FILE_EXISTS_CHECK)

    materialized = not missing_file_paths
    if materialized:
        if metrics.raw_row_count <= 0:
            failed_check_names.append(RAW_ADJ_FACTOR_ROW_COUNT_POSITIVE_CHECK)
        if full_semantics:
            if path_plan.raw_path not in raw_schema_valid_paths:
                failed_check_names.append(RAW_ADJ_FACTOR_SCHEMA_MATCHES_TUSHARE_CONTRACT_CHECK)
            if path_plan.raw_path not in raw_required_column_valid_paths:
                failed_check_names.append(RAW_ADJ_FACTOR_REQUIRED_COLUMNS_CHECK)
            if metrics.raw_date_failed_count:
                failed_check_names.append(RAW_ADJ_FACTOR_PARTITION_DATE_MATCHES_CHECK)
            if metrics.raw_duplicate_failed_count:
                failed_check_names.append(RAW_ADJ_FACTOR_UNIQUE_TS_CODE_TRADE_DATE_CHECK)
            if metrics.raw_positive_failed_count:
                failed_check_names.append(RAW_ADJ_FACTOR_POSITIVE_FACTOR_CHECK)

    checks_passed = not failed_check_names
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "raw_adj_factor_not_ready",
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=tuple(missing_file_paths),
        summary={
            "raw_row_count": metrics.raw_row_count,
            "raw_date_failed_count": metrics.raw_date_failed_count,
            "raw_duplicate_failed_count": metrics.raw_duplicate_failed_count,
            "raw_positive_failed_count": metrics.raw_positive_failed_count,
        },
    )


def _silver_status_for_trade_date(
    *,
    trade_date: str,
    path_plan: _AdjFactorPathPlan,
    registered_trade_day_set: set[str],
    stock_lifecycle_path: Path,
    silver_schema_valid_paths: set[Path],
    silver_required_column_valid_paths: set[Path],
    metrics: _AdjFactorPathMetrics,
    full_semantics: bool,
) -> ContinuityDateReadiness:
    missing_file_paths = [] if path_plan.silver_path.exists() else [str(path_plan.silver_path)]
    failed_check_names: list[str] = []
    if trade_date not in registered_trade_day_set:
        failed_check_names.append(SILVER_ADJ_FACTOR_STOCK_CURRENT_PARTITION_KEY_ALLOWED_CHECK)
    if missing_file_paths:
        failed_check_names.append(SILVER_ADJ_FACTOR_FILE_EXISTS_CHECK)

    materialized = not missing_file_paths
    if materialized:
        if metrics.silver_row_count <= 0:
            failed_check_names.append(SILVER_ADJ_FACTOR_ROW_COUNT_POSITIVE_CHECK)
        if full_semantics:
            if path_plan.silver_path not in silver_schema_valid_paths:
                failed_check_names.append(SILVER_ADJ_FACTOR_SCHEMA_MATCHES_CONTRACT_CHECK)
            if path_plan.silver_path not in silver_required_column_valid_paths:
                failed_check_names.append(SILVER_ADJ_FACTOR_REQUIRED_COLUMNS_CHECK)
            if metrics.silver_date_failed_count:
                failed_check_names.append(SILVER_ADJ_FACTOR_PARTITION_DATE_MATCHES_CHECK)
            if metrics.silver_duplicate_failed_count:
                failed_check_names.append(SILVER_ADJ_FACTOR_UNIQUE_TS_CODE_TRADE_DATE_CHECK)
            if metrics.silver_positive_failed_count:
                failed_check_names.append(SILVER_ADJ_FACTOR_POSITIVE_FACTOR_CHECK)
            if (
                not stock_lifecycle_path.exists()
                or metrics.silver_listed_failed_count
            ):
                failed_check_names.append(SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK)
            if metrics.silver_missing_code_count or metrics.silver_unexpected_code_count or metrics.silver_retained_source_failed_count:
                failed_check_names.append(SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK)

    checks_passed = not failed_check_names
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "silver_adj_factor_not_ready",
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=tuple(missing_file_paths),
        summary={
            "silver_row_count": metrics.silver_row_count,
            "silver_date_failed_count": metrics.silver_date_failed_count,
            "silver_duplicate_failed_count": metrics.silver_duplicate_failed_count,
            "silver_positive_failed_count": metrics.silver_positive_failed_count,
            "silver_listed_failed_count": metrics.silver_listed_failed_count,
            "silver_missing_code_count": metrics.silver_missing_code_count,
            "silver_unexpected_code_count": metrics.silver_unexpected_code_count,
            "silver_retained_source_failed_count": metrics.silver_retained_source_failed_count,
        },
    )


def _combined_status_for_trade_date(
    *,
    trade_date: str,
    raw_status: ContinuityDateReadiness,
    silver_status: ContinuityDateReadiness,
) -> ContinuityDateReadiness:
    materialized = raw_status.materialized and silver_status.materialized
    checks_passed = raw_status.checks_passed and silver_status.checks_passed
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "adj_factor_not_ready",
        failed_check_names=(
            *raw_status.failed_check_names,
            *silver_status.failed_check_names,
        ),
        missing_file_paths=(
            *raw_status.missing_file_paths,
            *silver_status.missing_file_paths,
        ),
        summary={
            "raw": dict(raw_status.summary),
            "silver": dict(silver_status.summary),
        },
    )


def _batch_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    layer: str,
    full_semantics: bool,
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = _normalize_trade_dates(expected_trade_dates)
    registered_trade_day_set = set(_normalize_trade_dates(registered_trade_days))
    path_plans = _adj_factor_path_plans(
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
    )
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root)
    raw_existing_paths = tuple(path_plan.raw_path for path_plan in path_plans if path_plan.raw_path.exists())
    silver_existing_paths = tuple(
        path_plan.silver_path for path_plan in path_plans if path_plan.silver_path.exists()
    )

    raw_schema_valid_paths: set[Path] = set()
    raw_required_column_valid_paths: set[Path] = set()
    silver_schema_valid_paths: set[Path] = set()
    silver_required_column_valid_paths: set[Path] = set()
    if full_semantics:
        for path in raw_existing_paths:
            if _schema_matches_contract(connection, path, ADJ_FACTOR_RAW_COLUMN_TYPES):
                raw_schema_valid_paths.add(path)
            if _has_required_columns(connection, path, ADJ_FACTOR_RAW_REQUIRED_COLUMNS):
                raw_required_column_valid_paths.add(path)
        for path in silver_existing_paths:
            if _schema_matches_contract(connection, path, ADJ_FACTOR_SILVER_COLUMN_TYPES):
                silver_schema_valid_paths.add(path)
            if _has_required_columns(connection, path, ADJ_FACTOR_SILVER_REQUIRED_COLUMNS):
                silver_required_column_valid_paths.add(path)
    else:
        raw_schema_valid_paths = set(raw_existing_paths)
        raw_required_column_valid_paths = set(raw_existing_paths)
        silver_schema_valid_paths = set(silver_existing_paths)
        silver_required_column_valid_paths = set(silver_existing_paths)

    metrics_by_trade_date = _metrics_by_trade_date(
        connection,
        path_plans=path_plans,
        stock_lifecycle_path=stock_lifecycle_path,
        layer=layer,
    )
    raw_statuses = {
        path_plan.trade_date: _raw_status_for_trade_date(
            trade_date=path_plan.trade_date,
            path_plan=path_plan,
            registered_trade_day_set=registered_trade_day_set,
            raw_schema_valid_paths=raw_schema_valid_paths,
            raw_required_column_valid_paths=raw_required_column_valid_paths,
            metrics=metrics_by_trade_date.get(path_plan.trade_date, _AdjFactorPathMetrics()),
            full_semantics=full_semantics,
        )
        for path_plan in path_plans
    }
    silver_statuses = {
        path_plan.trade_date: _silver_status_for_trade_date(
            trade_date=path_plan.trade_date,
            path_plan=path_plan,
            registered_trade_day_set=registered_trade_day_set,
            stock_lifecycle_path=stock_lifecycle_path,
            silver_schema_valid_paths=silver_schema_valid_paths,
            silver_required_column_valid_paths=silver_required_column_valid_paths,
            metrics=metrics_by_trade_date.get(path_plan.trade_date, _AdjFactorPathMetrics()),
            full_semantics=full_semantics,
        )
        for path_plan in path_plans
    }
    if layer == "raw":
        statuses_by_trade_date = raw_statuses
    elif layer == "silver":
        statuses_by_trade_date = silver_statuses
    elif layer == "combined":
        statuses_by_trade_date = {
            trade_date: _combined_status_for_trade_date(
                trade_date=trade_date,
                raw_status=raw_statuses[trade_date],
                silver_status=silver_statuses[trade_date],
            )
            for trade_date in expected_trade_dates
        }
    else:
        raise ValueError(f"Unsupported adj factor readiness layer: {layer!r}")

    elapsed_ms = round((perf_counter() - started_at) * 1000)
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses_by_trade_date,
        elapsed_ms=elapsed_ms,
        scanned_file_count=len(raw_existing_paths) + len(silver_existing_paths),
    )


def batch_raw_adj_factor_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    full_semantics: bool = True,
) -> ContinuityBatchReadiness:
    return _batch_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        layer="raw",
        full_semantics=full_semantics,
    )


def batch_silver_adj_factor_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    full_semantics: bool = True,
) -> ContinuityBatchReadiness:
    return _batch_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        layer="silver",
        full_semantics=full_semantics,
    )


def batch_adj_factor_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    full_semantics: bool = True,
) -> ContinuityBatchReadiness:
    return _batch_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        layer="combined",
        full_semantics=full_semantics,
    )
