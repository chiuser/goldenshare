from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    market_breadth_daily_select,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


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


def _gold_row(connection, path: Path) -> dict[str, Any] | None:
    row = connection.execute(
        f"""
        SELECT
          trade_date,
          up_count,
          down_count,
          flat_count,
          total_count,
          red_rate
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
        "up_count": int(row[1]),
        "down_count": int(row[2]),
        "flat_count": int(row[3]),
        "total_count": int(row[4]),
        "red_rate": float(row[5]),
    }


def _recomputed_row(connection, silver_path: Path, partition_key: str) -> dict[str, Any] | None:
    row = connection.execute(market_breadth_daily_select(silver_path, partition_key)).fetchone()
    if row is None:
        return None
    return {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
        "up_count": int(row[1]),
        "down_count": int(row[2]),
        "flat_count": int(row[3]),
        "total_count": int(row[4]),
        "red_rate": float(row[5]),
    }


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
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


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_counts_add_up(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE up_count + down_count + flat_count != total_count
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT trade_date, up_count, down_count, flat_count, total_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE up_count + down_count + flat_count != total_count
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "mismatch_count": int(mismatch_count),
            "mismatch_sample_rows": _sample_dicts(
                ["trade_date", "up_count", "down_count", "flat_count", "total_count"],
                rows,
            ),
        },
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_total_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date, total_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE total_count <= 0
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=not rows,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "invalid_row_count": len(rows),
            "invalid_sample_rows": _sample_dicts(["trade_date", "total_count"], rows),
        },
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_red_rate_range(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date, red_rate
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE red_rate < 0 OR red_rate > 100
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=not rows,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "invalid_row_count": len(rows),
            "invalid_sample_rows": _sample_dicts(["trade_date", "red_rate"], rows),
        },
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_red_rate_formula(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT
              trade_date,
              up_count,
              total_count,
              red_rate,
              CASE
                WHEN total_count = 0 THEN 0.0
                ELSE ROUND(up_count * 100.0 / total_count, 2)
              END AS expected_red_rate
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ABS(
              red_rate - CASE
                WHEN total_count = 0 THEN 0.0
                ELSE ROUND(up_count * 100.0 / total_count, 2)
              END
            ) > 0.000001
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=not rows,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "invalid_row_count": len(rows),
            "invalid_sample_rows": _sample_dicts(
                ["trade_date", "up_count", "total_count", "red_rate", "expected_red_rate"],
                rows,
            ),
        },
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_matches_silver_recompute(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with duckdb.connect() as connection:
        gold_row = _gold_row(connection, gold_path)
        recomputed_row = _recomputed_row(connection, silver_path, partition_key)

    passed = gold_row == recomputed_row
    return dg.AssetCheckResult(
        passed=passed,
        metadata={
            "gold_path": str(gold_path),
            "silver_path": str(silver_path),
            "partition_key": partition_key,
            "gold_row": gold_row or {},
            "recomputed_row": recomputed_row or {},
        },
    )
