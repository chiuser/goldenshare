"""Stopped-by-default bounded sensors for board Silver partitions."""

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
from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
    batch_raw_dc_index_lake_readiness,
    batch_raw_dc_member_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
    batch_silver_dc_index_lake_readiness,
    batch_silver_dc_member_lake_readiness,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_date_readiness,
)
from orchestrator.defs.run_contracts.cursors import SensorCursorDecision, build_sensor_cursor
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_SENSOR_WINDOW_LIMIT,
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_HISTORY_START_DATE,
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


def _load_window(
    context: dg.SensorEvaluationContext,
    *,
    connection,
    evaluated_at: datetime,
    min_trade_date: str,
    partition_set: str,
) -> tuple[ContinuityExpectedDateWindow, tuple[str, ...], ContinuityRegisteredGapStatus]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    expected_window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=min_trade_date,
        same_day_register_start=None,
        window_limit=DC_BOARD_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(partition_set))
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return expected_window, registered, gap_status


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    raw_batch: ContinuityBatchReadiness | None,
    silver_batch: ContinuityBatchReadiness | None,
    raw_status: object | None,
    silver_status: object | None,
    selected_trade_date: str | None,
    target_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    partition_set: str,
) -> str:
    frontier = {
        "continuity": compact_continuity_frontier(
            gap_status,
            selected_trade_date=selected_trade_date,
        )
        if gap_status is not None
        else None,
        "raw": compact_batch_frontier(raw_batch, selected_trade_date=selected_trade_date),
        "silver": compact_batch_frontier(
            silver_batch,
            selected_trade_date=selected_trade_date,
        ),
    }
    expected_count = len(expected_window.expected_trade_dates) if expected_window else 0
    registered_count = len(gap_status.registered_trade_dates) if gap_status else 0
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
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family="dc_board_silver",
            partition_set=partition_set,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier=frontier,
            gate_statuses={
                "raw": compact_date_readiness(raw_status),
                "silver": compact_date_readiness(silver_status),
            },
            evidence={
                "expected_count": expected_count,
                "registered_count": registered_count,
                "max_run_requests_per_tick": 1,
            },
            performance_ms={
                "raw_batch": raw_batch.elapsed_ms if raw_batch else None,
                "silver_batch": silver_batch.elapsed_ms if silver_batch else None,
            },
        ),
    )


