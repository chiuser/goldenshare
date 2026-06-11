from dataclasses import dataclass
from datetime import datetime, time

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
    source_window_started: bool,
    reason: str,
    stock_basic_status: AssetReadinessStatus | None = None,
    namechange_status: AssetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    identity_map_current: bool | None = None,
) -> str:
    details: dict[str, object] = {
        "source_window_started": source_window_started,
        "reason": reason,
        "identity_map_current": identity_map_current,
    }
    if stock_basic_status is not None:
        details["stock_basic_status"] = _status_payload(stock_basic_status)
    if namechange_status is not None:
        details["namechange_status"] = _status_payload(namechange_status)
    if identity_map_status is not None:
        details["identity_map_status"] = _status_payload(identity_map_status)
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
        details=details,
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
