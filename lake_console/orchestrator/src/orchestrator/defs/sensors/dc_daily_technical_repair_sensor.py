"""Stopped-by-default handoff sensor for bounded Gold board repairs."""

from __future__ import annotations

from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.dc_daily_silver_repair import (
    parse_dc_daily_silver_repair_batch_from_run_tags,
)
from orchestrator.defs.asset_guards.dc_daily_silver_repair_producer import (
    source_revision_for_silver_paths,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.jobs.dc_daily_technical_repair import (
    gold_dc_daily_technical_repair_job,
)
from orchestrator.defs.jobs.silver_dc_daily_repair import silver_dc_daily_repair_job
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import silver_dc_daily_path, silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_upstream_triggered_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


SENSOR_NAME = "gold_dc_daily_technical_repair_job_sensor"
GOLD_REPAIR_CONSUMER = "gold_dc_daily_technical_repair"


def _load_expected_trade_dates(connection, calendar_path: Path) -> tuple[str, ...]:
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing Silver trade calendar: {calendar_path}")
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


def _skip(code: str, detail: str) -> dg.SkipReason:
    return dg.SkipReason(f"{code}: {detail}")


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_dc_daily_technical_repair_job,
    monitored_jobs=[silver_dc_daily_repair_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "Silver dc_daily repair producer 成功后，按 ready batch tags 有界触发 Gold 技术指标 repair。"
    ),
)
def gold_dc_daily_technical_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    """Consume one successful Silver producer run without event-history scans."""

    dagster_run = context.dagster_run
    tags = dagster_run.tags
    if tags.get("goldenshare/silver_repair/status") != "ready":
        return _skip("batch_not_ready", "successful producer has no ready repair batch")

    try:
        lake_root_resource: LakeRootResource = context.resources.lake_root
        lake_root_resource.ensure_available_for_run()
        duckdb_resource: DuckDBResource = context.resources.duckdb
        lake_root = lake_root_resource.root()
        with duckdb_resource.connect() as connection:
            expected_trade_dates = _load_expected_trade_dates(
                connection,
                silver_trade_calendar_path(lake_root),
            )
            registered_trade_dates = tuple(
                context.instance.get_dynamic_partitions(cn_a_index_trade_days.name)
            )
            batch = parse_dc_daily_silver_repair_batch_from_run_tags(
                tags,
                expected_trade_dates=expected_trade_dates,
                registered_trade_dates=registered_trade_dates,
                max_indicator_recompute_dates=DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
            )
            if batch.producer_run_id != dagster_run.run_id:
                return _skip(
                    "producer_run_id_mismatch",
                    "repair batch producer_run_id does not match triggering run",
                )
            source_dates = tuple(
                date_key
                for date_key in expected_trade_dates
                if batch.source_repair_start_trade_date
                <= date_key
                <= batch.source_repair_end_trade_date
            )
            source_paths = tuple(silver_dc_daily_path(lake_root, date_key) for date_key in source_dates)
            missing_paths = tuple(path for path in source_paths if not path.exists())
            if missing_paths:
                return _skip(
                    "silver_source_missing",
                    f"bounded Silver source files are missing count={len(missing_paths)}",
                )
            current_revision = source_revision_for_silver_paths(connection, source_paths)
            if current_revision != batch.source_revision:
                return _skip(
                    "source_revision_mismatch",
                    "current Silver source revision differs from producer batch",
                )
    except Exception as error:
        return _skip("batch_validation_failed", str(error)[:300])

    return build_run_request(
        run_key=build_upstream_triggered_run_key(
            consumer=GOLD_REPAIR_CONSUMER,
            upstream_batch_id=batch.upstream_batch_id,
        ),
        run_config={
            "ops": {
                "gold_dc_daily_technical_repair_op": {
                    "config": batch.to_payload(),
                }
            }
        },
    )


__all__ = ["gold_dc_daily_technical_repair_job_sensor"]
