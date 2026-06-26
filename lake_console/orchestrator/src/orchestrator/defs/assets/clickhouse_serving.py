from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
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
from orchestrator.defs.run_contracts.asset_column_schemas import (
    CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
CLICKHOUSE_MARKET_BREADTH_TABLE = "goldenshare_serving.share_fact_market_breadth_daily"
CLICKHOUSE_MARKET_BREADTH_COLUMNS = tuple(
    column.name for column in CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA
)
PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN = 1


def _serving_materialization_metadata(
    *,
    partition_key: str,
    target_system: str,
    source_summary: dict[str, object],
) -> dict[str, object]:
    return {
        "summary": f"已写入 {target_system} 市场宽度 serving 日事实。",
        "next_action": "等待对应 ClickHouse serving blocking checks 全部通过；通过后 serving 查询可以消费。",
        "result_status": "written",
        "input_summary": source_summary,
        "serving_summary": {
            "target_system": target_system,
            "target_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
            "partition_key": partition_key,
            "replace_mode": "sync_delete_then_insert",
            "row_count": 1,
        },
        "diagnostic_ref": "完整诊断看 ClickHouse serving checks、materialization metadata 和 run stdout。",
    }


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
        _int_value(distribution_row, "down_gt_10_count"),
        _int_value(distribution_row, "down_7_10_count"),
        _int_value(distribution_row, "down_5_7_count"),
        _int_value(distribution_row, "down_3_5_count"),
        _int_value(distribution_row, "down_0_3_count"),
        _int_value(distribution_row, "up_0_3_count"),
        _int_value(distribution_row, "up_3_5_count"),
        _int_value(distribution_row, "up_5_7_count"),
        _int_value(distribution_row, "up_7_10_count"),
        _int_value(distribution_row, "up_gt_10_count"),
        datetime.now(CN_A_TIMEZONE).replace(tzinfo=None),
    )


def _normalise_clickhouse_value(column: str, value: Any) -> Any:
    if column == "trade_date":
        return _date_iso(value)
    if column == "updated_at":
        if hasattr(value, "isoformat"):
            return value.isoformat(sep=" ")
        return str(value)
    if column == "red_rate":
        return float(value)
    return int(value)


def _clickhouse_row_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        column: _normalise_clickhouse_value(column, value)
        for column, value in zip(CLICKHOUSE_MARKET_BREADTH_COLUMNS, row, strict=True)
    }


def _selected_partition_keys(
    context: dg.AssetExecutionContext | dg.AssetCheckExecutionContext,
) -> tuple[str, ...]:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    if not partition_keys:
        raise RuntimeError("prod ClickHouse market breadth sync requires partitions.")
    if len(partition_keys) != PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN:
        raise RuntimeError(
            "prod ClickHouse market breadth sync requires exactly one partition: "
            f"partition_count={len(partition_keys)}, "
            f"required={PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN}"
        )
    return partition_keys


def _trade_date_filter_sql(
    partition_keys: tuple[str, ...],
) -> tuple[str, dict[str, date]]:
    if not partition_keys:
        raise RuntimeError("trade_date filter requires at least one partition key.")

    params: dict[str, date] = {}
    placeholders = []
    for index, partition_key in enumerate(partition_keys):
        param_name = f"trade_date_{index}"
        placeholders.append(f"%({param_name})s")
        params[param_name] = date.fromisoformat(partition_key)
    return f"trade_date IN ({', '.join(placeholders)})", params


def _group_clickhouse_row_tuples_by_partition(
    rows: list[tuple[Any, ...]],
    partition_keys: tuple[str, ...],
) -> dict[str, list[tuple[Any, ...]]]:
    rows_by_partition = {partition_key: [] for partition_key in partition_keys}
    for row in rows:
        partition_key = _date_iso(row[0])
        if partition_key in rows_by_partition:
            rows_by_partition[partition_key].append(tuple(row))
    return rows_by_partition


def _fetch_clickhouse_market_breadth_row_tuples_by_partition(
    client,
    partition_keys: tuple[str, ...],
) -> dict[str, list[tuple[Any, ...]]]:
    column_list = ", ".join(CLICKHOUSE_MARKET_BREADTH_COLUMNS)
    where_sql, params = _trade_date_filter_sql(partition_keys)
    rows = client.execute(
        f"""
        SELECT {column_list}
        FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE {where_sql}
        ORDER BY trade_date
        """,
        params,
    )
    return _group_clickhouse_row_tuples_by_partition(
        [tuple(row) for row in rows],
        partition_keys,
    )


