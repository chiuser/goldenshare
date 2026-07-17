"""Stopped-by-default bounded sensor for local board technical serving."""

from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.dc_daily_technical_clickhouse_readiness import (
    batch_ch_dc_daily_technical_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_daily_technical_lake_readiness import (
    batch_gold_dc_daily_technical_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_date_readiness,
)
from orchestrator.defs.run_contracts.cursors import SensorCursorDecision, build_sensor_cursor
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_HISTORY_START_DATE,
    DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT,
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


JOB_NAME = "ch_dc_daily_technical_update_job"
SENSOR_NAME = "ch_dc_daily_technical_update_job_sensor"


def _cursor(
    *,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    gold_batch: ContinuityBatchReadiness | None,
    serving_batch: ContinuityBatchReadiness | None,
    gold_status: object | None,
    serving_status: object | None,
    selected_trade_date: str | None,
    target_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else (1 if target_date else 0),
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=JOB_NAME,
            asset_family="ch_dc_daily_technical",
            partition_set=cn_a_dc_daily_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": (
                    compact_continuity_frontier(
                        gap_status,
                        selected_trade_date=selected_trade_date,
                    )
                    if gap_status is not None
                    else None
                ),
                "gold": compact_batch_frontier(
                    gold_batch,
                    selected_trade_date=selected_trade_date,
                ),
                "serving": compact_batch_frontier(
                    serving_batch,
                    selected_trade_date=selected_trade_date,
                ),
            },
            gate_statuses={
                "gold": compact_date_readiness(gold_status),
                "serving": compact_date_readiness(serving_status),
            },
            evidence={
                "expected_count": (
                    len(expected_window.expected_trade_dates)
                    if expected_window is not None
                    else 0
                ),
                "registered_count": (
                    len(gap_status.registered_trade_dates)
                    if gap_status is not None
                    else 0
                ),
                "max_run_requests_per_tick": 1,
                "event_history_reads": 0,
            },
            performance_ms={
                "gold_batch_elapsed_ms": gold_batch.elapsed_ms if gold_batch else None,
                "serving_batch_elapsed_ms": (
                    serving_batch.elapsed_ms if serving_batch else None
                ),
            },
        ),
    )


def _load_window(
    context: dg.SensorEvaluationContext,
    *,
    connection,
    evaluated_at: datetime,
) -> tuple[
    ContinuityExpectedDateWindow,
    tuple[str, ...],
    ContinuityRegisteredGapStatus,
]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    expected_window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=DC_DAILY_TECHNICAL_HISTORY_START_DATE,
        same_day_register_start=None,
        window_limit=DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_dc_daily_trade_days.name))
    )
    return (
        expected_window,
        registered,
        build_registered_gap_status(
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_dates=registered,
        ),
    )


@dg.sensor(
    job_name=JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "clickhouse"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.SERVING,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="Gold 技术指标 ready 后，按最近 10 个交易日触发本机 ClickHouse serving。",
)
def ch_dc_daily_technical_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    gold_batch = None
    serving_batch = None
    expected_window = None
    gap_status = None
    try:
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
            )
            if not expected_window.expected_trade_dates:
                return dg.SensorResult(
                    skip_reason="no_expected_trade_date",
                    cursor=_cursor(
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        gold_batch=None,
                        serving_batch=None,
                        gold_status=None,
                        serving_status=None,
                        selected_trade_date=None,
                        target_date=None,
                        reason_code="no_expected_trade_date",
                        blocked_component="calendar",
                        summary="no expected board technical trade date",
                        next_action="wait for the board trade calendar",
                    ),
                )
            if not gap_status.ready:
                return dg.SensorResult(
                    skip_reason="missing_registered_partition",
                    cursor=_cursor(
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        gold_batch=None,
                        serving_batch=None,
                        gold_status=None,
                        serving_status=None,
                        selected_trade_date=None,
                        target_date=gap_status.first_missing_registered_date,
                        reason_code="missing_registered_partition",
                        blocked_component=cn_a_dc_daily_trade_days.name,
                        summary="board technical serving waits for registered partitions",
                        next_action="register the first missing board trade-date partition",
                    ),
                )

            gold_batch = batch_gold_dc_daily_technical_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            with context.resources.clickhouse.get_connection() as client:
                serving_batch = batch_ch_dc_daily_technical_lake_readiness(
                    client=client,
                    expected_trade_dates=expected_window.expected_trade_dates,
                    registered_trade_days=registered,
                )
    except Exception as error:
        return dg.SensorResult(
            skip_reason="scan_error",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                gold_batch=gold_batch,
                serving_batch=serving_batch,
                gold_status=None,
                serving_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="scan_error",
                blocked_component="calendar_or_clickhouse",
                summary="bounded local serving readiness scan failed",
                next_action=f"inspect the bounded scan error: {str(error)[:160]}",
            ),
        )

    gold_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=gold_batch,
    )
    if gold_selection.first_not_ready_trade_date is not None:
        return dg.SensorResult(
            skip_reason="gold_not_ready",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                gold_batch=gold_batch,
                serving_batch=serving_batch,
                gold_status=gold_selection.selected_status,
                serving_status=None,
                selected_trade_date=None,
                target_date=gold_selection.first_not_ready_trade_date,
                reason_code=(
                    "gold_materialized_check_failed"
                    if gold_selection.blocked_reason == "materialized_check_failed"
                    else "gold_not_ready"
                ),
                blocked_component="gold_dc_daily_technical",
                summary="Gold technical frontier blocks local ClickHouse serving",
                next_action="repair or materialize Gold before serving it",
            ),
        )

    serving_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=serving_batch,
    )
    if serving_selection.first_not_ready_trade_date is None:
        return dg.SensorResult(
            skip_reason="all_ready",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                gold_batch=gold_batch,
                serving_batch=serving_batch,
                gold_status=None,
                serving_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="all_ready",
                blocked_component="none",
                summary="recent local technical serving partitions are ready",
                next_action="wait for the next Gold technical partition",
            ),
        )
    if serving_selection.blocked_reason == "materialized_check_failed":
        return dg.SensorResult(
            skip_reason="serving_materialized_check_failed",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                gold_batch=gold_batch,
                serving_batch=serving_batch,
                gold_status=None,
                serving_status=serving_selection.selected_status,
                selected_trade_date=None,
                target_date=serving_selection.first_not_ready_trade_date,
                reason_code="serving_materialized_check_failed",
                blocked_component="ch_dc_daily_technical",
                summary="existing local serving partition failed its core check",
                next_action="inspect and repair the existing serving partition manually",
            ),
        )

    target = serving_selection.selected_trade_date
    if target is None:
        raise RuntimeError("Serving selection returned no target for a not-ready date.")
    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject=JOB_NAME.removesuffix("_job"),
                    unit_id=target,
                ),
                partition_key=target,
            )
        ],
        cursor=_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            gold_batch=gold_batch,
            serving_batch=serving_batch,
            gold_status=gold_batch.status_for_trade_date(target),
            serving_status=serving_selection.selected_status,
            selected_trade_date=target,
            target_date=target,
            reason_code="request_run",
            blocked_component="none",
            summary="Gold technical partition is ready; request local serving update",
            next_action="wait for local ClickHouse materialization and core check",
        ),
    )


__all__ = ["ch_dc_daily_technical_update_job_sensor"]
