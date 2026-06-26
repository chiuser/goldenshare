from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_gate_statuses,
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
    silver_namechange_ready_for_trade_date,
    silver_stock_basic_ready_for_trade_date,
    silver_stock_identity_map_ready_for_trade_date,
)


STOCK_IDENTITY_MAP_RUN_START = time(17, 30)


@dataclass(frozen=True)
class StockIdentityMapSensorDecision:
    request_run: bool
    reason: str
    identity_map_current: bool


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _source_window_started(evaluated_at: datetime) -> bool:
    return evaluated_at.time() >= STOCK_IDENTITY_MAP_RUN_START


def _identity_map_decision(
    *,
    target_trade_date: str,
    stock_basic_status: AssetReadinessStatus,
    namechange_status: AssetReadinessStatus,
    identity_map_status: AssetReadinessStatus,
) -> StockIdentityMapSensorDecision:
    if not stock_basic_status.ready:
        return StockIdentityMapSensorDecision(
            request_run=False,
            reason=f"股票基础信息未 ready：{stock_basic_status.reason}",
            identity_map_current=False,
        )
    if not namechange_status.ready:
        return StockIdentityMapSensorDecision(
            request_run=False,
            reason=f"股票曾用名未 ready：{namechange_status.reason}",
            identity_map_current=False,
        )

    upstream_storage_ids = [
        storage_id
        for storage_id in (
            stock_basic_status.materialization_storage_id,
            namechange_status.materialization_storage_id,
        )
        if storage_id is not None
    ]
    upstream_latest_storage_id = max(upstream_storage_ids) if upstream_storage_ids else None
    identity_storage_id = identity_map_status.materialization_storage_id
    identity_fresh_enough = identity_map_status.freshness_passed
    identity_after_upstreams = (
        upstream_latest_storage_id is None
        or (
            identity_storage_id is not None
            and identity_storage_id >= upstream_latest_storage_id
        )
    )
    identity_map_current = (
        identity_map_status.ready and identity_fresh_enough and identity_after_upstreams
    )
    if identity_map_current:
        return StockIdentityMapSensorDecision(
            request_run=False,
            reason="股票身份映射已经跟上最新基础事实，无需重建。",
            identity_map_current=True,
        )

    if (
        identity_map_status.materialized
        and identity_fresh_enough
        and identity_after_upstreams
        and not identity_map_status.checks_passed
    ):
        return StockIdentityMapSensorDecision(
            request_run=False,
            reason=(
                "股票身份映射已生成但 blocking checks 未全绿，需要人工检查后重跑，"
                "sensor 不自动循环提交。"
            ),
            identity_map_current=False,
        )

    return StockIdentityMapSensorDecision(
        request_run=True,
        reason=f"股票身份映射需要按 {target_trade_date} 最新基础事实重建。",
        identity_map_current=False,
    )


