"""Register at most two daily-basic dates, without launching work."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_HISTORY_START,
    DAILY_BASIC_INTERVAL,
    DAILY_BASIC_REGISTER_START,
)
from orchestrator.defs.partitions import cn_a_daily_basic_trade_days
from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
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


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=DAILY_BASIC_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="17:00后注册股票每日指标交易日，每次最多两日，不提交更新任务。",
)
def daily_basic_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    result = build_trade_day_partition_registration_result(
        context,
        dynamic_partitions=cn_a_daily_basic_trade_days,
        min_trade_date=DAILY_BASIC_HISTORY_START,
        partition_set_label="股票每日指标",
        same_day_register_start=DAILY_BASIC_REGISTER_START,
        sensor_name="daily_basic_trade_day_sensor",
        asset_family="daily_basic_trade_day_partitions",
        cursor_partition_set=cn_a_daily_basic_trade_days.name,
    )
    payload = load_sensor_cursor(result.cursor)
    count = payload["selected_count"]
    details = dict(payload["details"])
    details["summary"] = (
        f"本次注册{count}个每日指标交易日分区。"
        if count
        else result.skip_reason.skip_message
    )
    details["next_action"] = (
        "等待每日指标更新门禁就绪。" if count else "等待下次交易日历检查。"
    )
    return result._replace(
        cursor=build_sensor_cursor(
            evaluated_at=datetime.fromisoformat(payload["evaluated_at"]),
            decision=payload["decision"],
            target_date=payload["target_date"],
            selected_count=count,
            blocked_count=payload["blocked_count"],
            sample_keys=payload["sample_keys"],
            details=details,
        )
    )
