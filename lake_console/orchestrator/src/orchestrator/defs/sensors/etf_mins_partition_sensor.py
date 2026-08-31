"""Calendar-only partition registration for ETF minute assets."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
    etf_sensor_window_is_open,
    normalize_etf_sensor_evaluated_at,
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
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


def evaluate_etf_mins_trade_day_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    now = normalize_etf_sensor_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if not etf_sensor_window_is_open(now):
        return dg.SensorResult(
            skip_reason="ETF 自动更新等待上海时间 21:00 运行窗口。",
            cursor=build_sensor_cursor(
                evaluated_at=now,
                decision=SensorCursorDecision.SKIP,
                target_date=now.date().isoformat(),
                blocked_count=1,
                details={
                    "summary": "ETF partition sensor is outside the operating window",
                    "next_action": "wait for Shanghai time 21:00",
                    "sensor_name": "etf_mins_trade_day_sensor",
                    "reason_code": "outside_operating_window",
                },
            ),
        )
    return build_calendar_only_partition_registration_result(
        context,
        dynamic_partitions=cn_a_etf_mins_trade_days,
        min_trade_date=ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat(),
        partition_set_label="etf_mins",
        sensor_name="etf_mins_trade_day_sensor",
        asset_family="etf_mins_partition_registration",
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
    description=(
        "上海时间 21:00 后只按 SSE 交易日历注册 ETF 分钟专属交易日分区，"
        "不探测行情源。"
    ),
)
def etf_mins_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_etf_mins_trade_day_sensor(context)


__all__ = ["etf_mins_trade_day_sensor", "evaluate_etf_mins_trade_day_sensor"]
