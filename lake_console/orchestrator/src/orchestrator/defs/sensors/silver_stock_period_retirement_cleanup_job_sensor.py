"""A successful current Silver run triggers only its own frequency's cleanup."""

import dagster as dg

from orchestrator.defs.jobs.silver_stock_period_retirement_cleanup import (
    silver_stock_period_retirement_cleanup_job,
)
from orchestrator.defs.jobs.stock_monthly import silver_stock_monthly_update_job
from orchestrator.defs.jobs.stock_weekly import silver_stock_weekly_update_job
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.stock_period_retirement_cleanup import evaluate_retirement_sensor


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    monitored_jobs=[
        silver_stock_weekly_update_job,
        silver_stock_monthly_update_job,
    ],
    request_job=silver_stock_period_retirement_cleanup_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def silver_stock_period_retirement_cleanup_job_sensor(
    context, lake_root: LakeRootResource
):
    return evaluate_retirement_sensor(context, lake_root)
