"""Daily dynamic partition registration for stock nine-turn assets."""

from datetime import time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_trade_day_partition_registration_result,
)
from orchestrator.defs.stk_nineturn_contract import STK_NINETURN_HISTORY_START_DATE


STK_NINETURN_TRADE_DAY_REGISTER_START = time(17, 0)


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "17:00 后补注册神奇九转交易日分区，每 tick 最多 2 个，"
        "不触发数据更新任务。"
    ),
)
def stk_nineturn_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return build_trade_day_partition_registration_result(
        context,
        dynamic_partitions=cn_a_stk_nineturn_trade_days,
        min_trade_date=STK_NINETURN_HISTORY_START_DATE,
        partition_set_label="神奇九转",
        same_day_register_start=STK_NINETURN_TRADE_DAY_REGISTER_START,
        sensor_name="stk_nineturn_trade_day_sensor",
        asset_family="stk_nineturn_trade_day_partitions",
        cursor_partition_set=cn_a_stk_nineturn_trade_days.name,
    )
