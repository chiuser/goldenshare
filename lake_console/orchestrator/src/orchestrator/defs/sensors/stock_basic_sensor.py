from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_trade_days
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
    AssetReadinessStatus,
    raw_tushare_stock_basic_ready_for_trade_date,
    silver_stock_basic_ready_for_trade_date,
)


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _status_payload(status: AssetReadinessStatus) -> dict[str, object]:
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


def _cursor_payload(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    registered_trade_day_count: int,
    raw_status: AssetReadinessStatus | None = None,
    silver_status: AssetReadinessStatus | None = None,
) -> str:
    details: dict[str, object] = {
        "registered_trade_day_count": registered_trade_day_count,
        "selected_trade_date": selected_trade_date,
        "reason": reason,
    }
    readiness_details: dict[str, object] = {}
    if raw_status is not None:
        readiness_details["raw_tushare_stock_basic"] = _status_payload(raw_status)
    if silver_status is not None:
        readiness_details["silver_stock_basic"] = _status_payload(silver_status)
    if readiness_details:
        details["readiness_details"] = readiness_details

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


def _submit_when_missing_or_stale(status: AssetReadinessStatus) -> bool:
    if not status.materialized:
        return True
    if not status.checks_passed:
        return False
    return not status.freshness_passed


def _raw_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_stock_basic_update",
            unit_id=trade_date,
        )
    )


def _silver_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_stock_basic_update",
            unit_id=trade_date,
        )
    )


@dg.sensor(
    job_name="raw_stock_basic_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票基础信息 raw full snapshot 缺失或过期时，触发 raw 更新任务。",
)
def raw_stock_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    target_trade_date = _latest_registered_trade_date(
        registered_trade_days,
        evaluated_at,
    )

    if target_trade_date is None:
        reason = "当前还没有已注册交易日分区，暂不触发股票基础信息 raw 日更快照。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_tushare_stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if raw_status.ready:
        reason = "股票基础信息 raw 已满足最新已注册交易日 freshness 与 checks。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if raw_status.materialized and not raw_status.checks_passed:
        reason = (
            "股票基础信息 raw 已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not _submit_when_missing_or_stale(raw_status):
        reason = f"股票基础信息 raw 暂不自动触发：{raw_status.reason}"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            raw_status=raw_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票基础信息 raw 缺失或 freshness 不满足，提交 raw full snapshot 更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        registered_trade_day_count=len(registered_trade_days),
        raw_status=raw_status,
    )
    return dg.SensorResult(
        run_requests=[_raw_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )


@dg.sensor(
    job_name="silver_stock_basic_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票基础信息 raw ready 后，触发 silver full snapshot 更新任务。",
)
def silver_stock_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    target_trade_date = _latest_registered_trade_date(
        registered_trade_days,
        evaluated_at,
    )

    if target_trade_date is None:
        reason = "当前还没有已注册交易日分区，暂不触发股票基础信息 silver 日更快照。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=None,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    silver_status = silver_stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if silver_status.ready:
        reason = "股票基础信息 silver 已满足最新已注册交易日 freshness 与 checks。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if silver_status.materialized and not silver_status.checks_passed:
        reason = (
            "股票基础信息 silver 已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    raw_status = raw_tushare_stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not raw_status.ready:
        reason = "股票基础信息 silver 等待 raw readiness 门禁满足。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            registered_trade_day_count=len(registered_trade_days),
            raw_status=raw_status,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票基础信息 raw ready 且 silver 缺失或过期，提交 silver full snapshot 更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason=reason,
        registered_trade_day_count=len(registered_trade_days),
        raw_status=raw_status,
        silver_status=silver_status,
    )
    return dg.SensorResult(
        run_requests=[_silver_run_request_for_trade_date(target_trade_date)],
        cursor=cursor,
    )
