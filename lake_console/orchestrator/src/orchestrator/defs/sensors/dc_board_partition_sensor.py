"""Calendar-only partition registration sensors for the board asset family."""

import dagster as dg

from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_calendar_only_partition_registration_result,
)


def _result(context: dg.SensorEvaluationContext, *, dynamic_partitions, min_trade_date, sensor_name, label):
    return build_calendar_only_partition_registration_result(
        context,
        dynamic_partitions=dynamic_partitions,
        min_trade_date=min_trade_date,
        partition_set_label=label,
        sensor_name=sensor_name,
        asset_family="dc_board_partition_registration",
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
    description="只按 SSE 交易日历注册 dc_index 专属交易日分区，不探测源站。",
)
def dc_index_trade_day_partition_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _result(
        context,
        dynamic_partitions=cn_a_dc_index_trade_days,
        min_trade_date=DC_INDEX_HISTORY_START_DATE,
        sensor_name="dc_index_trade_day_partition_sensor",
        label="dc_index",
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
    description="只按 SSE 交易日历注册 dc_member 专属交易日分区，不探测源站。",
)
def dc_member_trade_day_partition_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _result(
        context,
        dynamic_partitions=cn_a_dc_member_trade_days,
        min_trade_date=DC_MEMBER_HISTORY_START_DATE,
        sensor_name="dc_member_trade_day_partition_sensor",
        label="dc_member",
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
    description="只按 SSE 交易日历注册 dc_daily 专属交易日分区，不探测源站。",
)
def dc_daily_trade_day_partition_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _result(
        context,
        dynamic_partitions=cn_a_dc_daily_trade_days,
        min_trade_date=DC_DAILY_HISTORY_START_DATE,
        sensor_name="dc_daily_trade_day_partition_sensor",
        label="dc_daily",
    )


__all__ = [
    "dc_daily_trade_day_partition_sensor",
    "dc_index_trade_day_partition_sensor",
    "dc_member_trade_day_partition_sensor",
]
