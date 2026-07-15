"""Stopped-by-default bounded sensor for Gold board technical indicators."""

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
from orchestrator.defs.asset_guards.dc_daily_technical_lake_readiness import (
    batch_gold_dc_daily_technical_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
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


JOB_NAME = "gold_dc_daily_technical_update_job"
SENSOR_NAME = "gold_dc_daily_technical_update_job_sensor"


def _load_window(
    context: dg.SensorEvaluationContext,
    *,
    connection,
    evaluated_at: datetime,
) -> tuple[ContinuityExpectedDateWindow, tuple[str, ...], ContinuityRegisteredGapStatus]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=DC_DAILY_TECHNICAL_HISTORY_START_DATE,
        same_day_register_start=None,
        window_limit=DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    return window, registered, build_registered_gap_status(
        expected_trade_dates=window.expected_trade_dates,
        registered_trade_dates=registered,
    )


def _cursor(
    *,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    silver_batch: ContinuityBatchReadiness | None,
    gold_batch: ContinuityBatchReadiness | None,
    silver_status: object | None,
    gold_status: object | None,
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
            asset_family="dc_daily_technical",
            partition_set=cn_a_index_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": compact_continuity_frontier(
                    gap_status,
                    selected_trade_date=selected_trade_date,
                )
                if gap_status is not None
                else None,
                "silver": compact_batch_frontier(
                    silver_batch,
                    selected_trade_date=selected_trade_date,
                ),
                "gold": compact_batch_frontier(
                    gold_batch,
                    selected_trade_date=selected_trade_date,
                ),
            },
            gate_statuses={
                "silver": compact_date_readiness(silver_status),
                "gold": compact_date_readiness(gold_status),
            },
            evidence={
                "expected_count": len(expected_window.expected_trade_dates)
                if expected_window
                else 0,
                "registered_count": len(gap_status.registered_trade_dates)
                if gap_status
                else 0,
                "max_run_requests_per_tick": 1,
            },
            performance_ms={
                "silver_batch": silver_batch.elapsed_ms if silver_batch else None,
                "gold_batch": gold_batch.elapsed_ms if gold_batch else None,
            },
        ),
    )


@dg.sensor(
    job_name=JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def gold_dc_daily_technical_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    duckdb_resource = context.resources.duckdb
    try:
        with duckdb_resource.connect() as connection:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
            )
            if not gap_status.ready:
                return dg.SensorResult(
                    skip_reason="板块 Gold 指标交易日分区尚未完整注册。",
                    cursor=_cursor(
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        silver_batch=None,
                        gold_batch=None,
                        silver_status=None,
                        gold_status=None,
                        selected_trade_date=None,
                        target_date=gap_status.first_missing_registered_date,
                        reason_code="missing_registered_partition",
                        blocked_component=cn_a_index_trade_days.name,
                        summary="registered partition gap blocks Gold technical update",
                        next_action="register the first missing trade-date partition",
                    ),
                )

            silver_batch = batch_silver_dc_daily_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
                dataset="dc_daily",
            )
            gold_batch = batch_gold_dc_daily_technical_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
                source_readiness=silver_batch.statuses_by_trade_date,
            )
    except Exception as exc:
        return dg.SensorResult(
            skip_reason=str(exc),
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                silver_batch=None,
                gold_batch=None,
                silver_status=None,
                gold_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="scan_error",
                blocked_component="calendar_or_lake",
                summary="bounded Gold technical readiness scan failed",
                next_action="inspect the bounded lake scan and retry after correction",
            ),
        )

    silver_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=silver_batch,
    )
    gold_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=gold_batch,
    )
    gold_target = gold_selection.selected_trade_date
    if gold_target is None and gold_selection.first_not_ready_trade_date is None:
        return dg.SensorResult(
            skip_reason="最近 10 个 expected 日期的 Gold 技术指标均已 ready。",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                silver_batch=silver_batch,
                gold_batch=gold_batch,
                silver_status=silver_selection.selected_status,
                gold_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="all_ready",
                blocked_component="none",
                summary="recent Gold technical partitions are ready",
                next_action="wait for the next expected trade date",
            ),
        )

    gold_target = gold_selection.first_not_ready_trade_date
    if gold_selection.blocked_reason == "materialized_check_failed":
        return dg.SensorResult(
            skip_reason="Gold 目标分区已存在但核心 check 失败，请人工修复。",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                silver_batch=silver_batch,
                gold_batch=gold_batch,
                silver_status=silver_selection.selected_status,
                gold_status=gold_selection.selected_status,
                selected_trade_date=None,
                target_date=gold_target,
                reason_code="gold_materialized_check_failed",
                blocked_component="gold_dc_daily_technical",
                summary="materialized Gold checks failed; no automatic overwrite",
                next_action="repair the existing Gold partition manually",
            ),
        )

    silver_first_not_ready = silver_selection.first_not_ready_trade_date
    if silver_first_not_ready is not None and silver_first_not_ready <= gold_target:
        reason_code = (
            "silver_materialized_check_failed"
            if silver_selection.blocked_reason == "materialized_check_failed"
            else "silver_not_ready"
        )
        return dg.SensorResult(
            skip_reason="Silver dc_daily 尚未覆盖 Gold 技术指标目标日期。",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                silver_batch=silver_batch,
                gold_batch=gold_batch,
                silver_status=silver_selection.selected_status,
                gold_status=gold_selection.selected_status,
                selected_trade_date=None,
                target_date=gold_target,
                reason_code=reason_code,
                blocked_component="silver_dc_daily",
                summary="Silver frontier blocks Gold technical update",
                next_action="repair or materialize Silver before retrying Gold",
            ),
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject=JOB_NAME.removesuffix("_job"),
                    unit_id=gold_target,
                ),
                partition_key=gold_target,
            )
        ],
        cursor=_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            silver_batch=silver_batch,
            gold_batch=gold_batch,
            silver_status=silver_selection.selected_status,
            gold_status=gold_selection.selected_status,
            selected_trade_date=gold_target,
            target_date=gold_target,
            reason_code="gold_request_run",
            blocked_component="none",
            summary="Silver frontier covers the first Gold technical gap",
            next_action="wait for Gold technical materialization and core check",
        ),
    )


__all__ = ["gold_dc_daily_technical_update_job_sensor"]
