"""Independent, STOPPED 东方财富板块 registration and update sensors."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.jobs.moneyflow_ind_dc import (
    raw_tushare_moneyflow_ind_dc_update_job,
    silver_moneyflow_ind_dc_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_ind_dc_trade_days
from orchestrator.defs.run_contracts.moneyflow import MONEYFLOW_SENSOR_INTERVAL
from orchestrator.defs.run_contracts.moneyflow_automation import (
    BOARD_DC_MONEYFLOW_AUTOMATION,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.moneyflow_update_selection import (
    evaluate_moneyflow_update,
    register_moneyflow_trade_days,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

RAW_JOB = BOARD_DC_MONEYFLOW_AUTOMATION.raw_job
SILVER_JOB = BOARD_DC_MONEYFLOW_AUTOMATION.silver_job
PARTITIONS = cn_a_moneyflow_ind_dc_trade_days.name


def evaluate_board_moneyflow_dc(context, now, *, silver=False):
    return evaluate_moneyflow_update(
        context, now, contract=BOARD_DC_MONEYFLOW_AUTOMATION, silver=silver
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="上海22:00后优先登记东方财富板块资金流当日，最多补一个接续漏登记日，不提交job。",
)
def cn_a_moneyflow_ind_dc_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return register_moneyflow_trade_days(
        context,
        contract=BOARD_DC_MONEYFLOW_AUTOMATION,
        dynamic_partitions=cn_a_moneyflow_ind_dc_trade_days,
    )


@dg.sensor(
    job=raw_tushare_moneyflow_ind_dc_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="22:00后最近10日一次提交一日Raw，临时源错误有限重试，每日最多复核一次。",
)
def raw_tushare_moneyflow_ind_dc_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_board_moneyflow_dc(context, datetime.now(CN_A_SENSOR_TIMEZONE))


@dg.sensor(
    job=silver_moneyflow_ind_dc_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="同日已绿Raw产生新hash后一次提交一日Silver，不请求源。",
)
def silver_moneyflow_ind_dc_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_board_moneyflow_dc(
        context, datetime.now(CN_A_SENSOR_TIMEZONE), silver=True
    )