def _cursor_payload(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    target_trade_date: str | None,
    source_window_started: bool,
    registered_trade_day_count: int,
    reason: str,
    stock_basic_status: AssetReadinessStatus | None = None,
    namechange_status: AssetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    identity_map_current: bool | None = None,
) -> str:
    reason_code = None
    blocked_component = "none"
    if decision == SensorCursorDecision.REQUEST_RUNS:
        reason_code = "request_run"
    else:
        for component, status in (
            ("silver_stock_basic", stock_basic_status),
            ("silver_namechange", namechange_status),
            ("silver_stock_identity_map", identity_map_status),
        ):
            if status is not None and not status.ready:
                reason_code = status.reason
                blocked_component = component
                break
    if reason_code is None:
        if target_trade_date is None:
            reason_code = "no_registered_trade_day"
            blocked_component = cn_a_stock_trade_days.name
        elif not source_window_started:
            reason_code = "run_window_not_started"
            blocked_component = "stock_identity_map_update_window"
        elif identity_map_current:
            reason_code = "identity_map_current"
        else:
            reason_code = "skip"
    if decision == SensorCursorDecision.REQUEST_RUNS:
        next_action = "等待本次 stock_identity_map 更新 run 完成，然后看 blocking checks。"
    elif blocked_component == cn_a_stock_trade_days.name:
        next_action = "先注册股票交易日分区，再等待下一次 sensor tick。"
    elif blocked_component == "stock_identity_map_update_window":
        next_action = "等待 17:30 之后再检查上游 readiness。"
    elif blocked_component == "silver_stock_basic":
        next_action = "先修复 silver_stock_basic readiness，再等待下一次 sensor tick。"
    elif blocked_component == "silver_namechange":
        next_action = "先修复 silver_namechange readiness，再等待下一次 sensor tick。"
    elif blocked_component == "silver_stock_identity_map":
        next_action = "先人工检查 silver_stock_identity_map blocking checks，sensor 不自动循环重跑。"
    else:
        next_action = "无需处理，股票身份映射已跟上最新基础事实。"
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if decision == SensorCursorDecision.REQUEST_RUNS else 0,
        blocked_count=0 if decision == SensorCursorDecision.REQUEST_RUNS else 1,
        sample_keys=(
            (target_trade_date,)
            if decision == SensorCursorDecision.REQUEST_RUNS and target_trade_date
            else ()
        ),
        details=build_cursor_details(
            sensor_name="stock_identity_map_sensor",
            job_name="stock_identity_map_update_job",
            asset_family="stock_identity_map",
            partition_set=cn_a_stock_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=reason,
            next_action=(
                "等待本次 run 完成。"
                if decision == SensorCursorDecision.REQUEST_RUNS
                else "按阻断组件修复或等待下一次 sensor tick。"
            ),
            gate_statuses=compact_gate_statuses(
                {
                    "silver_stock_basic": stock_basic_status,
                    "silver_namechange": namechange_status,
                    "silver_stock_identity_map": identity_map_status,
                }
            ),
            evidence={
                "registered_trade_day_count": registered_trade_day_count,
                "target_trade_date": target_trade_date,
                "source_window_started": source_window_started,
                "identity_map_current": identity_map_current,
            },
        ),
    )


@dg.sensor(
    job_name="stock_identity_map_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票身份映射在交易日 17:30 后等待基础事实 ready 后重建。",
)
def stock_identity_map_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = _source_window_started(evaluated_at)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    target_trade_date = _latest_registered_trade_date(
        registered_trade_days,
        evaluated_at,
    )

    if target_trade_date is None:
        reason = "没有已注册股票交易日分区，无法判断股票身份映射是否需要重建。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                target_trade_date=None,
                source_window_started=source_window_started,
                registered_trade_day_count=len(registered_trade_days),
                reason=reason,
            ),
        )

    if not source_window_started:
        reason = "股票身份映射日常更新窗口尚未到 17:30，暂不检查上游、不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                target_trade_date=target_trade_date,
                source_window_started=source_window_started,
                registered_trade_day_count=len(registered_trade_days),
                reason=reason,
            ),
        )

    stock_basic_status = silver_stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    namechange_status = silver_namechange_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    identity_map_status = silver_stock_identity_map_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    identity_decision = _identity_map_decision(
        target_trade_date=target_trade_date,
        stock_basic_status=stock_basic_status,
        namechange_status=namechange_status,
        identity_map_status=identity_map_status,
    )
    cursor_decision = (
        SensorCursorDecision.REQUEST_RUNS
        if identity_decision.request_run
        else SensorCursorDecision.SKIP
    )
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_trade_date=target_trade_date,
        source_window_started=source_window_started,
        registered_trade_day_count=len(registered_trade_days),
        reason=identity_decision.reason,
        stock_basic_status=stock_basic_status,
        namechange_status=namechange_status,
        identity_map_status=identity_map_status,
        identity_map_current=identity_decision.identity_map_current,
    )

    if not identity_decision.request_run:
        return dg.SensorResult(skip_reason=identity_decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject="stock_identity_map",
                    unit_id=target_trade_date,
                )
            )
        ],
        cursor=cursor,
    )
