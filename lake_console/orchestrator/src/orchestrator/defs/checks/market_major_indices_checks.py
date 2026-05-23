from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.market_major_indices import (
    MARKET_MAJOR_INDICES_COLUMNS,
    gold_market_major_indices,
)
from orchestrator.defs.assets.index_basic import silver_index_basic
from orchestrator.defs.assets.index_daily_active_pool import silver_index_daily_active_pool
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_market_major_indices_path,
    silver_index_basic_path,
    silver_index_daily_active_pool_path,
)
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


@dg.asset_check(asset=gold_market_major_indices, blocking=True)
def gold_market_major_indices_file_exists(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    path = gold_market_major_indices_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata={
            "path": str(path),
            "exists": path.exists(),
        },
    )


@dg.asset_check(asset=gold_market_major_indices, blocking=True)
def gold_market_major_indices_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = gold_market_major_indices_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, path)

    missing_columns = [column for column in MARKET_MAJOR_INDICES_COLUMNS if column not in columns]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata={
            "path": str(path),
            "columns": columns,
            "required_columns": list(MARKET_MAJOR_INDICES_COLUMNS),
            "missing_columns": missing_columns,
        },
    )


@dg.asset_check(asset=gold_market_major_indices, blocking=True)
def gold_market_major_indices_has_ten_items(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = gold_market_major_indices_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row_count = int(
            connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count == 10,
        metadata={
            "path": str(path),
            "row_count": row_count,
            "expected_row_count": 10,
        },
    )


@dg.asset_check(asset=gold_market_major_indices, blocking=True)
def gold_market_major_indices_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = gold_market_major_indices_path(lake_root.root())
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


@dg.asset_check(asset=gold_market_major_indices, blocking=True)
def gold_market_major_indices_rank_continuous(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = gold_market_major_indices_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row = connection.execute(
            f"""
            SELECT
              count(*) AS row_count,
              count(DISTINCT "rank") AS distinct_rank_count,
              min("rank") AS min_rank,
              max("rank") AS max_rank,
              count(*) FILTER (WHERE "rank" IS NULL) AS null_rank_count
            FROM {read_parquet(path, hive_partitioning=False)}
            """
        ).fetchone()
        duplicate_rows = connection.execute(
            f"""
            SELECT "rank", count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY "rank"
            HAVING count(*) > 1
            ORDER BY "rank"
            LIMIT 10
            """
        ).fetchall()

    row_count = int(row[0])
    distinct_rank_count = int(row[1])
    min_rank = row[2]
    max_rank = row[3]
    null_rank_count = int(row[4])
    rank_continuous = (
        row_count > 0
        and null_rank_count == 0
        and distinct_rank_count == row_count
        and min_rank == 1
        and max_rank == row_count
    )
    return dg.AssetCheckResult(
        passed=rank_continuous,
        metadata={
            "path": str(path),
            "row_count": row_count,
            "distinct_rank_count": distinct_rank_count,
            "min_rank": min_rank,
            "max_rank": max_rank,
            "null_rank_count": null_rank_count,
            "duplicate_rank_samples": _sample_dicts(["rank", "row_count"], duplicate_rows),
        },
    )


@dg.asset_check(
    asset=gold_market_major_indices,
    additional_deps=[silver_index_daily_active_pool],
    blocking=True,
)
def gold_market_major_indices_codes_exist_in_active_pool(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    major_indices_path = gold_market_major_indices_path(lake_root.root())
    active_pool_path = silver_index_daily_active_pool_path(lake_root.root())
    for path in (major_indices_path, active_pool_path):
        if not path.exists():
            return _missing_file_result(path)

    missing_codes_sql = f"""
    SELECT major_indices.ts_code, major_indices."rank"
    FROM {read_parquet(major_indices_path, hive_partitioning=False)} major_indices
    LEFT JOIN {read_parquet(active_pool_path, hive_partitioning=False)} active_pool
      ON major_indices.ts_code = active_pool.ts_code
    WHERE active_pool.ts_code IS NULL
    """
    with duckdb.connect() as connection:
        missing_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({missing_codes_sql}) missing_codes"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {missing_codes_sql}
            ORDER BY "rank", ts_code
            LIMIT 20
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata={
            "major_indices_path": str(major_indices_path),
            "active_pool_path": str(active_pool_path),
            "missing_count": missing_count,
            "missing_sample_rows": _sample_dicts(["ts_code", "rank"], rows),
        },
    )


@dg.asset_check(
    asset=gold_market_major_indices,
    additional_deps=[silver_index_basic],
    blocking=True,
)
def gold_market_major_indices_codes_exist_in_index_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    major_indices_path = gold_market_major_indices_path(lake_root.root())
    index_basic_path = silver_index_basic_path(lake_root.root())
    for path in (major_indices_path, index_basic_path):
        if not path.exists():
            return _missing_file_result(path)

    missing_codes_sql = f"""
    SELECT major_indices.ts_code, major_indices."rank"
    FROM {read_parquet(major_indices_path, hive_partitioning=False)} major_indices
    LEFT JOIN {read_parquet(index_basic_path, hive_partitioning=False)} index_basic
      ON major_indices.ts_code = index_basic.ts_code
    WHERE index_basic.ts_code IS NULL
    """
    with duckdb.connect() as connection:
        missing_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({missing_codes_sql}) missing_codes"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {missing_codes_sql}
            ORDER BY "rank", ts_code
            LIMIT 20
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata={
            "major_indices_path": str(major_indices_path),
            "index_basic_path": str(index_basic_path),
            "missing_count": missing_count,
            "missing_sample_rows": _sample_dicts(["ts_code", "rank"], rows),
        },
    )
