from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    raw_stk_mins_ready_for_trade_date,
    status_payload,
    stock_basic_ready_for_trade_date,
)


STOCK_MINS_RAW_SENSOR_JOB_NAME = "stock_mins_raw_update_from_prod_job"
STOCK_MINS_RAW_RUN_START = time(19, 30)
STOCK_MINS_RAW_SOURCE = "prod_db"


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _has_materialized_check_problem(status: DatasetReadinessStatus) -> bool:
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: DatasetReadinessStatus | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
    blocked_fallback: int = 0,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not selected_trade_date:
        if raw_status is not None and not raw_status.ready:
            blocked_count = len(
                [asset_status for asset_status in raw_status.statuses if not asset_status.ready]
            )
        elif stock_basic_status is not None and not stock_basic_status.ready:
            blocked_count = 1
        else:
            blocked_count = blocked_fallback

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source": STOCK_MINS_RAW_SOURCE,
            "job_name": STOCK_MINS_RAW_SENSOR_JOB_NAME,
            "source_window_started": source_window_started,
            "stock_basic_freshness_required": True,
            "raw_status": status_payload(raw_status) if raw_status else None,
            "stock_basic_status": (
                status_payload(stock_basic_status) if stock_basic_status else None
            ),
        },
    )


def _run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="stock_mins_raw_update_from_prod",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


@dg.sensor(
    job_name=STOCK_MINS_RAW_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票分钟线交易日分区和基础信息 freshness/checks 就绪后，触发五频度 prod DB raw 更新任务。",
)
def stock_mins_raw_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_MINS_RAW_RUN_START
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        reason = "没有注册股票分钟线交易日分区，无法触发 raw 更新。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "股票分钟线 raw 日常更新窗口尚未到 19:30，暂不触发。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_stk_mins_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if raw_status.ready:
        reason = "最新股票分钟线交易日的五频度 raw 分区已经生成完成并通过 blocking checks。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if _has_materialized_check_problem(raw_status):
        reason = (
            "最新股票分钟线交易日的 raw 分区已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_basic_status = stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not stock_basic_status.ready:
        reason = "股票基础信息尚未满足目标交易日 freshness 和 blocking checks 门禁。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            stock_basic_status=stock_basic_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票分钟线 raw 门禁已满足，提交五频度 prod DB raw 更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        raw_status=raw_status,
        stock_basic_status=stock_basic_status,
    )
    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )
