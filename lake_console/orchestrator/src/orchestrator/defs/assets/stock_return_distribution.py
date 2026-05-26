import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    stock_return_distribution_select,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_stock_return_distribution_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


STOCK_RETURN_DISTRIBUTION_COLUMNS = (
    "trade_date",
    "down_gt_7_count",
    "down_5_7_count",
    "down_3_5_count",
    "down_0_3_count",
    "flat_count",
    "up_0_3_count",
    "up_3_5_count",
    "up_5_7_count",
    "up_gt_7_count",
    "total_count",
)


STOCK_RETURN_DISTRIBUTION_AUTOMATION_CONDITION = (
    dg.AutomationCondition.eager()
    & dg.AutomationCondition.all_deps_blocking_checks_passed()
)


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=hive_partitioning)).fetchone()[
            0
        ]
    )


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _distribution_row(connection, path: Path) -> dict[str, Any]:
    row = connection.execute(
        f"""
        SELECT
          trade_date,
          down_gt_7_count,
          down_5_7_count,
          down_3_5_count,
          down_0_3_count,
          flat_count,
          up_0_3_count,
          up_3_5_count,
          up_5_7_count,
          up_gt_7_count,
          total_count
        FROM {read_parquet(path, hive_partitioning=False)}
        """
    ).fetchone()
    if row is None:
        return {}

    result: dict[str, Any] = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
    }
    for column, value in zip(STOCK_RETURN_DISTRIBUTION_COLUMNS[1:], row[1:], strict=True):
        result[column] = int(value)
    return result


@dg.asset(
    name="gold_stock_return_distribution",
    deps=["silver_stock_daily"],
    partitions_def=cn_a_stock_trade_days,
    group_name="breadth",
    description="股票涨跌幅区间分布日表，按 pct_chg 统计九段收益率区间数量。",
    automation_condition=STOCK_RETURN_DISTRIBUTION_AUTOMATION_CONDITION,
)
def gold_stock_return_distribution(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    target_path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not silver_path.exists():
        raise FileNotFoundError(f"Missing silver stock daily file: {silver_path}")

    with duckdb.connect() as connection:
        _replace_parquet_from_query(
            connection,
            stock_return_distribution_select(silver_path, partition_key),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        distribution_row = _distribution_row(connection, target_path)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "silver_path": str(silver_path),
            "row_count": row_count,
            "columns": columns,
            "partition_key": partition_key,
            "layer": "gold",
            "data_contract": "stock_return_distribution",
            "calculation_contract": (
                "pct_chg completeness is guaranteed by silver_stock_daily blocking checks; "
                "gold aggregation does not filter pct_chg nulls; "
                "nine return buckets must add up to total_count."
            ),
            "distribution_row": distribution_row,
        }
    )
