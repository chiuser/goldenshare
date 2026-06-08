from __future__ import annotations

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
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    raw_tushare_namechange_ready_for_trade_date,
    silver_namechange_ready_for_trade_date,
    status_payload,
    stock_basic_ready_for_trade_date,
)


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


def _asset_status_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def _raw_cursor_payload(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    already_submitted_for_trade_date: bool,
    raw_status: AssetReadinessStatus | None = None,
) -> str:
    details: dict[str, object] = {
        "registered_trade_day_count": registered_trade_day_count,
        "selected_trade_date": selected_trade_date,
        "reason": reason,
        "source_window_started": source_window_started,
        "already_submitted_for_trade_date": already_submitted_for_trade_date,
    }
    if raw_status is not None:
        details["readiness_details"] = {
            "raw_tushare_namechange": _asset_status_payload(raw_status)
        }
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details=details,
    )


def _silver_cursor_payload(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: AssetReadinessStatus | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
    silver_status: AssetReadinessStatus | None = None,
) -> str:
    readiness_details: dict[str, object] = {}
    if raw_status is not None:
        readiness_details["raw_tushare_namechange"] = _asset_status_payload(raw_status)
    if stock_basic_status is not None:
        readiness_details["stock_basic"] = status_payload(stock_basic_status)
    if silver_status is not None:
        readiness_details["silver_namechange"] = _asset_status_payload(silver_status)

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source_window_started": source_window_started,
            "readiness_details": readiness_details,
        },
    )


def _submit_when_missing_or_stale(status: AssetReadinessStatus) -> bool:
    if not status.materialized:
        return True
    if not status.checks_passed:
        return False
    return not status.freshness_passed


def _raw_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(run_key=f"raw_namechange_update:{trade_date}")


def _silver_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(run_key=f"silver_namechange_update:{trade_date}")


@dg.sensor(
    job_name="raw_namechange_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票曾用名 raw full snapshot 缺失或过期时，触发 raw 更新任务。",
)
def raw_namechange_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
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
        reason = "没有注册股票当前交易日分区，无法触发股票曾用名 raw 更新。"
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "股票曾用名日常更新窗口尚未到 09:30，暂不触发 raw 更新。"
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_tushare_namechange_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if raw_status.ready:
        reason = "股票曾用名 raw 已满足最新当前交易日 freshness 与 checks。"
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if raw_status.materialized and not raw_status.checks_passed:
        reason = (
            "股票曾用名 raw 已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    cursor_details = sensor_cursor_details(load_sensor_cursor(context.cursor))
    already_submitted = (
        cursor_details.get("selected_trade_date") == target_trade_date
        and cursor_details.get("already_submitted_for_trade_date") is True
    )
    if already_submitted:
        reason = "最新股票当前交易日已经提交过股票曾用名 raw 更新 run，失败时请人工 retry。"
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=True,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not _submit_when_missing_or_stale(raw_status):
        reason = f"股票曾用名 raw 暂不自动触发：{raw_status.reason}"
        cursor = _raw_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            already_submitted_for_trade_date=False,
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票曾用名 raw 缺失或 freshness 不满足，提交 raw full snapshot 更新。"
    cursor = _raw_cursor_payload(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        already_submitted_for_trade_date=True,
        raw_status=raw_status,
    )
    return dg.SensorResult(
        run_requests=[_raw_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )


@dg.sensor(
    job_name="silver_namechange_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票曾用名 raw 与 stock_basic ready 后，触发 silver 更新任务。",
)
def silver_namechange_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
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
        reason = "没有注册股票当前交易日分区，无法触发股票曾用名 silver 更新。"
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "股票曾用名日常更新窗口尚未到 09:30，暂不触发 silver 更新。"
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    silver_status = silver_namechange_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if silver_status.ready:
        reason = "股票曾用名 silver 已满足最新当前交易日 freshness 与 checks。"
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if silver_status.materialized and not silver_status.checks_passed:
        reason = (
            "股票曾用名 silver 已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_tushare_namechange_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not raw_status.ready:
        reason = "股票曾用名 silver 等待 raw readiness 门禁满足。"
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_basic_status = stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not stock_basic_status.ready:
        reason = "股票曾用名 silver 等待 stock_basic raw+silver final ready。"
        cursor = _silver_cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            stock_basic_status=stock_basic_status,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票曾用名 raw 与 stock_basic 均 ready，提交 silver full snapshot 更新。"
    cursor = _silver_cursor_payload(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        raw_status=raw_status,
        stock_basic_status=stock_basic_status,
        silver_status=silver_status,
    )
    return dg.SensorResult(
        run_requests=[_silver_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )
