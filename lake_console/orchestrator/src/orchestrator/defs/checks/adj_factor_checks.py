from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.adj_factor import (
    ADJ_FACTOR_RAW_COLUMN_TYPES,
    ADJ_FACTOR_SILVER_COLUMN_TYPES,
    raw_tushare_adj_factor,
    silver_adj_factor,
)
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
    silver_cny_stock_lifecycle_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
ADJ_FACTOR_MIN_TRADE_DATE = "2009-01-05"


def _describe_columns(connection, path: Path) -> list[tuple[str, str]]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _column_names(connection, path: Path) -> list[str]:
    return [name for name, _type_name in _describe_columns(connection, path)]


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={"missing_file": True},
        ),
    )


def _missing_input_file_result(paths: Sequence[Path]) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            missing_file_paths=paths,
            extra_metadata={"missing_input_file": True},
        ),
    )


def _schema_check_result(
    *,
    path: Path,
    partition_key: str,
    observed_schema: dict[str, str],
    expected_schema: dict[str, str],
    checked_row_count: int,
) -> dg.AssetCheckResult:
    missing_columns = [
        column for column in expected_schema if column not in observed_schema
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": observed_schema.get(column),
        }
        for column, expected_type in expected_schema.items()
        if observed_schema.get(column) != expected_type
    }
    return dg.AssetCheckResult(
        passed=not missing_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=checked_row_count,
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "observed_schema": observed_schema,
                "expected_schema": expected_schema,
                "missing_columns": missing_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


def _stock_current_partition_allowed_status(
    *,
    partition_key: str,
    registered_keys: set[str],
    today: str,
) -> dict[str, Any]:
    is_registered = partition_key in registered_keys
    is_not_before_start = partition_key >= ADJ_FACTOR_MIN_TRADE_DATE
    is_not_future = partition_key <= today
    return {
        "passed": is_registered and is_not_before_start and is_not_future,
        "partition_key": partition_key,
        "partition_set": cn_a_stock_current_trade_days.name,
        "is_registered": is_registered,
        "min_trade_date": ADJ_FACTOR_MIN_TRADE_DATE,
        "is_not_before_start": is_not_before_start,
        "today": today,
        "is_not_future": is_not_future,
    }


def _stock_current_partition_key_allowed_result(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    today = datetime.now(CN_A_TIMEZONE).date().isoformat()
    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
    )
    status = _stock_current_partition_allowed_status(
        partition_key=partition_key,
        registered_keys=registered_keys,
        today=today,
    )

    return dg.AssetCheckResult(
        passed=bool(status["passed"]),
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={key: value for key, value in status.items() if key != "passed"},
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "exists": path.exists(),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            checked_row_count=int(row_count),
            file_path=path,
            extra_metadata={"partition_key": partition_key},
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_schema_matches_tushare_contract(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        observed_schema = dict(_describe_columns(connection, path))
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return _schema_check_result(
        path=path,
        partition_key=partition_key,
        observed_schema=observed_schema,
        expected_schema=ADJ_FACTOR_RAW_COLUMN_TYPES,
        checked_row_count=int(row_count),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_required_columns(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)

    missing_columns = [
        column for column in ADJ_FACTOR_RAW_REQUIRED_COLUMNS if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "observed_columns": columns,
                "required_columns": list(ADJ_FACTOR_RAW_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    partition_date = f"DATE {duckdb_string(partition_key)}"
    trade_date_expression = (
        "CAST(try_strptime(trim(CAST(trade_date AS VARCHAR)), '%Y%m%d') AS DATE)"
    )
    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {trade_date_expression} IS NULL
               OR {trade_date_expression} != {partition_date}
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, adj_factor
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {trade_date_expression} IS NULL
               OR {trade_date_expression} != {partition_date}
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            failed_row_count=int(mismatch_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "mismatch_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "adj_factor"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        duplicate_count = connection.execute(
            f"""
            SELECT count(*) AS duplicate_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, count(*) AS duplicate_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            failed_row_count=int(duplicate_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "trade_date", "duplicate_count"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_positive_factor(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        invalid_count = connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, adj_factor
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=int(invalid_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "invalid_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "adj_factor"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_adj_factor, blocking=True)
def raw_adj_factor_stock_current_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_current_partition_key_allowed_result(context)


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "exists": path.exists(),
            },
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            checked_row_count=int(row_count),
            file_path=path,
            extra_metadata={"partition_key": partition_key},
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_schema_matches_contract(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        observed_schema = dict(_describe_columns(connection, path))
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return _schema_check_result(
        path=path,
        partition_key=partition_key,
        observed_schema=observed_schema,
        expected_schema=ADJ_FACTOR_SILVER_COLUMN_TYPES,
        checked_row_count=int(row_count),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_required_columns(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)

    missing_columns = [
        column for column in ADJ_FACTOR_SILVER_REQUIRED_COLUMNS if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "observed_columns": columns,
                "required_columns": list(ADJ_FACTOR_SILVER_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    partition_date = f"DATE {duckdb_string(partition_key)}"
    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL OR trade_date != {partition_date}
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, adj_factor
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL OR trade_date != {partition_date}
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            failed_row_count=int(mismatch_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "mismatch_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "adj_factor"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        duplicate_count = connection.execute(
            f"""
            SELECT count(*) AS duplicate_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, count(*) AS duplicate_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            failed_row_count=int(duplicate_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "trade_date", "duplicate_count"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_positive_factor(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        invalid_count = connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, adj_factor
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=int(invalid_count),
            file_path=path,
            extra_metadata={
                "partition_key": partition_key,
                "invalid_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "adj_factor"], rows
                ),
            },
        ),
    )


@dg.asset_check(
    asset=silver_adj_factor,
    additional_deps=[silver_stock_lifecycle],
    blocking=True,
)
def silver_adj_factor_listed_stock_only(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    if not lifecycle_path.exists():
        return _missing_input_file_result([lifecycle_path])

    stock_lifecycle_sql = silver_cny_stock_lifecycle_select(lifecycle_path)
    with connect_configured_duckdb() as connection:
        invalid_count = connection.execute(
            f"""
            WITH stock_lifecycle AS (
              {stock_lifecycle_sql}
            )
            SELECT count(*) AS invalid_count
            FROM {read_parquet(path, hive_partitioning=False)} adj
            LEFT JOIN stock_lifecycle
              ON adj.ts_code = stock_lifecycle.ts_code
            WHERE stock_lifecycle.ts_code IS NULL
               OR adj.trade_date < stock_lifecycle.list_date
               OR (
                 stock_lifecycle.delist_date IS NOT NULL
                 AND adj.trade_date > stock_lifecycle.delist_date
               )
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            WITH stock_lifecycle AS (
              {stock_lifecycle_sql}
            )
            SELECT
              adj.ts_code,
              adj.trade_date,
              stock_lifecycle.list_date,
              stock_lifecycle.delist_date,
              adj.adj_factor
            FROM {read_parquet(path, hive_partitioning=False)} adj
            LEFT JOIN stock_lifecycle
              ON adj.ts_code = stock_lifecycle.ts_code
            WHERE stock_lifecycle.ts_code IS NULL
               OR adj.trade_date < stock_lifecycle.list_date
               OR (
                 stock_lifecycle.delist_date IS NOT NULL
                 AND adj.trade_date > stock_lifecycle.delist_date
               )
            ORDER BY adj.ts_code, adj.trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            failed_row_count=int(invalid_count),
            input_file_paths=[path, lifecycle_path],
            extra_metadata={
                "partition_key": partition_key,
                "lifecycle_fact_source": "silver_stock_lifecycle",
                "silver_stock_lifecycle_file_path": str(lifecycle_path),
                "invalid_sample_rows": _sample_dicts(
                    [
                        "ts_code",
                        "trade_date",
                        "list_date",
                        "delist_date",
                        "adj_factor",
                    ],
                    rows,
                ),
            },
        ),
    )


@dg.asset_check(
    asset=silver_adj_factor,
    additional_deps=[silver_stock_lifecycle],
    blocking=True,
)
def silver_adj_factor_coverage_complete(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_adj_factor_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    if not lifecycle_path.exists():
        return _missing_input_file_result([lifecycle_path])

    partition_date = f"DATE {duckdb_string(partition_key)}"
    stock_lifecycle_sql = silver_cny_stock_lifecycle_select(lifecycle_path)
    with connect_configured_duckdb() as connection:
        summary = connection.execute(
            f"""
            WITH expected AS (
              SELECT DISTINCT ts_code
              FROM ({stock_lifecycle_sql}) stock_lifecycle
              WHERE list_date <= {partition_date}
                AND (
                  delist_date IS NULL
                  OR delist_date >= {partition_date}
                )
            ),
            actual AS (
              SELECT DISTINCT ts_code
              FROM {read_parquet(path, hive_partitioning=False)}
              WHERE trade_date = {partition_date}
            ),
            missing AS (
              SELECT expected.ts_code
              FROM expected
              LEFT JOIN actual USING (ts_code)
              WHERE actual.ts_code IS NULL
            ),
            unexpected AS (
              SELECT actual.ts_code
              FROM actual
              LEFT JOIN expected USING (ts_code)
              WHERE expected.ts_code IS NULL
            )
            SELECT
              (SELECT count(*) FROM expected) AS expected_code_count,
              (SELECT count(*) FROM actual) AS actual_code_count,
              (SELECT count(*) FROM missing) AS missing_code_count,
              (SELECT count(*) FROM unexpected) AS unexpected_code_count
            """
        ).fetchone()
        missing_rows = connection.execute(
            f"""
            WITH expected AS (
              SELECT DISTINCT ts_code
              FROM ({stock_lifecycle_sql}) stock_lifecycle
              WHERE list_date <= {partition_date}
                AND (
                  delist_date IS NULL
                  OR delist_date >= {partition_date}
                )
            ),
            actual AS (
              SELECT DISTINCT ts_code
              FROM {read_parquet(path, hive_partitioning=False)}
              WHERE trade_date = {partition_date}
            )
            SELECT expected.ts_code
            FROM expected
            LEFT JOIN actual USING (ts_code)
            WHERE actual.ts_code IS NULL
            ORDER BY expected.ts_code
            LIMIT 10
            """
        ).fetchall()
        unexpected_rows = connection.execute(
            f"""
            WITH expected AS (
              SELECT DISTINCT ts_code
              FROM ({stock_lifecycle_sql}) stock_lifecycle
              WHERE list_date <= {partition_date}
                AND (
                  delist_date IS NULL
                  OR delist_date >= {partition_date}
                )
            ),
            actual AS (
              SELECT DISTINCT ts_code
              FROM {read_parquet(path, hive_partitioning=False)}
              WHERE trade_date = {partition_date}
            )
            SELECT actual.ts_code
            FROM actual
            LEFT JOIN expected USING (ts_code)
            WHERE expected.ts_code IS NULL
            ORDER BY actual.ts_code
            LIMIT 10
            """
        ).fetchall()

    missing_count = int(summary[2])
    unexpected_count = int(summary[3])
    return dg.AssetCheckResult(
        passed=missing_count == 0 and unexpected_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            failed_row_count=missing_count + unexpected_count,
            input_file_paths=[path, lifecycle_path],
            extra_metadata={
                "partition_key": partition_key,
                "lifecycle_fact_source": "silver_stock_lifecycle",
                "silver_stock_lifecycle_file_path": str(lifecycle_path),
                "expected_code_count": int(summary[0]),
                "actual_code_count": int(summary[1]),
                "missing_code_count": missing_count,
                "unexpected_code_count": unexpected_count,
                "missing_code_samples": [
                    row[0] for row in missing_rows
                ],
                "unexpected_code_samples": [
                    row[0] for row in unexpected_rows
                ],
            },
        ),
    )


@dg.asset_check(asset=silver_adj_factor, blocking=True)
def silver_adj_factor_stock_current_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_current_partition_key_allowed_result(context)
