"""Shared bounded evaluator for canonical CN A-share Gold minute sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_date_readiness,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

BatchReadinessLoader = Callable[..., ContinuityBatchReadiness]


@dataclass(frozen=True, slots=True)
class CanonicalGoldMinuteSensorSpec:
    sensor_name: str
    job_name: str
    asset_family: str
    min_trade_date: str
    partition_set_name: str
    silver_readiness_loader: BatchReadinessLoader
    gold_readiness_loader: BatchReadinessLoader


def _cursor(
    *,
    spec: CanonicalGoldMinuteSensorSpec,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    target_date: str | None,
    reason_code: str,
    gap_status=None,
    source_batch: ContinuityBatchReadiness | None = None,
    gold_batch: ContinuityBatchReadiness | None = None,
    selected_status=None,
) -> str:
    selected = target_date if decision is SensorCursorDecision.REQUEST_RUNS else None
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=1 if selected else 0,
        blocked_count=0 if selected else (1 if target_date else 0),
        sample_keys=(selected,) if selected else (),
        details=build_cursor_details(
            sensor_name=spec.sensor_name,
            job_name=spec.job_name,
            asset_family=spec.asset_family,
            partition_set=spec.partition_set_name,
            reason_code=reason_code,
            blocked_component="none" if selected else reason_code,
            summary=f"{spec.asset_family} Gold sensor decision: {reason_code}",
            next_action=(
                "run the single-partition Gold job"
                if selected
                else "wait for the blocking condition to clear"
            ),
            frontier={
                "continuity": compact_continuity_frontier(
                    gap_status, selected_trade_date=selected
                ),
                "silver": compact_batch_frontier(
                    source_batch, selected_trade_date=selected
                ),
                "gold": compact_batch_frontier(
                    gold_batch, selected_trade_date=selected
                ),
            },
            gate_statuses={"gold": compact_date_readiness(selected_status)},
            evidence={"window_limit": 10, "max_run_requests_per_tick": 1},
            performance_ms={
                "silver_batch": source_batch.elapsed_ms if source_batch else None,
                "gold_batch": gold_batch.elapsed_ms if gold_batch else None,
            },
        ),
    )


def evaluate_canonical_gold_minute_sensor(
    context: dg.SensorEvaluationContext,
    *,
    spec: CanonicalGoldMinuteSensorSpec,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    try:
        context.resources.lake_root.ensure_available_for_run()
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            expected_window = load_expected_trade_date_window(
                connection,
                silver_trade_calendar_path(context.resources.lake_root.root()),
                evaluated_at=evaluated_at,
                min_trade_date=spec.min_trade_date,
                same_day_register_start=None,
                window_limit=10,
            )
            registered = tuple(
                sorted(context.instance.get_dynamic_partitions(spec.partition_set_name))
            )
            gap_status = build_registered_gap_status(
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_dates=registered,
            )
            if not gap_status.ready:
                target = gap_status.first_missing_registered_date
                return dg.SensorResult(
                    skip_reason="Gold 分钟线等待专属交易日分区注册。",
                    cursor=_cursor(
                        spec=spec,
                        evaluated_at=evaluated_at,
                        decision=SensorCursorDecision.SKIP,
                        target_date=target,
                        reason_code="missing_registered_partition",
                        gap_status=gap_status,
                    ),
                )
            source_batch = spec.silver_readiness_loader(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            gold_batch = spec.gold_readiness_loader(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )

        selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=gold_batch,
        )
        target = selection.first_not_ready_trade_date
        if selection.selected_trade_date is None:
            reason_code = (
                "materialized_check_failed"
                if selection.blocked_reason == "materialized_check_failed"
                else "all_ready"
            )
            return dg.SensorResult(
                skip_reason=(
                    "Gold 分钟线已有文件但核心语义失败，拒绝自动覆盖。"
                    if reason_code == "materialized_check_failed"
                    else "最近 10 个 Gold 分钟线交易日均已 ready。"
                ),
                cursor=_cursor(
                    spec=spec,
                    evaluated_at=evaluated_at,
                    decision=SensorCursorDecision.SKIP,
                    target_date=target,
                    reason_code=reason_code,
                    gap_status=gap_status,
                    source_batch=source_batch,
                    gold_batch=gold_batch,
                    selected_status=selection.selected_status,
                ),
            )
        target = selection.selected_trade_date
        source_status = source_batch.status_for_trade_date(target)
        if not source_status.ready:
            return dg.SensorResult(
                skip_reason="同日 Silver 七频尚未全部 ready，暂不生成 Gold。",
                cursor=_cursor(
                    spec=spec,
                    evaluated_at=evaluated_at,
                    decision=SensorCursorDecision.SKIP,
                    target_date=target,
                    reason_code="silver_not_ready",
                    gap_status=gap_status,
                    source_batch=source_batch,
                    gold_batch=gold_batch,
                    selected_status=selection.selected_status,
                ),
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=spec.job_name.removesuffix("_job"),
                        unit_id=target,
                    ),
                    partition_key=target,
                )
            ],
            cursor=_cursor(
                spec=spec,
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.REQUEST_RUNS,
                target_date=target,
                reason_code="request_run",
                gap_status=gap_status,
                source_batch=source_batch,
                gold_batch=gold_batch,
                selected_status=selection.selected_status,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor must fail closed.
        return dg.SensorResult(
            skip_reason="Gold 分钟线 sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                spec=spec,
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                target_date=None,
                reason_code=f"sensor_error_{type(error).__name__}",
            ),
        )


__all__ = [
    "CanonicalGoldMinuteSensorSpec",
    "evaluate_canonical_gold_minute_sensor",
]
