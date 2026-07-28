"""Bounded phase sensors for international-index Raw updates."""

from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.jobs.index_global import raw_index_global_update_job
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_REPLAY_SLOT_LIMIT,
    build_index_global_phase_slots,
    build_index_global_raw_run_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


SENSOR_NAME = "raw_index_global_update_job_sensor"
JOB_NAME = "raw_index_global_update_job"


def _skip(code: str, detail: str) -> dg.SkipReason:
    return dg.SkipReason(f"{code}: {detail}")


def _slot_key(trade_date: str, probe_phase: str) -> str:
    return f"{trade_date}:{probe_phase}"


def _cursor(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision,
    target_date: str | None,
    selected_count: int,
    blocked_count: int,
    reason_code: str,
    summary: str,
    next_action: str,
    runtime_state: dict[str, object],
    sample_keys: tuple[str, ...] = (),
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=selected_count,
        blocked_count=blocked_count,
        sample_keys=sample_keys,
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=JOB_NAME,
            asset_family="index_global_raw",
            partition_set=cn_global_index_trade_days.name,
            reason_code=reason_code,
            blocked_component="none",
            summary=summary,
            next_action=next_action,
            frontier={
                "due_slot_count": selected_count + blocked_count,
                "replay_slot_limit": GLOBAL_INDEX_REPLAY_SLOT_LIMIT,
            },
            evidence={"event_history_reads": 0, "source_requests": 0},
            runtime_state=runtime_state,
        ),
    )


def _next_due_slot(
    slots: tuple[tuple[str, str, datetime], ...],
    *,
    last_dispatched_slot: str | None,
) -> tuple[tuple[str, str, datetime] | None, str | None]:
    if not slots:
        return None, "no_due_slots"
    if not last_dispatched_slot:
        return slots[0], None
    keys = tuple(_slot_key(trade_date, phase) for trade_date, phase, _ in slots)
    if last_dispatched_slot in keys:
        index = keys.index(last_dispatched_slot) + 1
        return (slots[index], None) if index < len(slots) else (None, "all_slots_dispatched")
    last_date = last_dispatched_slot.split(":", 1)[0]
    earliest_date = slots[0][0]
    if last_date < earliest_date:
        return None, "replay_backlog_exceeded"
    later_slots = tuple(slot for slot in slots if slot[0] > last_date)
    return (later_slots[0], None) if later_slots else (None, "all_slots_dispatched")


def evaluate_index_global_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> dg.SensorResult:
    slots = build_index_global_phase_slots(evaluated_at)
    if len(slots) > GLOBAL_INDEX_REPLAY_SLOT_LIMIT:
        cursor = _cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_date=None,
            selected_count=0,
            blocked_count=len(slots),
            reason_code="replay_backlog_exceeded",
            summary="due phase slots exceed the bounded replay limit",
            next_action="wait for manual backlog review",
            runtime_state={},
        )
        return dg.SensorResult(skip_reason=_skip("replay_backlog_exceeded", "slot limit exceeded"), cursor=cursor)

    payload = load_sensor_cursor(context.cursor)
    details = sensor_cursor_details(payload)
    state = cursor_runtime_state(details)
    last_slot = state.get("last_dispatched_slot")
    last_slot = str(last_slot) if last_slot else None
    candidate, reason = _next_due_slot(slots, last_dispatched_slot=last_slot)
    if candidate is None:
        reason = reason or "all_slots_dispatched"
        cursor = _cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_date=None,
            selected_count=0,
            blocked_count=0,
            reason_code=reason,
            summary="no due international-index phase requires a new run",
            next_action="wait for the next phase window",
            runtime_state={"last_dispatched_slot": last_slot} if last_slot else {},
        )
        return dg.SensorResult(skip_reason=_skip(reason, "no dispatchable phase slot"), cursor=cursor)

    trade_date, probe_phase, _due_at = candidate
    registered = set(context.instance.get_dynamic_partitions(cn_global_index_trade_days.name))
    if trade_date not in registered:
        cursor = _cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_date=trade_date,
            selected_count=0,
            blocked_count=1,
            reason_code="partition_not_registered",
            summary="the due phase target partition is not registered",
            next_action="wait for the dedicated natural-day partition sensor",
            runtime_state={"last_dispatched_slot": last_slot} if last_slot else {},
            sample_keys=(_slot_key(trade_date, probe_phase),),
        )
        return dg.SensorResult(skip_reason=_skip("partition_not_registered", trade_date), cursor=cursor)

    slot_key = _slot_key(trade_date, probe_phase)
    run_config = build_index_global_raw_run_config(
        trade_date=trade_date,
        probe_phase=probe_phase,
        slot_key=slot_key,
    )
    cursor = _cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_date=trade_date,
        selected_count=1,
        blocked_count=max(0, len(slots) - 1),
        reason_code="dispatch_due_phase",
        summary=f"dispatch one bounded {probe_phase} phase",
        next_action="wait for the phase run result or bounded retry sensor",
        runtime_state={"last_dispatched_slot": slot_key, "replay_slot_count": len(slots)},
        sample_keys=(slot_key,),
    )
    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject="index_global_update",
                    unit_id=slot_key,
                ),
                partition_key=trade_date,
                run_config=run_config,
            )
        ],
        cursor=cursor,
    )


@dg.sensor(
    job=raw_index_global_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=60,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="按北京时间五阶段、有界回看和单分区 RunRequest 探测国际指数 Raw。",
)
def raw_index_global_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_index_global_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
    )


__all__ = ["evaluate_index_global_sensor", "raw_index_global_update_job_sensor"]
