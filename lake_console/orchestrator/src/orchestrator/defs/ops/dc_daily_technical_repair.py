"""Dagster op for bounded ``gold_dc_daily_technical`` repair."""

from __future__ import annotations

from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.dc_daily_silver_repair import (
    parse_dc_daily_silver_repair_batch,
)
from orchestrator.defs.assets.dc_daily_technical_repair import (
    write_gold_dc_daily_technical_repair_batch,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
)
from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
)


GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA = {
    "source_asset": dg.Field(str),
    "producer_run_id": dg.Field(str),
    "upstream_batch_id": dg.Field(str),
    "status": dg.Field(str),
    "source_revision": dg.Field(str),
    "source_repair_start_trade_date": dg.Field(str),
    "source_repair_end_trade_date": dg.Field(str),
    "indicator_recompute_start_trade_date": dg.Field(str),
    "indicator_recompute_end_trade_date": dg.Field(str),
    "context_start_trade_date": dg.Field(str),
    "target_frontier_trade_date": dg.Field(str),
    "affected_date_count": dg.Field(int),
    "affected_series_count": dg.Field(int),
    "affected_series_hash": dg.Field(str),
    "truncated": dg.Field(bool),
    "selected_partition_count": dg.Field(int),
    "protocol_version": dg.Field(str),
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
    config_schema=GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA,
)
def gold_dc_daily_technical_repair_op(context) -> dict[str, object]:
    """Validate one Silver batch, rewrite Gold partitions, and attribute events."""

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
    batch = parse_dc_daily_silver_repair_batch(
        context.op_config,
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
        max_indicator_recompute_dates=DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
    )
    result = write_gold_dc_daily_technical_repair_batch(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        batch=batch,
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )

    for partition_result in result.partition_results:
        metadata = {
            **result.to_metadata(),
            **partition_result.to_metadata(),
            "upstream_batch_id": batch.upstream_batch_id,
            "source_revision": batch.source_revision,
            "event_scope": "gold_dc_daily_technical_repair_partition",
        }
        context.log_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey("gold_dc_daily_technical"),
                partition=partition_result.trade_date,
                metadata=metadata,
            )
        )
        context.log_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey("gold_dc_daily_technical"),
                check_name=GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
                passed=True,
                metadata=metadata,
                blocking=True,
                partition=partition_result.trade_date,
            )
        )

    context.log.info(
        "Gold dc_daily technical repair completed: upstream_batch_id=%s "
        "rewritten_partition_count=%s output_row_count=%s",
        batch.upstream_batch_id,
        result.rewritten_partition_count,
        result.output_row_count,
    )
    return result.to_metadata()


__all__ = [
    "GOLD_DC_DAILY_TECHNICAL_REPAIR_CONFIG_SCHEMA",
    "gold_dc_daily_technical_repair_op",
]
