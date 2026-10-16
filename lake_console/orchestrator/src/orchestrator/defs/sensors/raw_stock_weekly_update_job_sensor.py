"""Daily direct-source weekly orchestration; no source requests or Parquet writes in sensors."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.jobs.stock_weekly import raw_stk_period_bar_adj_week_update_job
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.stock_period_update import evaluate_daily_sensor
from orchestrator.defs.stock_weekly_update import WEEKLY_UPDATE_POLICY


def evaluate_stock_weekly_update(context, now, *, staging_root=None):
    return evaluate_daily_sensor(context, now, freq="week", staging_root=staging_root)


@dg.sensor(
    jobs=[raw_stk_period_bar_adj_week_update_job],
    minimum_interval_seconds=WEEKLY_UPDATE_POLICY.tick_min_seconds,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_stock_weekly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_stock_weekly_update(
        context, datetime.now(ZoneInfo(WEEKLY_UPDATE_POLICY.timezone))
    )
