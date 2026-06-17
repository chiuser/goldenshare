from datetime import time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_RAW_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_trade_day_partition_registration_result,
)


STOCK_MINS_TRADE_DAY_REGISTER_START = time(18, 0)


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="每天 18:00 后补注册股票分钟线 raw 交易日分区，不触发数据更新任务。",
)
def stock_mins_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return build_trade_day_partition_registration_result(
        context,
        dynamic_partitions=cn_a_stock_mins_trade_days,
        min_trade_date=STK_MINS_RAW_HISTORY_START_DATE,
        partition_set_label="股票分钟线 raw",
        same_day_register_start=STOCK_MINS_TRADE_DAY_REGISTER_START,
    )
