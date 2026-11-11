"""Coordinate successful weekly/monthly current Raw deliveries."""

import dagster as dg

from orchestrator.defs.jobs.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_job,
)
from orchestrator.defs.jobs.stock_monthly import raw_stk_period_bar_adj_month_update_job
from orchestrator.defs.jobs.stock_weekly import raw_stk_period_bar_adj_week_update_job
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.stock_period_history_repair import evaluate_history_repair_sensor


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    monitored_jobs=[
        raw_stk_period_bar_adj_week_update_job,
        raw_stk_period_bar_adj_month_update_job,
    ],
    request_job=raw_stock_period_history_repair_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_stock_period_history_repair_job_sensor(context, lake_root: LakeRootResource):
    return evaluate_history_repair_sensor(context, lake_root)
