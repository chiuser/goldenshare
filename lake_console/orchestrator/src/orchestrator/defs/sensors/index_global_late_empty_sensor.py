"""Bounded follow-up probes for natural days whose global Raw stayed empty."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.jobs.index_global import raw_index_global_update_job
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import raw_index_global_path
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details, cursor_runtime_state
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_LATE_EMPTY_DATE_LIMIT,
    GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT,
    build_index_global_phase_slots,
    build_index_global_raw_run_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_repair_attempt_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


SENSOR_NAME = "raw_index_global_late_empty_sensor"
JOB_NAME = "raw_index_global_update_job"


def _skip(code: str, detail: str) -> dg.SkipReason:
    return dg.SkipReason(f"{code}: {detail}")


def _eligible_dates(evaluated_at: datetime) -> tuple[str, ...]:
    slots = build_index_global_phase_slots(evaluated_at)
    dates = {trade_date for trade_date, phase, _ in slots if phase == "americas"}
    return tuple(sorted(dates, reverse=True)[:GLOBAL_INDEX_LATE_EMPTY_DATE_LIMIT])


def _empty_existing_dates(
    connection,
    *,
    paths_by_date: dict[str, Path],
) -> set[str]:
    if not paths_by_date:
        return set()
    statements: list[str] = []
    params: list[object] = []
    for trade_date, path in paths_by_date.items():
        statements.append(
            "SELECT ? AS trade_date, count(*) AS row_count "
            f"FROM {read_parquet(path, hive_partitioning=False)}"
        )
        params.extend([trade_date])
    rows = connection.execute(" UNION ALL ".join(statements), params).fetchall()
    return {str(trade_date) for trade_date, row_count in rows if int(row_count or 0) == 0}


def evaluate_index_global_late_empty_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> dg.SensorResult:
    eligible_dates = _eligible_dates(evaluated_at.astimezone(CN_A_SENSOR_TIMEZONE))
    registered = set(context.instance.get_dynamic_partitions(cn_global_index_trade_days.name))
    unregistered = tuple(date_key for date_key in eligible_dates if date_key not in registered)
    if unregistered:
        return dg.SensorResult(
            skip_reason=_skip("partition_not_registered", unregistered[0]),
            cursor=build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                target_date=unregistered[0],
                selected_count=0,
                blocked_count=len(unregistered),
                sample_keys=unregistered[:3],
                details=build_cursor_details(
                    sensor_name=SENSOR_NAME,
                    job_name=JOB_NAME,
                    asset_family="index_global_raw",
                    partition_set=cn_global_index_trade_days.name,
                    reason_code="partition_not_registered",
                    blocked_component="none",
                    summary="late-empty candidates include unregistered partitions",
                    next_action="wait for natural-day partition registration",
                    frontier={"eligible_date_count": len(eligible_dates)},
                    evidence={"event_history_reads": 0},
                ),
            ),
        )
    paths = {
        trade_date: raw_index_global_path(context.resources.lake_root.root(), trade_date)
        for trade_date in eligible_dates
    }
    existing_paths = {date_key: path for date_key, path in paths.items() if path.exists()}
    payload = load_sensor_cursor(context.cursor)
    previous_details = sensor_cursor_details(payload)
    previous_state = cursor_runtime_state(previous_details)
    raw_attempts = previous_state.get("late_empty_attempts", {})
    attempts = {
        str(key): int(value)
        for key, value in raw_attempts.items()
        if str(key) in eligible_dates
    } if isinstance(raw_attempts, dict) else {}

    if existing_paths:
        context.resources.lake_root.ensure_available_for_run()
        duckdb_resource: DuckDBResource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            empty_dates = _empty_existing_dates(connection, paths_by_date=existing_paths)
    else:
        empty_dates = set()

    candidates = tuple(sorted(empty_dates))
    exhausted = tuple(
        trade_date
        for trade_date in candidates
        if attempts.get(trade_date, 0) >= GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT
    )
    selected = next(
        (
            trade_date
            for trade_date in candidates
            if attempts.get(trade_date, 0) < GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT
        ),
        None,
    )
    runtime_state = {
        "late_empty_attempts": {
            trade_date: attempts.get(trade_date, 0)
            for trade_date in candidates
        },
        "eligible_date_count": len(eligible_dates),
    }
    if selected is None:
        reason = "late_empty_exhausted" if exhausted else "no_late_empty_candidate"
        cursor = build_sensor_cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            target_date=None,
            selected_count=0,
            blocked_count=len(exhausted),
            sample_keys=exhausted[:3],
            details=build_cursor_details(
                sensor_name=SENSOR_NAME,
                job_name=JOB_NAME,
                asset_family="index_global_raw",
                partition_set=cn_global_index_trade_days.name,
                reason_code=reason,
                blocked_component="none",
                summary="no bounded late-empty re-probe is available",
                next_action="wait for a later scheduled tick or manual review",
                frontier={"eligible_date_count": len(eligible_dates)},
                evidence={"duckdb_scan_files": len(existing_paths), "event_history_reads": 0},
                runtime_state=runtime_state,
            ),
        )
        return dg.SensorResult(skip_reason=_skip(reason, "no retryable empty date"), cursor=cursor)

    next_attempt = attempts.get(selected, 0) + 1
    run_config = build_index_global_raw_run_config(
        trade_date=selected,
        probe_phase="late_empty",
        slot_key=f"{selected}:late_empty",
        late_empty_attempt=next_attempt,
    )
    runtime_state["late_empty_attempts"][selected] = next_attempt  # type: ignore[index]
    cursor = build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_date=selected,
        selected_count=1,
        blocked_count=len(candidates) - 1,
        sample_keys=(f"{selected}:late_empty:{next_attempt}",),
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=JOB_NAME,
            asset_family="index_global_raw",
            partition_set=cn_global_index_trade_days.name,
            reason_code="late_empty_retry",
            blocked_component="none",
            summary=f"re-probe one bounded empty Raw date (attempt {next_attempt})",
            next_action="wait for the late-empty run result",
            frontier={"eligible_date_count": len(eligible_dates)},
            evidence={"duckdb_scan_files": len(existing_paths), "event_history_reads": 0},
            runtime_state=runtime_state,
        ),
    )
    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_repair_attempt_run_key(
                    subject="index_global_update",
                    repair_scope_id=selected,
                    attempt=next_attempt,
                    attempt_scope="late_empty",
                ),
                partition_key=selected,
                run_config=run_config,
            )
        ],
        cursor=cursor,
    )


@dg.sensor(
    job=raw_index_global_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="对 Americas 之后仍为空的最近三个自然日做最多两次有界 late-empty 探测。",
)
def raw_index_global_late_empty_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_index_global_late_empty_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
    )


__all__ = ["evaluate_index_global_late_empty_sensor", "raw_index_global_late_empty_sensor"]
