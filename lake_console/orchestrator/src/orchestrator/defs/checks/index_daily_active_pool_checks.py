from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_daily_active_pool import (
    INDEX_DAILY_ACTIVE_POOL_COLUMNS,
    silver_index_daily_active_pool,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import silver_index_daily_active_pool_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return [row[0] for row in rows]


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata={
            "path": str(path),
            "missing_file": True,
        },
    )


@dg.asset_check(asset=silver_index_daily_active_pool, blocking=True)
def silver_index_daily_active_pool_file_exists(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    path = silver_index_daily_active_pool_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata={
            "path": str(path),
            "exists": path.exists(),
        },
    )


@dg.asset_check(asset=silver_index_daily_active_pool, blocking=True)
def silver_index_daily_active_pool_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_daily_active_pool_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, path)

    missing_columns = [column for column in INDEX_DAILY_ACTIVE_POOL_COLUMNS if column not in columns]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata={
            "path": str(path),
            "columns": columns,
            "required_columns": list(INDEX_DAILY_ACTIVE_POOL_COLUMNS),
            "missing_columns": missing_columns,
        },
    )


@dg.asset_check(asset=silver_index_daily_active_pool, blocking=True)
def silver_index_daily_active_pool_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_daily_active_pool_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row_count = int(
            connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata={
            "path": str(path),
            "row_count": row_count,
        },
    )


@dg.asset_check(asset=silver_index_daily_active_pool, blocking=True)
def silver_index_daily_active_pool_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_daily_active_pool_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    GROUP BY ts_code
    HAVING count(*) > 1
    """
    with duckdb.connect() as connection:
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
        metadata={
            "path": str(path),
            "duplicate_key_count": duplicate_key_count,
            "duplicate_sample_keys": _sample_dicts(["ts_code", "row_count"], rows),
        },
    )
