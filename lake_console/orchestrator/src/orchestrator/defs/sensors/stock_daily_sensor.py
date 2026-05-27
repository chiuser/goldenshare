import json
from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    RAW_STOCK_DAILY_ASSET_KEY,
    SILVER_STOCK_DAILY_ASSET_KEY,
    materialized_partition_keys,
    status_payload,
    stock_basic_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)
from orchestrator.source_readiness.tushare.stock_daily import (
    check_stock_daily_source_readiness,
)


MAX_RUN_REQUESTS_PER_TICK = 2


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_count: int,
    pending_keys: tuple[str, ...],
    selected_keys: tuple[str, ...],
    blocked_basic_keys: tuple[str, ...],
    blocked_suspend_keys: tuple[str, ...],
    source_not_ready_keys: tuple[str, ...],
    readiness_details: dict[str, object],
) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "registered_count": registered_count,
        "pending_count": len(pending_keys),
        "selected_keys": list(selected_keys),
        "blocked_basic_keys": list(blocked_basic_keys),
        "blocked_suspend_keys": list(blocked_suspend_keys),
        "source_not_ready_keys": list(source_not_ready_keys),
        "readiness_details": readiness_details,
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job_name="stock_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"tushare"},
    description="股票基础信息、停复牌和源站日线就绪后，触发日线更新任务。",
)
def stock_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()
    registered_keys = tuple(
        key
        for key in sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
        if key <= today
    )
    materialized_keys = materialized_partition_keys(
        context.instance,
        (RAW_STOCK_DAILY_ASSET_KEY, SILVER_STOCK_DAILY_ASSET_KEY),
    )
    pending_keys = tuple(key for key in registered_keys if key not in materialized_keys)
    candidate_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]

    selected_keys = []
    blocked_basic_keys = []
    blocked_suspend_keys = []
    source_not_ready_keys = []
    readiness_details: dict[str, object] = {}

    for key in candidate_keys:
        basic_status = stock_basic_ready_for_trade_date(context.instance, key)
        readiness_details.setdefault(key, {})
        readiness_details[key]["stock_basic"] = status_payload(basic_status)
        if not basic_status.ready:
            blocked_basic_keys.append(key)
            continue

        suspend_status = suspend_d_ready_for_trade_date(context.instance, key)
        readiness_details[key]["suspend_d"] = status_payload(suspend_status)
        if not suspend_status.ready:
            blocked_suspend_keys.append(key)
            continue

        source_readiness = check_stock_daily_source_readiness(
            tushare=context.resources.tushare,
            trade_date=key,
            checked_at=evaluated_at,
        )
        readiness_details[key]["source_readiness"] = {
            "is_ready": source_readiness.is_ready,
            "trade_date": source_readiness.trade_date,
            "row_count": source_readiness.row_count,
            "checked_at": source_readiness.checked_at,
            "reason": source_readiness.reason,
        }
        if not source_readiness.is_ready:
            source_not_ready_keys.append(key)
            continue

        selected_keys.append(key)

    selected_tuple = tuple(selected_keys)
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        pending_keys=pending_keys,
        selected_keys=selected_tuple,
        blocked_basic_keys=tuple(blocked_basic_keys),
        blocked_suspend_keys=tuple(blocked_suspend_keys),
        source_not_ready_keys=tuple(source_not_ready_keys),
        readiness_details=readiness_details,
    )

    if not selected_tuple:
        if not pending_keys:
            skip_reason = "当前所有已注册交易日的股票日线分区都已经生成完成。"
        elif blocked_basic_keys:
            skip_reason = "股票基础信息还没有通过 materialization 和 blocking checks 门禁。"
        elif blocked_suspend_keys:
            skip_reason = "停复牌分区还没有通过 materialization 和 blocking checks 门禁。"
        elif source_not_ready_keys:
            skip_reason = "Tushare 日线源站还没有返回有效数据。"
        else:
            skip_reason = "当前没有满足门禁的股票日线待补分区。"
        return dg.SensorResult(skip_reason=skip_reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=key,
                run_key=f"stock_daily_update:{key}",
            )
            for key in selected_tuple
        ],
        cursor=cursor,
    )
