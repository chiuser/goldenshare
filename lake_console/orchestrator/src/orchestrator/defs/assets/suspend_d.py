import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap import bootstrap_partition_to_raw
from orchestrator.defs.bootstrap.specs.suspend_d import suspend_d_bootstrap_spec
from orchestrator.defs.duckdb_sql import (
    SUSPEND_D_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    silver_stock_suspend_daily_select,
)
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import raw_suspend_d_path, silver_stock_suspend_daily_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


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


@dg.asset(
    name="raw_tushare_suspend_d",
    partitions_def=cn_a_trade_days,
    group_name="quote",
    description="Tushare suspend_d raw partition written to the new raw lake path.",
)
def raw_tushare_suspend_d(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    spec = suspend_d_bootstrap_spec(lake_root.root())
    metadata = bootstrap_partition_to_raw(spec, partition_key, duckdb)

    return dg.MaterializeResult(
        metadata={
            **metadata,
            "layer": "raw",
            "source_api": "suspend_d",
            "data_contract": "source_mirror",
            "raw_contract": (
                "Tushare suspend_d source mirror: trade_date YYYYMMDD string, "
                "suspend_timing nullable string."
            ),
            "required_columns": list(SUSPEND_D_RAW_REQUIRED_COLUMNS),
            "cast_summary": "trade_date DATE -> YYYYMMDD string; suspend_timing -> nullable string.",
        }
    )


@dg.asset(
    name="silver_stock_suspend_daily",
    deps=[raw_tushare_suspend_d],
    partitions_def=cn_a_trade_days,
    group_name="quote",
    description="Standardized stock daily suspend facts derived from Tushare suspend_d raw data.",
)
def silver_stock_suspend_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    raw_path = raw_suspend_d_path(lake_root.root(), partition_key)
    target_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw suspend_d file: {raw_path}")

    with duckdb.connect() as connection:
        _replace_parquet_from_query(
            connection,
            silver_stock_suspend_daily_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "raw_path": str(raw_path),
            "row_count": row_count,
            "columns": columns,
            "partition_key": partition_key,
            "layer": "silver",
            "data_contract": "standardized_stock_suspend_daily",
        }
    )
