from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_return_distribution import (
    STOCK_RETURN_DISTRIBUTION_COLUMNS,
    gold_stock_return_distribution,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    read_parquet,
    stock_return_distribution_select,
)
from orchestrator.defs.paths import (
    gold_stock_return_distribution_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


RETURN_BUCKET_COLUMNS = (
    "down_gt_7_count",
    "down_5_7_count",
    "down_3_5_count",
    "down_0_3_count",
    "flat_count",
    "up_0_3_count",
    "up_3_5_count",
    "up_5_7_count",
    "up_gt_7_count",
)


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
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
        metadata={
            "path": str(path),
            "missing_file": True,
        },
    )


def _distribution_row(connection, path: Path) -> dict[str, Any] | None:
    row = connection.execute(
        f"""
        SELECT {", ".join(STOCK_RETURN_DISTRIBUTION_COLUMNS)}
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    result = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
    }
    for column, value in zip(STOCK_RETURN_DISTRIBUTION_COLUMNS[1:], row[1:], strict=True):
        result[column] = int(value)
    return result


def _recomputed_row(connection, silver_path: Path, partition_key: str) -> dict[str, Any] | None:
    row = connection.execute(stock_return_distribution_select(silver_path, partition_key)).fetchone()
    if row is None:
        return None
    result = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
    }
    for column, value in zip(STOCK_RETURN_DISTRIBUTION_COLUMNS[1:], row[1:], strict=True):
        result[column] = int(value)
    return result


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count == 1,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "row_count": int(row_count),
        },
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_counts_add_up(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    bucket_sum_expression = " + ".join(RETURN_BUCKET_COLUMNS)
    with duckdb.connect() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {bucket_sum_expression} != total_count
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT {", ".join(STOCK_RETURN_DISTRIBUTION_COLUMNS)}
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {bucket_sum_expression} != total_count
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "mismatch_count": int(mismatch_count),
            "mismatch_sample_rows": _sample_dicts(STOCK_RETURN_DISTRIBUTION_COLUMNS, rows),
        },
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_total_count_matches_silver(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with duckdb.connect() as connection:
        gold_total_count = connection.execute(
            f"""
            SELECT total_count
            FROM {read_parquet(gold_path, hive_partitioning=False)}
            LIMIT 1
            """
        ).fetchone()[0]
        silver_row_count = connection.execute(
            count_parquet_query(silver_path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=int(gold_total_count) == int(silver_row_count),
        metadata={
            "gold_path": str(gold_path),
            "silver_path": str(silver_path),
            "partition_key": partition_key,
            "gold_total_count": int(gold_total_count),
            "silver_row_count": int(silver_row_count),
        },
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL
               OR CAST(trade_date AS DATE) != DATE '{partition_key}'
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=not rows,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "invalid_row_count": len(rows),
            "invalid_sample_rows": _sample_dicts(["trade_date"], rows),
        },
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_recomputed_from_silver(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with duckdb.connect() as connection:
        gold_row = _distribution_row(connection, gold_path)
        recomputed_row = _recomputed_row(connection, silver_path, partition_key)

    return dg.AssetCheckResult(
        passed=gold_row == recomputed_row,
        metadata={
            "gold_path": str(gold_path),
            "silver_path": str(silver_path),
            "partition_key": partition_key,
            "gold_row": gold_row,
            "recomputed_row": recomputed_row,
        },
    )
