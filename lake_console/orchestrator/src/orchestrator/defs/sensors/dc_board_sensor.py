"""Stopped-by-default bounded sensors for board Raw partitions."""

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
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardSourceProbeResult,
    probe_dc_daily,
    probe_dc_index,
    probe_dc_member,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_SENSOR_WINDOW_LIMIT,
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    compact_batch_frontier,
    compact_continuity_frontier,
    build_cursor_details,
)
from orchestrator.defs.run_contracts.cursors import SensorCursorDecision, build_sensor_cursor
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
    batch_status: ContinuityBatchReadiness | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    partition_set: str,
    decision: SensorCursorDecision = SensorCursorDecision.SKIP,
    target_date: str | None = None,
    source_probe: DcBoardSourceProbeResult | None = None,
) -> str:
    details = build_cursor_details(
        sensor_name=sensor_name,
        job_name=job_name,
        asset_family="dc_board",
        partition_set=partition_set,
        reason_code=reason_code,
        blocked_component=blocked_component,
        summary=summary,
        next_action=next_action,
        frontier=(
            compact_batch_frontier(batch_status, selected_trade_date=selected_trade_date)
            if batch_status is not None
            else compact_continuity_frontier(
                gap_status,
                selected_trade_date=selected_trade_date,
            )
        ),
        evidence={
            "expected_count": len(expected_window.expected_trade_dates)
            if expected_window
            else 0,
            "registered_count": len(gap_status.registered_trade_dates)
            if gap_status
            else 0,
            "source_probe": source_probe.to_summary() if source_probe else None,
        },
        performance_ms={
            "duckdb_batch": batch_status.elapsed_ms if batch_status else None,
            "source_probe": source_probe.elapsed_ms if source_probe else None,
        },
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        details=details,
    )


def _evaluate_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    dataset: str,
    min_trade_date: str,
    batch_reader,
    source_probe_reader,
    partition_set,
    upstream_index_gate: bool = False,
) -> dg.SensorResult:
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        try:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
                min_trade_date=min_trade_date,
                partition_set=partition_set,
            )
            if not gap_status.ready:
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=None,
                    selected_trade_date=None,
                    reason_code="missing_registered_partition",
                    blocked_component="partition_set",
                    summary="registered partition gap blocks board Raw update",
                    next_action="register the first missing trade-date partition",
                    target_date=gap_status.first_missing_registered_date,
                    partition_set=partition_set,
                )
                return dg.SensorResult(
                    skip_reason=(
                        "板块 Raw 交易日分区尚未完整注册，最早缺失日期为 "
                        f"{gap_status.first_missing_registered_date}。"
                    ),
                    cursor=cursor,
                )
            if upstream_index_gate:
                index_registered = tuple(
                    sorted(
                        context.instance.get_dynamic_partitions(
                            cn_a_dc_index_trade_days.name
                        )
                    )
                )
                index_batch = batch_raw_dc_index_lake_readiness(
                    connection=connection,
                    lake_root=context.resources.lake_root.root(),
                    expected_trade_dates=expected_window.expected_trade_dates,
                    registered_trade_days=index_registered,
                )
                index_selection = select_first_not_ready_trade_date(
                    expected_trade_dates=expected_window.expected_trade_dates,
                    readiness=index_batch,
                )
                if index_selection.selected_trade_date is not None or index_selection.blocked_reason:
                    cursor = _cursor(
                        sensor_name=sensor_name,
                        job_name=job_name,
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        batch_status=index_batch,
                        selected_trade_date=None,
                        reason_code=(
                            "materialized_check_failed"
                            if index_selection.blocked_reason
                            else "upstream_index_not_ready"
                        ),
                        blocked_component="raw_dc_index",
                        summary="dc_member waits for raw dc_index readiness",
                        next_action="repair or materialize raw dc_index first",
                        target_date=index_selection.first_not_ready_trade_date,
                        source_probe=None,
                        partition_set=partition_set,
                    )
                    return dg.SensorResult(
                        skip_reason="dc_member 等待同日 raw dc_index 就绪。",
                        cursor=cursor,
                    )
            batch_status = batch_reader(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            selection = select_first_not_ready_trade_date(
                expected_trade_dates=expected_window.expected_trade_dates,
                readiness=batch_status,
            )
            selected_trade_date = selection.selected_trade_date
            if selected_trade_date is None:
                reason_code = "materialized_check_failed" if selection.blocked_reason else "all_ready"
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code=reason_code,
                    blocked_component="raw_lake" if selection.blocked_reason else "none",
                    summary="board Raw window is ready" if reason_code == "all_ready" else "materialized board Raw checks failed",
                    next_action="wait for the next expected trade date" if reason_code == "all_ready" else "repair the materialized Raw partition manually",
                    target_date=selection.first_not_ready_trade_date,
                    source_probe=None,
                    partition_set=partition_set,
                )
                return dg.SensorResult(skip_reason="板块 Raw 窗口暂无可提交分区。", cursor=cursor)

            try:
                source_probe = source_probe_reader(
                    connection=connection,
                    lake_root=context.resources.lake_root.root(),
                    tushare=context.resources.tushare,
                    trade_date=selected_trade_date,
                )
            except Exception as exc:  # noqa: BLE001 - source probe must fail closed.
                source_probe = DcBoardSourceProbeResult(
                    dataset=dataset,
                    trade_date=selected_trade_date,
                    ready=False,
                    reason_code="source_probe_error",
                    request_count=0,
                    retry_count=0,
                    elapsed_ms=0.0,
                    successful_count=0,
                    empty_count=0,
                    failed_count=1,
                    unattempted_count=0,
                    sample=({"error": str(exc)[:300]},),
                )
            if not source_probe.ready:
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code=source_probe.reason_code,
                    blocked_component="source_probe",
                    summary="source availability probe did not pass",
                    next_action="retry the bounded source probe on the next tick",
                    target_date=selected_trade_date,
                    source_probe=source_probe,
                    partition_set=partition_set,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 源站有限探测未通过，等待下一轮探测。",
                    cursor=cursor,
                )

            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=batch_status,
                selected_trade_date=selected_trade_date,
                reason_code="request_run",
                blocked_component="none",
                summary="first board Raw partition is ready to request",
                next_action="run the selected trade-date partition",
                decision=SensorCursorDecision.REQUEST_RUNS,
                target_date=selected_trade_date,
                source_probe=source_probe,
                partition_set=partition_set,
            )
            return dg.SensorResult(
                run_requests=[
                    build_run_request(
                        run_key=build_asset_update_run_key(
                            subject=job_name.removesuffix("_job"),
                            unit_id=selected_trade_date,
                        ),
                        partition_key=selected_trade_date,
                    )
                ],
                cursor=cursor,
            )
        except Exception as exc:
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                batch_status=None,
                selected_trade_date=None,
                reason_code="calendar_scan_error",
                blocked_component="calendar",
                summary="calendar scan failed",
                next_action="repair calendar input and retry",
                partition_set=partition_set,
            )
            return dg.SensorResult(skip_reason=str(exc), cursor=cursor)


