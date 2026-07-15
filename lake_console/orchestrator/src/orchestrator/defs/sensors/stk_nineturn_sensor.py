"""Bounded daily sensors for stock nine-turn Raw and Silver assets."""

from __future__ import annotations

from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityBatchReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    ContinuitySelection,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stk_nineturn_lake_readiness import (
    batch_raw_stk_nineturn_lake_readiness,
    batch_silver_stock_nineturn_daily_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_continuity_frontier,
    compact_date_readiness,
)
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
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.stk_nineturn_contract import STK_NINETURN_HISTORY_START_DATE


RAW_STK_NINETURN_RUN_START = time(21, 15)
SILVER_STOCK_NINETURN_RUN_START = time(21, 20)


def _load_expected_window(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> ContinuityExpectedDateWindow:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    connect_duckdb = duckdb_resource.connect
    with connect_duckdb() as connection:
        return load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            min_trade_date=STK_NINETURN_HISTORY_START_DATE,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _raw_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_stk_nineturn_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _silver_run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_stock_nineturn_daily_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _target_date(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    selection: ContinuitySelection | None,
) -> str | None:
    if gap_status.first_missing_registered_date is not None:
        return gap_status.first_missing_registered_date
    if selection is not None:
        return (
            selection.first_not_ready_trade_date
            or selection.ready_through_trade_date
            or expected_window.max_trade_date
        )
    return expected_window.max_trade_date


def _continuity_payload(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_readiness: ContinuityBatchReadiness | None,
    selection: ContinuitySelection | None,
) -> dict[str, object]:
    return {
        "expected_start_date": (
            expected_window.expected_trade_dates[0]
            if expected_window.expected_trade_dates
            else None
        ),
        "expected_end_date": expected_window.max_trade_date,
        "expected_count": len(expected_window.expected_trade_dates),
        "registered_count": len(gap_status.registered_trade_dates),
        "first_missing_registered_date": gap_status.first_missing_registered_date,
        "ready_through_trade_date": (
            selection.ready_through_trade_date if selection is not None else None
        ),
        "first_not_ready_trade_date": (
            selection.first_not_ready_trade_date if selection is not None else None
        ),
        "selected_trade_date": (
            selection.selected_trade_date if selection is not None else None
        ),
        "blocked_reason": selection.blocked_reason if selection is not None else None,
        "batch_elapsed_ms": (
            batch_readiness.elapsed_ms if batch_readiness is not None else None
        ),
        "scanned_file_count": (
            batch_readiness.scanned_file_count
            if batch_readiness is not None
            else None
        ),
    }


def _sensor_cursor(
    *,
    sensor_name: str,
    job_name: str,
    target_layer: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_readiness: ContinuityBatchReadiness | None,
    selection: ContinuitySelection | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    run_window_started: bool,
    raw_batch_readiness: ContinuityBatchReadiness | None = None,
    raw_selection: ContinuitySelection | None = None,
) -> str:
    target_trade_date = _target_date(
        expected_window=expected_window,
        gap_status=gap_status,
        selection=selection,
    )
    gate_statuses = {}
    if raw_selection is not None and raw_selection.first_not_ready_trade_date:
        raw_status = raw_selection.selected_status
        if raw_status is None and raw_batch_readiness is not None:
            raw_status = raw_batch_readiness.status_for_trade_date(
                raw_selection.first_not_ready_trade_date
            )
        gate_statuses["raw_stk_nineturn"] = compact_date_readiness(raw_status)
    if selection is not None and selection.first_not_ready_trade_date:
        selected_status = selection.selected_status
        if selected_status is None and batch_readiness is not None:
            selected_status = batch_readiness.status_for_trade_date(
                selection.first_not_ready_trade_date
            )
        gate_statuses[target_layer] = compact_date_readiness(selected_status)
    performance_ms = {
        "raw_batch": (
            raw_batch_readiness.elapsed_ms
            if raw_batch_readiness is not None
            else None
        ),
        f"{target_layer}_batch": (
            batch_readiness.elapsed_ms if batch_readiness is not None else None
        ),
    }
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=selected_trade_date or target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=(
            0 if selected_trade_date or reason_code == "all_ready" else 1
        ),
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family="stk_nineturn",
            partition_set=cn_a_stk_nineturn_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier=compact_continuity_frontier(
                _continuity_payload(
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_readiness=batch_readiness,
                    selection=selection,
                ),
                selected_trade_date=selected_trade_date,
            ),
            gate_statuses=gate_statuses,
            evidence={"run_window_started": run_window_started},
            performance_ms=performance_ms,
        ),
    )


def _registered_gap_reason(gap_status: ContinuityRegisteredGapStatus) -> str:
    return (
        "神奇九转交易日分区存在缺口，最早缺失日期为 "
        f"{gap_status.first_missing_registered_date}，暂不触发神奇九转更新。"
    )


