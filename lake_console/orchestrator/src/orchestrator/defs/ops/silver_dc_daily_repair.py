"""Dagster handoff op for bounded ``silver_dc_daily`` repair batches."""

from __future__ import annotations

from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.dc_daily_silver_repair_producer import (
    produce_dc_daily_silver_repair_batch,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.silver_repair import (
    SILVER_REPAIR_RUN_TAG_PREFIX,
)


SILVER_DC_DAILY_REPAIR_CONFIG_SCHEMA = {
    "source_repair_start_trade_date": dg.Field(str),
    "source_repair_end_trade_date": dg.Field(str),
    "indicator_recompute_end_trade_date": dg.Field(str),
    "context_start_trade_date": dg.Field(str),
    "target_frontier_trade_date": dg.Field(str),
}


def _load_expected_trade_dates(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing Silver trade calendar: {calendar_path}")
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d')
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE CAST(exchange AS VARCHAR) = 'SSE'
              AND CAST(is_open AS BOOLEAN)
            GROUP BY CAST(trade_date AS DATE)
            ORDER BY CAST(trade_date AS DATE)
            """
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


@dg.op(
    required_resource_keys={"lake_root", "duckdb"},
    config_schema=SILVER_DC_DAILY_REPAIR_CONFIG_SCHEMA,
)
def silver_dc_daily_repair_op(context) -> dict[str, object]:
    """Produce one bounded Silver repair batch and publish scalar run tags."""

    lake_root_resource: LakeRootResource = context.resources.lake_root
    lake_root_resource.ensure_available_for_run()
    lake_root = lake_root_resource.root()
    duckdb_resource: DuckDBResource = context.resources.duckdb
    expected_trade_dates = _load_expected_trade_dates(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    registered_trade_dates = tuple(
        context.instance.get_dynamic_partitions(cn_a_dc_daily_trade_days.name)
    )
    config = context.op_config
    result = produce_dc_daily_silver_repair_batch(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        producer_run_id=context.run_id,
        source_repair_start_trade_date=config["source_repair_start_trade_date"],
        source_repair_end_trade_date=config["source_repair_end_trade_date"],
        indicator_recompute_end_trade_date=config["indicator_recompute_end_trade_date"],
        context_start_trade_date=config["context_start_trade_date"],
        target_frontier_trade_date=config["target_frontier_trade_date"],
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )

    if result.batch is None:
        context.instance.add_run_tags(
            context.run_id,
            {
                f"{SILVER_REPAIR_RUN_TAG_PREFIX}source_asset": "silver_dc_daily",
                f"{SILVER_REPAIR_RUN_TAG_PREFIX}producer_run_id": context.run_id,
                f"{SILVER_REPAIR_RUN_TAG_PREFIX}status": "no_op",
                f"{SILVER_REPAIR_RUN_TAG_PREFIX}source_revision": result.source_revision,
            },
        )
        context.log.info(
            "Silver dc_daily repair is a no-op: source_revision=%s",
            result.source_revision,
        )
    else:
        context.instance.add_run_tags(context.run_id, result.batch.to_run_tags())
        context.log.info(
            "Silver dc_daily repair batch is ready: upstream_batch_id=%s "
            "source_revision=%s selected_partition_count=%s",
            result.batch.upstream_batch_id,
            result.batch.source_revision,
            result.batch.selected_partition_count,
        )
    return result.to_metadata()


__all__ = [
    "SILVER_DC_DAILY_REPAIR_CONFIG_SCHEMA",
    "silver_dc_daily_repair_op",
]