def fetch_clickhouse_market_breadth_rows_for_partitions(
    client,
    partition_keys: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    rows_by_partition = _fetch_clickhouse_market_breadth_row_tuples_by_partition(
        client,
        partition_keys,
    )
    return {
        partition_key: [_clickhouse_row_dict(row) for row in rows]
        for partition_key, rows in rows_by_partition.items()
    }


def fetch_clickhouse_market_breadth_rows(
    client,
    partition_key: str,
) -> list[dict[str, Any]]:
    return fetch_clickhouse_market_breadth_rows_for_partitions(
        client,
        (partition_key,),
    )[partition_key]


def _require_single_clickhouse_rows(
    rows_by_partition: dict[str, list[tuple[Any, ...]]],
    partition_keys: tuple[str, ...],
    *,
    dataset_label: str,
) -> list[tuple[Any, ...]]:
    missing_partitions = [
        partition_key
        for partition_key in partition_keys
        if not rows_by_partition.get(partition_key)
    ]
    duplicate_partitions = [
        partition_key
        for partition_key in partition_keys
        if len(rows_by_partition.get(partition_key, [])) > 1
    ]
    if missing_partitions or duplicate_partitions:
        raise RuntimeError(
            f"{dataset_label} must contain exactly one row for each selected "
            "partition before syncing to prod: "
            f"missing_partitions={missing_partitions[:10]}, "
            f"duplicate_partitions={duplicate_partitions[:10]}"
        )
    return [rows_by_partition[partition_key][0] for partition_key in partition_keys]


def _fetch_single_clickhouse_market_breadth_row(
    client,
    partition_key: str,
) -> tuple[Any, ...]:
    rows = _require_single_clickhouse_rows(
        _fetch_clickhouse_market_breadth_row_tuples_by_partition(
            client,
            (partition_key,),
        ),
        (partition_key,),
        dataset_label="Local ClickHouse serving partition",
    )
    return rows[0]


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


def _count_clickhouse_partitions(
    client,
    partition_keys: tuple[str, ...],
) -> dict[str, int]:
    where_sql, params = _trade_date_filter_sql(partition_keys)
    rows = client.execute(
        f"""
        SELECT trade_date, count()
        FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE {where_sql}
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        params,
    )
    row_counts = {partition_key: 0 for partition_key in partition_keys}
    for trade_date, row_count in rows:
        partition_key = _date_iso(trade_date)
        if partition_key in row_counts:
            row_counts[partition_key] = int(row_count)
    return row_counts


def _assert_clickhouse_partition_row_counts(
    row_counts: dict[str, int],
    *,
    expected_row_count: int,
    failure_prefix: str,
) -> None:
    failed_partitions = {
        partition_key: row_count
        for partition_key, row_count in row_counts.items()
        if row_count != expected_row_count
    }
    if failed_partitions:
        raise RuntimeError(
            f"{failure_prefix}: "
            f"failed_partitions={dict(list(failed_partitions.items())[:10])}"
        )


def _replace_clickhouse_partitions(
    client,
    rows_by_partition: dict[str, list[tuple[Any, ...]]],
    partition_keys: tuple[str, ...],
) -> None:
    rows = _require_single_clickhouse_rows(
        rows_by_partition,
        partition_keys,
        dataset_label="Local ClickHouse serving partition",
    )
    client.execute("SET lightweight_deletes_sync = 1")
    where_sql, params = _trade_date_filter_sql(partition_keys)
    client.execute(
        f"""
        DELETE FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE {where_sql}
        """,
        params,
    )
    deleted_row_counts = _count_clickhouse_partitions(client, partition_keys)
    _assert_clickhouse_partition_row_counts(
        deleted_row_counts,
        expected_row_count=0,
        failure_prefix="Synchronous ClickHouse delete did not make target partitions empty",
    )

    column_list = ", ".join(CLICKHOUSE_MARKET_BREADTH_COLUMNS)
    client.execute(
        f"INSERT INTO {CLICKHOUSE_MARKET_BREADTH_TABLE} ({column_list}) VALUES",
        rows,
    )
    inserted_row_counts = _count_clickhouse_partitions(client, partition_keys)
    _assert_clickhouse_partition_row_counts(
        inserted_row_counts,
        expected_row_count=1,
        failure_prefix="ClickHouse batch replace must leave exactly one row per partition",
    )


def _replace_clickhouse_partition(client, row: tuple[Any, ...]) -> None:
    partition_key = _date_iso(row[0])
    _replace_clickhouse_partitions(
        client,
        {partition_key: [row]},
        (partition_key,),
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
        column_schema=CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
        extra_metadata={
            "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
            "replace_contract": "sync delete by trade_date, then insert exactly one row",
        },
    ),
    description="本机 ClickHouse 市场宽度 serving 日事实，由市场宽度 gold 和收益率分布 gold 合并生成，供行情事实查询消费。",
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
    log = DgStdoutLogger("clickhouse_market_breadth")
    log.stdout(
        "ch_share_fact_market_breadth_started",
        partition_key=partition_key,
        target_table=CLICKHOUSE_MARKET_BREADTH_TABLE,
    )

    with connect_configured_duckdb() as connection:
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
                "down_gt_10_count",
                "down_7_10_count",
                "down_5_7_count",
                "down_3_5_count",
                "down_0_3_count",
                "flat_count",
                "up_0_3_count",
                "up_3_5_count",
                "up_5_7_count",
                "up_7_10_count",
                "up_gt_10_count",
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

    log.stdout(
        "ch_share_fact_market_breadth_completed",
        partition_key=partition_key,
        target_table=CLICKHOUSE_MARKET_BREADTH_TABLE,
        output_row_count=1,
        total_count=clickhouse_row[4],
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=(
                f"clickhouse://{CLICKHOUSE_MARKET_BREADTH_TABLE}"
                f"?trade_date={partition_key}"
            ),
            row_count=1,
            observed_columns=CLICKHOUSE_MARKET_BREADTH_COLUMNS,
            extra_metadata={
                **_serving_materialization_metadata(
                    partition_key=partition_key,
                    target_system="local_clickhouse",
                    source_summary={
                        "source_assets": [
                            "gold_market_breadth_daily",
                            "gold_stock_return_distribution",
                        ],
                        "gold_market_breadth_daily_path": str(breadth_path),
                        "gold_stock_return_distribution_path": str(distribution_path),
                    },
                ),
                "partition_key": partition_key,
                "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
                "gold_market_breadth_daily_path": str(breadth_path),
                "gold_stock_return_distribution_path": str(distribution_path),
                "replace_mode": "sync_delete_then_insert",
                "lightweight_deletes_sync": 1,
            },
        )
    )


@dg.asset(
    name="prod_ch_share_fact_market_breadth_daily",
    deps=[ch_share_fact_market_breadth_daily],
    partitions_def=cn_a_stock_trade_days,
    backfill_policy=dg.BackfillPolicy.multi_run(
        max_partitions_per_run=PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN,
    ),
    group_name="serving",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="prod_ch_share_fact_market_breadth_daily",
        source_system=SourceSystem.DERIVED,
        data_contract="share_fact_market_breadth_daily_prod_sync",
        column_schema=CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
        extra_metadata={
            "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
            "replace_contract": "prod sync delete by trade_date, then insert local row",
            "upstream_asset": "ch_share_fact_market_breadth_daily",
        },
    ),
    description="Prod ClickHouse 市场宽度 serving 日事实，从本机 ClickHouse serving 同步生成，供生产行情事实查询消费。",
)
def prod_ch_share_fact_market_breadth_daily(
    context: dg.AssetExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.MaterializeResult:
    partition_keys = _selected_partition_keys(context)
    partition_key = partition_keys[0]
    log = DgStdoutLogger("clickhouse_market_breadth")
    log.stdout(
        "prod_ch_share_fact_market_breadth_started",
        partition_key=partition_key,
        target_table=CLICKHOUSE_MARKET_BREADTH_TABLE,
    )
    with clickhouse.get_connection() as local_client:
        local_rows_by_partition = _fetch_clickhouse_market_breadth_row_tuples_by_partition(
            local_client,
            partition_keys,
        )

    with prod_clickhouse.get_connection() as prod_client:
        _replace_clickhouse_partitions(
            prod_client,
            local_rows_by_partition,
            partition_keys,
        )

    log.stdout(
        "prod_ch_share_fact_market_breadth_completed",
        partition_key=partition_key,
        target_table=CLICKHOUSE_MARKET_BREADTH_TABLE,
        output_row_count=1,
    )
    extra_metadata: dict[str, Any] = {
        **_serving_materialization_metadata(
            partition_key=partition_key,
            target_system="prod_clickhouse",
            source_summary={
                "source_asset": "ch_share_fact_market_breadth_daily",
                "partition_count": len(partition_keys),
            },
        ),
        "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
        "source_clickhouse_asset": "ch_share_fact_market_breadth_daily",
        "lightweight_deletes_sync": 1,
        "partition_key": partition_key,
        "partition_count": 1,
        "replace_mode": "sync_delete_then_insert",
    }
    uri = (
        f"clickhouse://prod/{CLICKHOUSE_MARKET_BREADTH_TABLE}"
        f"?trade_date={partition_key}"
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=uri,
            row_count=1,
            observed_columns=CLICKHOUSE_MARKET_BREADTH_COLUMNS,
            extra_metadata=extra_metadata,
        )
    )