@dg.sensor(
    job_name="raw_stk_nineturn_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="21:15 后按最近 10 个交易日 first-not-ready 触发神奇九转 Raw 更新。",
)
def raw_stk_nineturn_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= RAW_STK_NINETURN_RUN_START
    expected_window = _load_expected_window(context, evaluated_at)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stk_nineturn_trade_days.name
            )
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    if gap_status.first_missing_registered_date is not None:
        reason = _registered_gap_reason(gap_status)
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="raw_stk_nineturn_update_job_sensor",
                job_name="raw_stk_nineturn_update_job",
                target_layer="raw_stk_nineturn",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
                selected_trade_date=None,
                reason_code="missing_registered_partition",
                blocked_component=cn_a_stk_nineturn_trade_days.name,
                summary="未触发：神奇九转交易日分区存在缺口。",
                next_action="先补齐 dynamic partition，再等待下一次 sensor tick。",
                run_window_started=run_window_started,
            ),
        )
    if not run_window_started:
        reason = "神奇九转 Raw 日常更新窗口尚未到 21:15，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="raw_stk_nineturn_update_job_sensor",
                job_name="raw_stk_nineturn_update_job",
                target_layer="raw_stk_nineturn",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
                selected_trade_date=None,
                reason_code="run_window_not_started",
                blocked_component="run_window",
                summary="未触发：神奇九转 Raw 更新窗口尚未到。",
                next_action="等待 21:15 后下一次 sensor tick。",
                run_window_started=False,
            ),
        )

    duckdb_resource = context.resources.duckdb
    connect_duckdb = duckdb_resource.connect
    with connect_duckdb() as connection:
        batch_readiness = batch_raw_stk_nineturn_lake_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=set(registered_trade_days),
            full_semantics=True,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=batch_readiness,
    )
    if selection.selected_trade_date is not None:
        trade_date = selection.selected_trade_date
        return dg.SensorResult(
            run_requests=[_raw_run_request_for_trade_date(trade_date)],
            cursor=_sensor_cursor(
                sensor_name="raw_stk_nineturn_update_job_sensor",
                job_name="raw_stk_nineturn_update_job",
                target_layer="raw_stk_nineturn",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=batch_readiness,
                selection=selection,
                selected_trade_date=trade_date,
                reason_code="request_run",
                blocked_component="none",
                summary=f"已触发：提交 {trade_date} 的神奇九转 Raw 更新。",
                next_action="等待 Raw run 和两个 blocking checks 完成。",
                run_window_started=True,
            ),
        )

    blocked = selection.blocked_reason == "materialized_check_failed"
    reason = (
        "最早未就绪神奇九转 Raw 分区已存在但 checks 未全绿，暂不自动重跑。"
        if blocked
        else "最近 10 个交易日神奇九转 Raw 分区都已 ready。"
    )
    return dg.SensorResult(
        skip_reason=reason,
        cursor=_sensor_cursor(
            sensor_name="raw_stk_nineturn_update_job_sensor",
            job_name="raw_stk_nineturn_update_job",
            target_layer="raw_stk_nineturn",
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=batch_readiness,
            selection=selection,
            selected_trade_date=None,
            reason_code="materialized_check_failed" if blocked else "all_ready",
            blocked_component="raw_stk_nineturn" if blocked else "none",
            summary=reason,
            next_action=(
                "查看 Raw check metadata 并人工修复；不要自动覆盖现有文件。"
                if blocked
                else "无需处理，等待下一个交易日。"
            ),
            run_window_started=True,
        ),
    )


