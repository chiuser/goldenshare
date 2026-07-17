"""Local ClickHouse serving asset for ``gold_dc_daily_technical``."""

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.assets.dc_daily_technical_asset import gold_dc_daily_technical
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import gold_dc_daily_technical_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")


class DcDailyTechnicalServingValidationError(ValueError):
    """Raised when the Gold input cannot be served safely."""


def _expected_schema() -> tuple[tuple[str, str], ...]:
    return tuple(
        (column.name, column.type.upper())
        for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA
    )


def _read_gold_rows(
    connection,
    path: Path,
    *,
    partition_key: str,
) -> list[tuple[Any, ...]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing Gold technical parquet: {path}")

    relation = read_parquet(path, hive_partitioning=False)
    observed_schema = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    if observed_schema != _expected_schema():
        raise DcDailyTechnicalServingValidationError(
            "Gold technical schema mismatch: "
            f"expected={_expected_schema()}, observed={observed_schema}"
        )

    projection = ", ".join(DC_DAILY_TECHNICAL_SERVING_COLUMNS)
    rows = connection.execute(
        f"""
        SELECT {projection}
        FROM {relation}
        """
    ).fetchall()
    if not rows:
        raise DcDailyTechnicalServingValidationError(
            f"Gold technical partition is empty: {partition_key}"
        )

    metrics = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(*) FILTER (WHERE trade_date IS NULL OR CAST(trade_date AS VARCHAR) <> ?)
            AS date_mismatch_count,
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR category IS NULL OR trim(CAST(category AS VARCHAR)) = ''
          ) AS invalid_key_count,
          count(*) - count(DISTINCT (ts_code, trade_date, category))
            AS duplicate_key_count
        FROM {relation}
        """,
        [partition_key],
    ).fetchone()
    row_count, date_mismatch_count, invalid_key_count, duplicate_key_count = (
        int(value or 0) for value in metrics
    )
    if row_count != len(rows):
        raise DcDailyTechnicalServingValidationError(
            f"Gold technical row count changed during read: {partition_key}"
        )
    if date_mismatch_count or invalid_key_count or duplicate_key_count:
        raise DcDailyTechnicalServingValidationError(
            "Gold technical key/date validation failed: "
            f"date_mismatch={date_mismatch_count}, "
            f"invalid_key={invalid_key_count}, duplicate_key={duplicate_key_count}"
        )
    return [tuple(row) for row in rows]


def _trade_date_filter(partition_key: str) -> tuple[str, dict[str, date]]:
    return "trade_date = %(trade_date)s", {
        "trade_date": date.fromisoformat(partition_key),
    }


def _trade_dates_filter(
    partition_keys: tuple[str, ...],
) -> tuple[str, dict[str, date]]:
    if not partition_keys:
        raise ValueError("partition_keys must not be empty")
    params: dict[str, date] = {}
    placeholders: list[str] = []
    for index, partition_key in enumerate(partition_keys):
        name = f"trade_date_{index}"
        placeholders.append(f"%({name})s")
        params[name] = date.fromisoformat(partition_key)
    return f"trade_date IN ({', '.join(placeholders)})", params


def fetch_dc_daily_technical_rows_for_partitions(
    client,
    partition_keys: tuple[str, ...],
) -> dict[str, list[tuple[Any, ...]]]:
    """Fetch explicit serving rows grouped by trade date."""

    where_sql, params = _trade_dates_filter(partition_keys)
    rows = client.execute(
        f"SELECT {', '.join(DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS)} "
        f"FROM {DC_DAILY_TECHNICAL_SERVING_TABLE} "
        f"WHERE {where_sql} ORDER BY trade_date, category, ts_code",
        params,
    )
    result = {partition_key: [] for partition_key in partition_keys}
    for row in rows:
        trade_date = row[1]
        partition_key = (
            trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date)
        )
        if partition_key in result:
            result[partition_key].append(tuple(row))
    return result


def _count_target_partition(client, partition_key: str) -> int:
    where_sql, params = _trade_date_filter(partition_key)
    rows = client.execute(
        f"SELECT count() FROM {DC_DAILY_TECHNICAL_SERVING_TABLE} WHERE {where_sql}",
        params,
    )
    return int(rows[0][0]) if rows else 0


def replace_dc_daily_technical_partition(
    client,
    *,
    partition_key: str,
    rows: list[tuple[Any, ...]],
) -> None:
    """Replace one ClickHouse date with one explicit insert batch."""

    if not rows:
        raise DcDailyTechnicalServingValidationError(
            f"Cannot replace an empty serving partition: {partition_key}"
        )
    client.execute("SET lightweight_deletes_sync = 1")
    where_sql, params = _trade_date_filter(partition_key)
    client.execute(
        f"DELETE FROM {DC_DAILY_TECHNICAL_SERVING_TABLE} WHERE {where_sql}",
        params,
    )
    if _count_target_partition(client, partition_key) != 0:
        raise RuntimeError(
            "Synchronous ClickHouse delete did not empty the target partition: "
            f"{partition_key}"
        )

    client.execute(
        f"INSERT INTO {DC_DAILY_TECHNICAL_SERVING_TABLE} "
        f"({', '.join(DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS)}) VALUES",
        rows,
    )
    actual_count = _count_target_partition(client, partition_key)
    if actual_count != len(rows):
        raise RuntimeError(
            "ClickHouse serving row count mismatch after insert: "
            f"partition={partition_key}, expected={len(rows)}, actual={actual_count}"
        )


@dg.asset(
    name="ch_dc_daily_technical",
    deps=[gold_dc_daily_technical],
    partitions_def=cn_a_dc_daily_trade_days,
    group_name="serving",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="ch_dc_daily_technical",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_dc_daily_technical_clickhouse_serving",
        column_schema=CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
        extra_metadata={
            "clickhouse_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "replace_contract": "sync delete by trade_date, then explicit single-batch insert",
            "upstream_asset": "gold_dc_daily_technical",
        },
    ),
    description="本机 ClickHouse 技术指标 serving，事实源为 gold_dc_daily_technical。",
)
def ch_dc_daily_technical(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    target_path = gold_dc_daily_technical_path(lake_root.root(), partition_key)
    duckdb_resource = duckdb
    with duckdb_resource.connect() as connection:
        gold_rows = _read_gold_rows(
            connection,
            target_path,
            partition_key=partition_key,
        )
    updated_at = datetime.now(CN_A_TIMEZONE).replace(tzinfo=None)
    serving_rows = [(*row, updated_at) for row in gold_rows]
    with clickhouse.get_connection() as client:
        replace_dc_daily_technical_partition(
            client,
            partition_key=partition_key,
            rows=serving_rows,
        )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=(
                f"clickhouse://{DC_DAILY_TECHNICAL_SERVING_TABLE}"
                f"?trade_date={partition_key}"
            ),
            row_count=len(serving_rows),
            observed_columns=DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
            extra_metadata={
                "partition_key": partition_key,
                "clickhouse_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
                "source_asset": "gold_dc_daily_technical",
                "source_path": str(target_path),
                "replace_mode": "sync_delete_then_insert",
                "lightweight_deletes_sync": 1,
                "null_semantics": "MA/BOLL warmup NULL preserved",
            },
        )
    )


def _selected_prod_partition(context: dg.AssetExecutionContext) -> str:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    if len(partition_keys) != 1:
        raise RuntimeError(
            "prod ClickHouse technical sync requires exactly one partition: "
            f"partition_count={len(partition_keys)}"
        )
    return partition_keys[0]


@dg.asset(
    name="prod_ch_dc_daily_technical",
    deps=[ch_dc_daily_technical],
    partitions_def=cn_a_dc_daily_trade_days,
    backfill_policy=dg.BackfillPolicy.multi_run(max_partitions_per_run=1),
    group_name="serving",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="prod_ch_dc_daily_technical",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_dc_daily_technical_prod_clickhouse_sync",
        column_schema=CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
        extra_metadata={
            "clickhouse_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "upstream_asset": "ch_dc_daily_technical",
            "replace_contract": "single partition; local read before Prod replace",
        },
    ),
    description="将本机 ClickHouse 板块技术指标 serving 按交易日同步到 Prod ClickHouse。",
)
def prod_ch_dc_daily_technical(
    context: dg.AssetExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.MaterializeResult:
    partition_key = _selected_prod_partition(context)
    with clickhouse.get_connection() as local_client:
        local_rows = fetch_dc_daily_technical_rows_for_partitions(
            local_client,
            (partition_key,),
        )
    if not local_rows[partition_key]:
        raise DcDailyTechnicalServingValidationError(
            f"Local ClickHouse serving partition is missing: {partition_key}"
        )
    with prod_clickhouse.get_connection() as prod_client:
        replace_dc_daily_technical_partition(
            prod_client,
            partition_key=partition_key,
            rows=local_rows[partition_key],
        )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=(
                f"clickhouse://{DC_DAILY_TECHNICAL_SERVING_TABLE}"
                f"?trade_date={partition_key}"
            ),
            row_count=len(local_rows[partition_key]),
            observed_columns=DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
            extra_metadata={
                "partition_key": partition_key,
                "clickhouse_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
                "source_asset": "ch_dc_daily_technical",
                "target_system": "prod_clickhouse",
                "replace_mode": "sync_delete_then_insert",
                "lightweight_deletes_sync": 1,
            },
        )
    )


__all__ = [
    "DcDailyTechnicalServingValidationError",
    "ch_dc_daily_technical",
    "fetch_dc_daily_technical_rows_for_partitions",
    "prod_ch_dc_daily_technical",
    "replace_dc_daily_technical_partition",
]
