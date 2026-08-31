"""Calendar-only partition registration for ETF minute assets."""

import dagster as dg

from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
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


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="只按 SSE 交易日历注册 ETF 分钟专属交易日分区，不探测行情源。",
)
def etf_mins_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return build_calendar_only_partition_registration_result(
        context,
        dynamic_partitions=cn_a_etf_mins_trade_days,
        min_trade_date=ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat(),
        partition_set_label="etf_mins",
        sensor_name="etf_mins_trade_day_sensor",
        asset_family="etf_mins_partition_registration",
    )


__all__ = ["etf_mins_trade_day_sensor"]
