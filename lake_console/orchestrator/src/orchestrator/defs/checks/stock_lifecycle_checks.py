from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    CNY_STOCK_CURR_TYPE,
    STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import silver_stock_lifecycle_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_LIFECYCLE_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _column_types(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={"missing_file": True},
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_file_exists_check(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    path = silver_stock_lifecycle_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={"exists": path.exists()},
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_required_columns_and_types_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duckdb_resource = duckdb
    path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    expected_types = {column.name: column.type for column in SILVER_STOCK_LIFECYCLE_SCHEMA}
    with duckdb_resource.connect() as connection:
        observed_types = _column_types(connection, path)

    missing_columns = [
        column for column in STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS if column not in observed_types
    ]
    type_mismatches = {
        column: {
            "expected": expected_types[column],
            "observed": observed_types[column],
        }
        for column in STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS
        if column in observed_types and observed_types[column] != expected_types[column]
    }

    return dg.AssetCheckResult(
        passed=not missing_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            extra_metadata={
                "observed_columns": list(observed_types),
                "required_columns": list(STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_unique_ts_code_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duckdb_resource = duckdb
    path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    GROUP BY ts_code
    HAVING count(*) > 1
    """
    with duckdb_resource.connect() as connection:
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=path,
            failed_row_count=duplicate_key_count,
            extra_metadata={
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_keys": _sample_dicts(["ts_code", "row_count"], rows),
            },
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_required_fields_non_null_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duckdb_resource = duckdb
    path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    required_non_null_columns = (
        "ts_code",
        "symbol",
        "name",
        "exchange",
        "curr_type",
        "is_cny_stock",
        "list_status",
        "list_date",
    )
    null_condition = " OR ".join(
        (
            f"{column} IS NULL"
            if column == "is_cny_stock"
            else f"{column} IS NULL OR trim(CAST({column} AS VARCHAR)) = ''"
        )
        for column in required_non_null_columns
    )
    with duckdb_resource.connect() as connection:
        null_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS null_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE {null_condition}
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, symbol, name, exchange, market, curr_type, list_status, list_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {null_condition}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            file_path=path,
            failed_row_count=null_count,
            extra_metadata={
                "required_non_null_columns": list(required_non_null_columns),
                "null_row_count": null_count,
                "null_sample_rows": _sample_dicts(
                    [
                        "ts_code",
                        "symbol",
                        "name",
                        "exchange",
                        "market",
                        "curr_type",
                        "list_status",
                        "list_date",
                    ],
                    rows,
                ),
            },
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_dates_valid_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duckdb_resource = duckdb
    path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb_resource.connect() as connection:
        invalid_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS invalid_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE list_date IS NULL
                   OR (
                     delist_date IS NOT NULL
                     AND delist_date < list_date
                   )
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, list_status, list_date, delist_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_date IS NULL
               OR (
                 delist_date IS NOT NULL
                 AND delist_date < list_date
               )
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            file_path=path,
            failed_row_count=invalid_count,
            extra_metadata={
                "invalid_lifecycle_date_count": invalid_count,
                "invalid_lifecycle_date_sample_rows": _sample_dicts(
                    ["ts_code", "list_status", "list_date", "delist_date"],
                    rows,
                ),
            },
        ),
    )


@dg.asset_check(asset="silver_stock_lifecycle", blocking=True)
def silver_stock_lifecycle_cny_stock_universe_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duckdb_resource = duckdb
    path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    required_curr_type = duckdb_string(CNY_STOCK_CURR_TYPE)
    with duckdb_resource.connect() as connection:
        non_cny_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS non_cny_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE curr_type IS NULL
                   OR curr_type != {required_curr_type}
                   OR is_cny_stock IS DISTINCT FROM true
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, curr_type, is_cny_stock, list_status
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE curr_type IS NULL
               OR curr_type != {required_curr_type}
               OR is_cny_stock IS DISTINCT FROM true
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=non_cny_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            file_path=path,
            failed_row_count=non_cny_count,
            extra_metadata={
                "required_curr_type_values": [CNY_STOCK_CURR_TYPE],
                "non_cny_row_count": non_cny_count,
                "non_cny_sample_rows": _sample_dicts(
                    ["ts_code", "name", "curr_type", "is_cny_stock", "list_status"],
                    rows,
                ),
            },
        ),
    )
