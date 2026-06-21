import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    market_breadth_daily_select,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_market_breadth_daily_path,
    lake_path_template,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_BREADTH_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


MARKET_BREADTH_DAILY_COLUMNS = tuple(
    column.name for column in GOLD_MARKET_BREADTH_DAILY_SCHEMA
)


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _breadth_row(connection, path: Path) -> dict[str, int | float | str]:
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
        """
    ).fetchone()
    if row is None:
        return {}
    trade_date, up_count, down_count, flat_count, total_count, red_rate = row
    return {
        "trade_date": trade_date.isoformat()
        if hasattr(trade_date, "isoformat")
        else trade_date,
        "up_count": int(up_count),
        "down_count": int(down_count),
        "flat_count": int(flat_count),
        "total_count": int(total_count),
        "red_rate": float(red_rate),
    }


@dg.asset(
    name="gold_market_breadth_daily",
    deps=["silver_stock_daily"],
    partitions_def=cn_a_stock_trade_days,
    group_name="breadth",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.DERIVED_METRIC),
    metadata=build_asset_definition_metadata(
        dataset_id="market_breadth",
        source_system=SourceSystem.DERIVED,
        data_contract="market_breadth_daily",
        path_template=lake_path_template(
            gold_market_breadth_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        column_schema=GOLD_MARKET_BREADTH_DAILY_SCHEMA,
        extra_metadata={
            "calculation_contract": (
                "pct_chg completeness is guaranteed by silver_stock_daily blocking checks; "
                "up/down/flat by pct_chg > 0/< 0/= 0; "
                "red_rate = round(up_count / total_count * 100, 2)."
            )
        },
    ),
    description="市场涨跌分布日表，统计上涨、下跌和平盘数量。",
)
def gold_market_breadth_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    target_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not silver_path.exists():
        raise FileNotFoundError(f"Missing silver stock daily file: {silver_path}")

    with connect_configured_duckdb() as connection:
        _replace_parquet_from_query(
            connection,
            market_breadth_daily_select(silver_path, partition_key),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        breadth_row = _breadth_row(connection, target_path)

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "silver_file_path": str(silver_path),
                "partition_key": partition_key,
                "breadth_row": breadth_row,
            },
        )
    )
