from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


STOCK_NAMECHANGE_RUN_START = time(9, 30)


def _latest_registered_current_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    already_submitted_for_trade_date: bool,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source_window_started": source_window_started,
            "already_submitted_for_trade_date": already_submitted_for_trade_date,
        },
    )


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(run_key=f"stock_namechange_update:{trade_date}")


@dg.sensor(
    job_name="namechange_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.RAW_SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票当前交易日信号注册后，触发股票曾用名 full snapshot 更新任务。",
)
def stock_namechange_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_NAMECHANGE_RUN_START
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_current_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_current_trade_date(
        registered_trade_days,
        evaluated_at,
    )

    if target_trade_date is None:
        reason = "没有注册股票当前交易日分区，无法触发股票曾用名更新。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "股票曾用名日常更新窗口尚未到 09:30，暂不触发。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    cursor_details = sensor_cursor_details(load_sensor_cursor(context.cursor))
    already_submitted = (
        cursor_details.get("selected_trade_date") == target_trade_date
        and cursor_details.get("already_submitted_for_trade_date") is True
    )
    if already_submitted:
        reason = "最新股票当前交易日已经提交过股票曾用名更新 run，失败时请人工 retry。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=True,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票曾用名日更门禁已满足，提交 full snapshot 更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        already_submitted_for_trade_date=True,
    )
    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )
