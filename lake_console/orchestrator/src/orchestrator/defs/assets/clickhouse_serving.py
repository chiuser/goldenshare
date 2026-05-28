from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.assets.stock_return_distribution import (
    gold_stock_return_distribution,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    gold_stock_return_distribution_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
CLICKHOUSE_MARKET_BREADTH_TABLE = "goldenshare_serving.share_fact_market_breadth_daily"
CLICKHOUSE_MARKET_BREADTH_COLUMNS = (
    "trade_date",
    "up_count",
    "down_count",
    "flat_count",
    "total_count",
    "red_rate",
    "down_gt_7_count",
    "down_5_7_count",
    "down_3_5_count",
    "down_0_3_count",
    "up_0_3_count",
    "up_3_5_count",
    "up_5_7_count",
    "up_gt_7_count",
    "updated_at",
)

CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION = (
    dg.AutomationCondition.eager()
    & dg.AutomationCondition.all_deps_blocking_checks_passed()
)


def _read_single_row(
    connection,
    path: Path,
    *,
    columns: tuple[str, ...],
    dataset_name: str,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {dataset_name} parquet: {path}")

    select_columns = ", ".join(columns)
    rows = connection.execute(
        f"SELECT {select_columns} FROM {read_parquet(path, hive_partitioning=False)}"
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(
            f"{dataset_name} must contain exactly 1 row, got {len(rows)}: {path}"
        )
    return dict(zip(columns, rows[0], strict=True))


def _date_iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _int_value(row: dict[str, Any], column: str) -> int:
    return int(row[column])


def _float_value(row: dict[str, Any], column: str) -> float:
    return float(row[column])


def _build_clickhouse_row(
    *,
    partition_key: str,
    breadth_row: dict[str, Any],
    distribution_row: dict[str, Any],
) -> tuple[Any, ...]:
    breadth_date = _date_iso(breadth_row["trade_date"])
    distribution_date = _date_iso(distribution_row["trade_date"])
    if breadth_date != partition_key:
        raise ValueError(
            f"gold_market_breadth_daily trade_date {breadth_date} "
            f"does not match partition {partition_key}."
        )
    if distribution_date != partition_key:
        raise ValueError(
            f"gold_stock_return_distribution trade_date {distribution_date} "
            f"does not match partition {partition_key}."
        )

    if _int_value(breadth_row, "total_count") != _int_value(
        distribution_row, "total_count"
    ):
        raise ValueError(
            "Gold total_count mismatch between market breadth and return distribution."
        )
    if _int_value(breadth_row, "flat_count") != _int_value(
        distribution_row, "flat_count"
    ):
        raise ValueError(
            "Gold flat_count mismatch between market breadth and return distribution."
        )

    return (
        date.fromisoformat(partition_key),
        _int_value(breadth_row, "up_count"),
        _int_value(breadth_row, "down_count"),
        _int_value(breadth_row, "flat_count"),
        _int_value(breadth_row, "total_count"),
        _float_value(breadth_row, "red_rate"),
        _int_value(distribution_row, "down_gt_7_count"),
        _int_value(distribution_row, "down_5_7_count"),
        _int_value(distribution_row, "down_3_5_count"),
        _int_value(distribution_row, "down_0_3_count"),
        _int_value(distribution_row, "up_0_3_count"),
        _int_value(distribution_row, "up_3_5_count"),
        _int_value(distribution_row, "up_5_7_count"),
        _int_value(distribution_row, "up_gt_7_count"),
        datetime.now(CN_A_TIMEZONE).replace(tzinfo=None),
    )


def _count_clickhouse_partition(client, partition_date: date) -> int:
    rows = client.execute(
        f"""
        SELECT count()
        FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE trade_date = %(trade_date)s
        """,
        {"trade_date": partition_date},
    )
    return int(rows[0][0])


def _replace_clickhouse_partition(client, row: tuple[Any, ...]) -> None:
    partition_date = row[0]
    client.execute("SET lightweight_deletes_sync = 1")
    client.execute(
        f"""
        DELETE FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE trade_date = %(trade_date)s
        """,
        {"trade_date": partition_date},
    )
    deleted_row_count = _count_clickhouse_partition(client, partition_date)
    if deleted_row_count != 0:
        raise RuntimeError(
            "Synchronous ClickHouse delete did not make the target partition empty: "
            f"trade_date={partition_date.isoformat()}, remaining_rows={deleted_row_count}"
        )

    column_list = ", ".join(CLICKHOUSE_MARKET_BREADTH_COLUMNS)
    client.execute(
        f"INSERT INTO {CLICKHOUSE_MARKET_BREADTH_TABLE} ({column_list}) VALUES",
        [row],
    )
    inserted_row_count = _count_clickhouse_partition(client, partition_date)
    if inserted_row_count != 1:
        raise RuntimeError(
            "ClickHouse replace must leave exactly one row: "
            f"trade_date={partition_date.isoformat()}, row_count={inserted_row_count}"
        )


@dg.asset(
    name="ch_share_fact_market_breadth_daily",
    deps=[gold_market_breadth_daily, gold_stock_return_distribution],
    partitions_def=cn_a_stock_trade_days,
    group_name="serving",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="ch_share_fact_market_breadth_daily",
        source_system=SourceSystem.DERIVED,
        data_contract="share_fact_market_breadth_daily",
        extra_metadata={
            "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
            "replace_contract": "sync delete by trade_date, then insert exactly one row",
        },
    ),
    description="ClickHouse 行情事实市场宽度日表，由两个 gold 资产合并生成 serving 副本。",
    automation_condition=CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION,
)
def ch_share_fact_market_breadth_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    breadth_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    distribution_path = gold_stock_return_distribution_path(
        lake_root.root(),
        partition_key,
    )

    with duckdb.connect() as connection:
        breadth_row = _read_single_row(
            connection,
            breadth_path,
            columns=(
                "trade_date",
                "up_count",
                "down_count",
                "flat_count",
                "total_count",
                "red_rate",
            ),
            dataset_name="gold_market_breadth_daily",
        )
        distribution_row = _read_single_row(
            connection,
            distribution_path,
            columns=(
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
            ),
            dataset_name="gold_stock_return_distribution",
        )
    clickhouse_row = _build_clickhouse_row(
        partition_key=partition_key,
        breadth_row=breadth_row,
        distribution_row=distribution_row,
    )

    with clickhouse.get_connection() as client:
        _replace_clickhouse_partition(client, clickhouse_row)

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=(
                f"clickhouse://{CLICKHOUSE_MARKET_BREADTH_TABLE}"
                f"?trade_date={partition_key}"
            ),
            row_count=1,
            columns=CLICKHOUSE_MARKET_BREADTH_COLUMNS,
            extra_metadata={
                "partition_key": partition_key,
                "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
                "gold_market_breadth_daily_path": str(breadth_path),
                "gold_stock_return_distribution_path": str(distribution_path),
                "replace_mode": "sync_delete_then_insert",
                "lightweight_deletes_sync": 1,
            },
        )
    )
