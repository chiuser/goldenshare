"""Consume completed Raw weekly deliveries without reading market data."""

import dagster as dg

from orchestrator.defs.jobs.stock_weekly import silver_stock_weekly_update_job
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stock_period_silver import SENSOR_TICK_SECONDS
from orchestrator.defs.stock_period_silver import evaluate_update_sensor


@dg.sensor(
    jobs=[silver_stock_weekly_update_job],
    minimum_interval_seconds=SENSOR_TICK_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def silver_stock_weekly_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_update_sensor(context, freq="week")
