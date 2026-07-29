"""Calendar-only registration for the index minute partition set."""

import dagster as dg

from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_HISTORY_START_DATE
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_calendar_only_partition_registration_result,
)


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description=(
        "只按 SSE 交易日历注册指数分钟线专属交易日分区，不探测 Prod 明细。"
    ),
)
def index_mins_trade_day_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return build_calendar_only_partition_registration_result(
        context,
        dynamic_partitions=cn_a_index_mins_trade_days,
        min_trade_date=INDEX_MINS_HISTORY_START_DATE,
        partition_set_label="index_mins",
        sensor_name="index_mins_trade_day_sensor",
        asset_family="index_mins_partition_registration",
    )


__all__ = ["index_mins_trade_day_sensor"]