@dg.sensor(
    job_name="silver_stock_nineturn_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="21:20 后在 Raw frontier 内触发神奇九转 Silver 标准化更新。",
)
def silver_stock_nineturn_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= SILVER_STOCK_NINETURN_RUN_START
    expected_window = _load_expected_window(context, evaluated_at)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stk_nineturn_trade_days.name
            )
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    if gap_status.first_missing_registered_date is not None:
        reason = _registered_gap_reason(gap_status)
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
                selected_trade_date=None,
                reason_code="missing_registered_partition",
                blocked_component=cn_a_stk_nineturn_trade_days.name,
                summary="未触发：神奇九转交易日分区存在缺口。",
                next_action="先补齐 dynamic partition，再等待下一次 sensor tick。",
                run_window_started=run_window_started,
            ),
        )
    if not run_window_started:
        reason = "神奇九转 Silver 日常更新窗口尚未到 21:20，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
                selected_trade_date=None,
                reason_code="run_window_not_started",
                blocked_component="run_window",
                summary="未触发：神奇九转 Silver 更新窗口尚未到。",
                next_action="等待 21:20 后下一次 sensor tick。",
                run_window_started=False,
            ),
        )

    duckdb_resource = context.resources.duckdb
    connect_duckdb = duckdb_resource.connect
    with connect_duckdb() as connection:
        raw_batch = batch_raw_stk_nineturn_lake_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=set(registered_trade_days),
            full_semantics=True,
        )
    raw_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=raw_batch,
    )
    raw_first_not_ready = raw_selection.first_not_ready_trade_date
    raw_ready_dates = tuple(
        trade_date
        for trade_date in expected_window.expected_trade_dates
        if raw_first_not_ready is None or trade_date < raw_first_not_ready
    )
    if not raw_ready_dates:
        raw_status = raw_batch.status_for_trade_date(
            raw_first_not_ready or expected_window.expected_trade_dates[0]
        )
        reason = "神奇九转 Silver 前置 Raw frontier 未满足，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=raw_selection,
                selected_trade_date=None,
                reason_code=raw_status.reason,
                blocked_component="raw_stk_nineturn",
                summary=reason,
                next_action="先补齐或修复 Raw 最早未就绪分区。",
                run_window_started=True,
                raw_batch_readiness=raw_batch,
                raw_selection=raw_selection,
            ),
        )

    identity_map_path = silver_stock_identity_map_path(
        context.resources.lake_root.root()
    )
    if not identity_map_path.exists():
        reason = "silver_stock_identity_map 文件不存在，神奇九转 Silver 暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
                selected_trade_date=None,
                reason_code="identity_mapping_missing",
                blocked_component="silver_stock_identity_map",
                summary="未触发：股票身份映射文件不存在。",
                next_action="先生成并验收 silver_stock_identity_map。",
                run_window_started=True,
                raw_batch_readiness=raw_batch,
                raw_selection=raw_selection,
            ),
        )

    with connect_duckdb() as connection:
        silver_batch = batch_silver_stock_nineturn_daily_lake_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=raw_ready_dates,
            registered_trade_days=set(registered_trade_days),
            full_semantics=True,
        )
    silver_selection = select_first_not_ready_trade_date(
        expected_trade_dates=raw_ready_dates,
        readiness=silver_batch,
    )
    selected_status = silver_selection.selected_status
    if (
        selected_status is not None
        and selected_status.reason
        in {"identity_mapping_missing", "identity_mapping_not_ready"}
    ):
        reason = "股票身份映射未满足神奇九转 Silver canonical 语义，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=silver_batch,
                selection=silver_selection,
                selected_trade_date=None,
                reason_code=selected_status.reason,
                blocked_component="silver_stock_identity_map",
                summary=reason,
                next_action="修复 identity 有效区间或映射冲突后等待下一次 tick。",
                run_window_started=True,
                raw_batch_readiness=raw_batch,
                raw_selection=raw_selection,
            ),
        )
    if silver_selection.selected_trade_date is not None:
        trade_date = silver_selection.selected_trade_date
        return dg.SensorResult(
            run_requests=[_silver_run_request_for_trade_date(trade_date)],
            cursor=_sensor_cursor(
                sensor_name="silver_stock_nineturn_daily_update_job_sensor",
                job_name="silver_stock_nineturn_daily_update_job",
                target_layer="silver_stock_nineturn_daily",
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=silver_batch,
                selection=silver_selection,
                selected_trade_date=trade_date,
                reason_code="request_run",
                blocked_component="none",
                summary=f"已触发：提交 {trade_date} 的神奇九转 Silver 更新。",
                next_action="等待 Silver run 和两个 blocking checks 完成。",
                run_window_started=True,
                raw_batch_readiness=raw_batch,
                raw_selection=raw_selection,
            ),
        )

    if silver_selection.blocked_reason == "materialized_check_failed":
        reason = "最早未就绪神奇九转 Silver 已存在但 checks 未全绿，暂不自动重跑。"
        reason_code = "materialized_check_failed"
        blocked_component = "silver_stock_nineturn_daily"
        next_action = "查看 Silver check metadata 并人工修复；不要自动覆盖现有文件。"
    elif raw_first_not_ready is not None:
        reason = "Raw frontier 之前的神奇九转 Silver 均 ready，等待 Raw 继续推进。"
        raw_status = raw_batch.status_for_trade_date(raw_first_not_ready)
        reason_code = raw_status.reason
        blocked_component = "raw_stk_nineturn"
        next_action = "先补齐或修复 Raw 最早未就绪分区。"
    else:
        reason = "最近 10 个交易日神奇九转 Silver 分区都已 ready。"
        reason_code = "all_ready"
        blocked_component = "none"
        next_action = "无需处理，等待下一个交易日。"
    return dg.SensorResult(
        skip_reason=reason,
        cursor=_sensor_cursor(
            sensor_name="silver_stock_nineturn_daily_update_job_sensor",
            job_name="silver_stock_nineturn_daily_update_job",
            target_layer="silver_stock_nineturn_daily",
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=silver_batch,
            selection=silver_selection,
            selected_trade_date=None,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=reason,
            next_action=next_action,
            run_window_started=True,
            raw_batch_readiness=raw_batch,
            raw_selection=raw_selection,
        ),
    )
