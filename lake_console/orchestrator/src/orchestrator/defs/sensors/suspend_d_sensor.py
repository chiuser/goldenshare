import json
from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    RAW_SUSPEND_D_ASSET_KEY,
    SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY,
    materialized_partition_keys,
)


MAX_RUN_REQUESTS_PER_TICK = 2


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_count: int,
    pending_keys: tuple[str, ...],
    selected_keys: tuple[str, ...],
) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "registered_count": registered_count,
        "pending_count": len(pending_keys),
        "selected_keys": list(selected_keys),
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job_name="suspend_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    description=(
        "Triggers suspend_update_job for registered trading day partitions whose "
        "suspend_d raw/silver assets are missing."
    ),
)
def suspend_d_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_keys = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_trade_days.name))
    )
    materialized_keys = materialized_partition_keys(
        context.instance,
        (RAW_SUSPEND_D_ASSET_KEY, SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY),
    )
    pending_keys = tuple(key for key in registered_keys if key not in materialized_keys)
    selected_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        pending_keys=pending_keys,
        selected_keys=selected_keys,
    )

    if not selected_keys:
        return dg.SensorResult(
            skip_reason=(
                "当前所有已注册交易日的停复牌分区都已经生成完成；如果存在失败检查，"
                "需要通过 Dagster UI 或明确的重试策略处理。"
            ),
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            dg.RunRequest(
                partition_key=key,
                run_key=f"suspend_d_update:{key}",
                tags={"triggered_by": "suspend_d_sensor"},
            )
            for key in selected_keys
        ],
        cursor=cursor,
    )
