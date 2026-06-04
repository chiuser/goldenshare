from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.suspend_d import (
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
from orchestrator.defs.duckdb_sql import (
    SUSPEND_D_KNOWN_TYPE_VALUES,
    SUSPEND_D_RAW_REQUIRED_COLUMNS,
    SUSPEND_D_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import raw_suspend_d_path, silver_stock_suspend_daily_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


RAW_SUSPEND_D_EXPECTED_SCHEMA = {
    "ts_code": "VARCHAR",
    "trade_date": "VARCHAR",
    "suspend_timing": "VARCHAR",
    "suspend_type": "VARCHAR",
}


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
            extra_metadata={
                "file_path": str(path),
                "missing_file": True,
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_suspend_d,
    blocking=True,
)
def raw_suspend_d_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_suspend_d_path(lake_root.root(), partition_key)
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "exists": path.exists(),
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_suspend_d,
    blocking=True,
)
def raw_suspend_d_required_columns(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_suspend_d_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)

    missing_columns = [
        column for column in SUSPEND_D_RAW_REQUIRED_COLUMNS if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "observed_columns": columns,
                "required_columns": list(SUSPEND_D_RAW_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_suspend_d,
    blocking=True,
)
def raw_suspend_d_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_suspend_d_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE CAST(try_strptime(trade_date, '%Y%m%d') AS DATE) != DATE '{partition_key}'
               OR try_strptime(trade_date, '%Y%m%d') IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, suspend_type, suspend_timing
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE CAST(try_strptime(trade_date, '%Y%m%d') AS DATE) != DATE '{partition_key}'
               OR try_strptime(trade_date, '%Y%m%d') IS NULL
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "mismatch_count": int(mismatch_count),
                "mismatch_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "suspend_type", "suspend_timing"], rows
                ),
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_suspend_d,
    blocking=True,
)
def raw_suspend_d_schema_matches_tushare_contract(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_suspend_d_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        schema = dict(_describe_columns(connection, path))
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    missing_columns = [
        column for column in SUSPEND_D_RAW_REQUIRED_COLUMNS if column not in schema
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": schema.get(column),
        }
        for column, expected_type in RAW_SUSPEND_D_EXPECTED_SCHEMA.items()
        if schema.get(column) != expected_type
    }
    return dg.AssetCheckResult(
        passed=not missing_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "checked_row_count": int(row_count),
                "observed_schema": schema,
                "expected_schema": RAW_SUSPEND_D_EXPECTED_SCHEMA,
                "missing_columns": missing_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


@dg.asset_check(
    asset=silver_stock_suspend_daily,
    blocking=True,
)
def silver_suspend_d_known_type_values(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)
        missing_columns = [
            column
            for column in SUSPEND_D_SILVER_REQUIRED_COLUMNS
            if column not in columns
        ]
        if missing_columns:
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.SCHEMA,
                    extra_metadata={
                        "file_path": str(path),
                        "partition_key": partition_key,
                        "observed_columns": columns,
                        "required_columns": list(SUSPEND_D_SILVER_REQUIRED_COLUMNS),
                        "missing_columns": missing_columns,
                    },
                ),
            )

        invalid_count = connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE suspend_type IS NULL
               OR suspend_type NOT IN ('S', 'R')
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, suspend_type, suspend_timing
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE suspend_type IS NULL
               OR suspend_type NOT IN ('S', 'R')
            LIMIT 10
            """
        ).fetchall()
        distribution_rows = connection.execute(
            f"""
            SELECT suspend_type, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY suspend_type
            ORDER BY suspend_type
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "known_values": list(SUSPEND_D_KNOWN_TYPE_VALUES),
                "invalid_count": int(invalid_count),
                "invalid_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "suspend_type", "suspend_timing"], rows
                ),
                "suspend_type_distribution": _sample_dicts(
                    ["suspend_type", "row_count"], distribution_rows
                ),
            },
        ),
    )


@dg.asset_check(
    asset=silver_stock_suspend_daily,
    blocking=True,
)
def silver_suspend_d_unique_business_key(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT
      ts_code,
      trade_date,
      suspend_type,
      COALESCE(suspend_timing, '') AS suspend_timing_key,
      count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    GROUP BY ts_code, trade_date, suspend_type, COALESCE(suspend_timing, '')
    HAVING count(*) > 1
    """
    with connect_configured_duckdb() as connection:
        duplicate_key_count = connection.execute(
            f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code, trade_date, suspend_type, suspend_timing_key
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "business_key": [
                    "ts_code",
                    "trade_date",
                    "suspend_type",
                    "coalesce(suspend_timing, '')",
                ],
                "duplicate_key_count": int(duplicate_key_count),
                "duplicate_sample_keys": _sample_dicts(
                    [
                        "ts_code",
                        "trade_date",
                        "suspend_type",
                        "suspend_timing_key",
                        "row_count",
                    ],
                    rows,
                ),
            },
        ),
    )