@dg.sensor(
    job_name="raw_tushare_dc_index_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(sensor_domain=SensorDomain.INDEX_TOPIC, target_layer=SensorTargetLayer.RAW, role=SensorRole.ASSET_UPDATE),
)
def raw_tushare_dc_index_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_index_update_job_sensor",
        job_name="raw_tushare_dc_index_update_job",
        dataset="dc_index",
        partition_set=cn_a_dc_index_trade_days.name,
        min_trade_date=DC_INDEX_HISTORY_START_DATE,
        batch_reader=batch_raw_dc_index_lake_readiness,
        source_probe_reader=probe_dc_index,
    )


@dg.sensor(
    job_name="raw_tushare_dc_member_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(sensor_domain=SensorDomain.INDEX_TOPIC, target_layer=SensorTargetLayer.RAW, role=SensorRole.ASSET_UPDATE),
)
def raw_tushare_dc_member_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_member_update_job_sensor",
        job_name="raw_tushare_dc_member_update_job",
        dataset="dc_member",
        partition_set=cn_a_dc_member_trade_days.name,
        min_trade_date=DC_MEMBER_HISTORY_START_DATE,
        batch_reader=batch_raw_dc_member_lake_readiness,
        source_probe_reader=probe_dc_member,
        upstream_index_gate=True,
    )


@dg.sensor(
    job_name="raw_tushare_dc_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(sensor_domain=SensorDomain.INDEX_TOPIC, target_layer=SensorTargetLayer.RAW, role=SensorRole.ASSET_UPDATE),
)
def raw_tushare_dc_daily_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_daily_update_job_sensor",
        job_name="raw_tushare_dc_daily_update_job",
        dataset="dc_daily",
        partition_set=cn_a_dc_daily_trade_days.name,
        min_trade_date=DC_DAILY_HISTORY_START_DATE,
        batch_reader=batch_raw_dc_daily_lake_readiness,
        source_probe_reader=probe_dc_daily,
        upstream_index_gate=True,
    )


__all__ = [
    "raw_tushare_dc_daily_update_job_sensor",
    "raw_tushare_dc_index_update_job_sensor",
    "raw_tushare_dc_member_update_job_sensor",
]