def _evaluate_silver_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    min_trade_date: str,
    raw_reader,
    silver_reader,
    partition_set,
) -> dg.SensorResult:
    duckdb_resource = context.resources.duckdb
    try:
        with duckdb_resource.connect() as connection:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
                min_trade_date=min_trade_date,
                partition_set=partition_set,
            )
            if not gap_status.ready:
                reason = "registered partition gap blocks Silver update"
                return dg.SensorResult(
                    skip_reason=(
                        "板块 Silver 交易日分区尚未完整注册，最早缺失日期为 "
                        f"{gap_status.first_missing_registered_date}。"
                    ),
                    cursor=_cursor(
                        sensor_name=sensor_name,
                        job_name=job_name,
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        raw_batch=None,
                        silver_batch=None,
                        raw_status=None,
                        silver_status=None,
                        selected_trade_date=None,
                        target_date=gap_status.first_missing_registered_date,
                        reason_code="missing_registered_partition",
                        blocked_component=partition_set,
                        summary=reason,
                        next_action="register the first missing trade-date partition",
                        partition_set=partition_set,
                    ),
                )
            raw_batch = raw_reader(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            silver_batch = silver_reader(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
    except Exception as exc:
        return dg.SensorResult(
            skip_reason=str(exc),
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                raw_batch=None,
                silver_batch=None,
                raw_status=None,
                silver_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="scan_error",
                blocked_component="calendar_or_lake",
                summary="bounded Silver readiness scan failed",
                next_action="inspect the lake scan error and retry after correction",
                partition_set=partition_set,
            ),
        )

    raw_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=raw_batch,
    )
    silver_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=silver_batch,
    )
    silver_target = silver_selection.selected_trade_date
    silver_status = silver_selection.selected_status
    raw_first_not_ready = raw_selection.first_not_ready_trade_date
    raw_status = raw_selection.selected_status

    if silver_selection.blocked_reason == "materialized_check_failed":
        return dg.SensorResult(
            skip_reason="Silver partition exists but core checks failed; manual repair is required.",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
                raw_status=raw_status,
                silver_status=silver_status,
                selected_trade_date=None,
                target_date=silver_selection.first_not_ready_trade_date,
                reason_code="silver_materialized_check_failed",
                blocked_component=job_name.removesuffix("_update_job"),
                summary="materialized Silver checks failed; no automatic overwrite",
                next_action="repair the existing Silver partition manually",
                partition_set=partition_set,
            ),
        )

    if silver_target is None:
        reason = "recent Silver partitions are ready"
        return dg.SensorResult(
            skip_reason="最近 10 个 expected 日期的 Silver 分区都已 ready。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
                raw_status=raw_status,
                silver_status=None,
                selected_trade_date=None,
                target_date=None,
                reason_code="all_ready",
                blocked_component="none",
                summary=reason,
                next_action="wait for the next expected trade date",
                partition_set=partition_set,
            ),
        )

    if raw_first_not_ready is not None and raw_first_not_ready <= silver_target:
        raw_reason = (
            "raw_materialized_check_failed"
            if raw_selection.blocked_reason == "materialized_check_failed"
            else "raw_not_ready"
        )
        return dg.SensorResult(
            skip_reason="对应 Raw frontier 未覆盖 Silver 目标日期，暂不触发 Silver。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
                raw_status=raw_status,
                silver_status=silver_status,
                selected_trade_date=None,
                target_date=silver_target,
                reason_code=raw_reason,
                blocked_component=(
                    "raw_"
                    + job_name.removeprefix("silver_").removesuffix("_update_job")
                ),
                summary="Raw first-not-ready frontier blocks Silver",
                next_action="repair or materialize the Raw target before retrying Silver",
                partition_set=partition_set,
            ),
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject=job_name.removesuffix("_job"),
                    unit_id=silver_target,
                ),
                partition_key=silver_target,
            )
        ],
        cursor=_cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            raw_batch=raw_batch,
            silver_batch=silver_batch,
            raw_status=raw_status,
            silver_status=silver_status,
            selected_trade_date=silver_target,
            target_date=silver_target,
            reason_code="silver_request_run",
            blocked_component="none",
            summary="Raw frontier covers the first Silver gap",
            next_action="wait for the Silver run and core check to complete",
            partition_set=partition_set,
        ),
    )


@dg.sensor(
    job_name="silver_dc_index_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def silver_dc_index_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_silver_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="silver_dc_index_update_job_sensor",
        job_name="silver_dc_index_update_job",
        min_trade_date=DC_INDEX_HISTORY_START_DATE,
        raw_reader=batch_raw_dc_index_lake_readiness,
        silver_reader=batch_silver_dc_index_lake_readiness,
        partition_set=cn_a_dc_index_trade_days.name,
    )


@dg.sensor(
    job_name="silver_dc_member_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def silver_dc_member_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_silver_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="silver_dc_member_update_job_sensor",
        job_name="silver_dc_member_update_job",
        min_trade_date=DC_MEMBER_HISTORY_START_DATE,
        raw_reader=batch_raw_dc_member_lake_readiness,
        silver_reader=batch_silver_dc_member_lake_readiness,
        partition_set=cn_a_dc_member_trade_days.name,
    )


@dg.sensor(
    job_name="silver_dc_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def silver_dc_daily_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_silver_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="silver_dc_daily_update_job_sensor",
        job_name="silver_dc_daily_update_job",
        min_trade_date=DC_DAILY_HISTORY_START_DATE,
        raw_reader=batch_raw_dc_daily_lake_readiness,
        silver_reader=batch_silver_dc_daily_lake_readiness,
        partition_set=cn_a_dc_daily_trade_days.name,
    )


__all__ = [
    "silver_dc_daily_update_job_sensor",
    "silver_dc_index_update_job_sensor",
    "silver_dc_member_update_job_sensor",
]
