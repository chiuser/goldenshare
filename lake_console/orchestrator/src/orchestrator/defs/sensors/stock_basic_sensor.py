from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    status_payload,
    stock_basic_ready_for_trade_date,
)


def _cursor_payload(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    target_trade_date: str | None,
    ready: bool | None,
    readiness_reason: str | None,
    asset_statuses: dict[str, object] | None = None,
) -> str:
    details: dict[str, object] = {
        "ready": ready,
        "readiness_reason": readiness_reason,
    }
    if asset_statuses is not None:
        details["asset_statuses"] = asset_statuses
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if decision == SensorCursorDecision.REQUEST_RUNS else 0,
        sample_keys=(
            (target_trade_date,)
            if decision == SensorCursorDecision.REQUEST_RUNS and target_trade_date
            else ()
        ),
        details=details,
    )


@dg.sensor(
    job_name="stock_basic_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    description="股票基础信息未满足最新交易日要求时，触发更新任务。",
)
def stock_basic_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()
    registered_keys = tuple(
        key
        for key in sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
        if key <= today
    )
    if not registered_keys:
        return dg.SensorResult(
            skip_reason="当前还没有已注册交易日分区，暂不触发股票基础信息日更快照。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                target_trade_date=None,
                ready=None,
                readiness_reason="no registered trade day partitions",
            ),
        )

    target_trade_date = registered_keys[-1]
    readiness = stock_basic_ready_for_trade_date(context.instance, target_trade_date)
    cursor_decision = (
        SensorCursorDecision.SKIP
        if readiness.ready
        else SensorCursorDecision.REQUEST_RUNS
    )
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_trade_date=target_trade_date,
        ready=readiness.ready,
        readiness_reason=readiness.reason,
        asset_statuses=status_payload(readiness),
    )

    if readiness.ready:
        return dg.SensorResult(
            skip_reason="股票基础信息已经满足最新已注册交易日的日更快照要求。",
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=f"stock_basic_update:{target_trade_date}",
            )
        ],
        cursor=cursor,
    )
