"""Daily direct-source monthly orchestration; no source requests or Parquet writes in sensors."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.jobs.stock_monthly import raw_stk_period_bar_adj_month_update_job
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.stock_monthly_update import MONTHLY_UPDATE_POLICY
from orchestrator.defs.stock_period_update import evaluate_daily_sensor


def evaluate_stock_monthly_update(context, now, *, staging_root=None):
    return evaluate_daily_sensor(context, now, freq="month", staging_root=staging_root)


@dg.sensor(
    jobs=[raw_stk_period_bar_adj_month_update_job],
    minimum_interval_seconds=MONTHLY_UPDATE_POLICY.tick_min_seconds,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_stock_monthly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_stock_monthly_update(
        context, datetime.now(ZoneInfo(MONTHLY_UPDATE_POLICY.timezone))
    )
