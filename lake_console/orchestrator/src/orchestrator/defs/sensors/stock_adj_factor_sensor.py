from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    batch_raw_adj_factor_lake_readiness,
    batch_silver_adj_factor_lake_readiness,
)
from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    ContinuitySelection,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
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
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    silver_stock_lifecycle_ready_without_freshness,
    stock_basic_ready_without_freshness,
)


STOCK_ADJ_FACTOR_RUN_START = time(9, 30)


def _load_expected_current_trade_day_window(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> ContinuityExpectedDateWindow:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        return load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_ADJ_FACTOR_RUN_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _target_date_from_selection(
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


def _continuity_details(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_readiness: ContinuityBatchReadiness | None,
    selection: ContinuitySelection | None,
) -> dict[str, object]:
    first_not_ready_reason = None
    if selection is not None and selection.first_not_ready_trade_date is not None:
        selected_status = selection.selected_status
        if selected_status is None and batch_readiness is not None:
            selected_status = batch_readiness.status_for_trade_date(
                selection.first_not_ready_trade_date
            )
        if selected_status is not None:
            first_not_ready_reason = selected_status.reason
    return {
        "expected_start_date": expected_window.min_trade_date,
        "expected_end_date": expected_window.max_trade_date,
        "expected_count": len(expected_window.expected_trade_dates),
        "registered_count": len(gap_status.registered_trade_dates),
        "missing_registered_count": len(gap_status.missing_registered_dates),
        "first_missing_registered_date": gap_status.first_missing_registered_date,
        "ready_through_trade_date": (
            selection.ready_through_trade_date if selection is not None else None
        ),
        "first_not_ready_trade_date": (
            selection.first_not_ready_trade_date if selection is not None else None
        ),
        "first_not_ready_reason": first_not_ready_reason,
        "selected_trade_date": (
            selection.selected_trade_date if selection is not None else None
        ),
        "blocked_reason": selection.blocked_reason if selection is not None else None,
        "batch_elapsed_ms": (
            batch_readiness.elapsed_ms if batch_readiness is not None else None
        ),
        "scanned_file_count": (
            batch_readiness.scanned_file_count if batch_readiness is not None else None
        ),
    }


def _asset_status_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def _summary_count_payload(summary: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in summary.items()
        if key.endswith("_count") and (value or key.endswith("_row_count"))
    }


def _date_status_payload(status: ContinuityDateReadiness) -> dict[str, object]:
    payload: dict[str, object] = {
        "trade_date": status.trade_date,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "reason": status.reason,
        "failed_check_names": list(status.failed_check_names),
        "missing_check_names": list(status.missing_check_names),
        "missing_file_count": len(status.missing_file_paths),
    }
    if status.missing_file_paths:
        payload["first_missing_file_path"] = status.missing_file_paths[0]
    summary_counts = _summary_count_payload(status.summary)
    if summary_counts:
        payload["summary_counts"] = summary_counts
    return payload


def _dataset_status_payload(status: DatasetReadinessStatus) -> dict[str, object]:
    return {
        "ready": status.ready,
        "reason": status.reason,
        "statuses": [
            _asset_status_payload(asset_status) for asset_status in status.statuses
        ],
    }


def _status_payload(
    status: ContinuityDateReadiness
    | DatasetReadinessStatus
    | AssetReadinessStatus
    | None,
):
    if status is None:
        return None
    if isinstance(status, ContinuityDateReadiness):
        return _date_status_payload(status)
    if isinstance(status, DatasetReadinessStatus):
        return _dataset_status_payload(status)
    return _asset_status_payload(status)


def _raw_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    continuity_details: dict[str, object] | None,
    reason_code: str | None = None,
    blocked_component: str | None = None,
) -> str:
    if selected_trade_date:
        reason_code = "request_run"
        blocked_component = "none"
    if reason_code is None and continuity_details is not None:
        blocked_reason = continuity_details.get("blocked_reason")
        first_not_ready_reason = continuity_details.get("first_not_ready_reason")
        first_missing_registered_date = continuity_details.get(
            "first_missing_registered_date"
        )
        if first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_current_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "raw_adj_factor"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "raw_adj_factor"
    if reason_code is None:
        reason_code = (
            "run_window_not_started" if not source_window_started else "all_ready"
        )
    if blocked_component is None:
        blocked_component = (
            "run_window" if reason_code == "run_window_not_started" else "none"
        )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date or reason_code == "all_ready" else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details={
            "partition_set": cn_a_stock_current_trade_days.name,
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason_code": reason_code,
            "blocked_component": blocked_component,
            "source_window_started": source_window_started,
            "continuity_status": continuity_details,
        },
    )


def _silver_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: ContinuityDateReadiness | None = None,
    silver_status: ContinuityDateReadiness | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
    stock_lifecycle_status: AssetReadinessStatus | None = None,
    continuity_details: dict[str, object] | None = None,
    raw_continuity_details: dict[str, object] | None = None,
    reason_code: str | None = None,
    blocked_component: str | None = None,
) -> str:
    if selected_trade_date:
        reason_code = "request_run"
        blocked_component = "none"
    if reason_code is None and continuity_details is not None:
        blocked_reason = continuity_details.get("blocked_reason")
        first_not_ready_reason = continuity_details.get("first_not_ready_reason")
        first_missing_registered_date = continuity_details.get(
            "first_missing_registered_date"
        )
        if first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_current_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "silver_adj_factor"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "silver_adj_factor"
    if reason_code is None and raw_continuity_details is not None:
        blocked_reason = raw_continuity_details.get("blocked_reason")
        first_not_ready_reason = raw_continuity_details.get("first_not_ready_reason")
        if first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "raw_adj_factor"
        elif blocked_reason:
            reason_code = f"raw_{blocked_reason}"
            blocked_component = "raw_adj_factor"
    if reason_code is None:
        reason_code = (
            "run_window_not_started" if not source_window_started else "all_ready"
        )
    if blocked_component is None:
        blocked_component = (
            "run_window" if reason_code == "run_window_not_started" else "none"
        )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date or reason_code == "all_ready" else 1,
        sample_keys=(selected_trade_date or target_trade_date,)
        if selected_trade_date or target_trade_date
        else (),
        details={
            "partition_set": cn_a_stock_current_trade_days.name,
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason_code": reason_code,
            "blocked_component": blocked_component,
            "source_window_started": source_window_started,
            "stock_basic_freshness_required": False,
            "readiness_details": {
                "raw_tushare_adj_factor": _status_payload(raw_status),
                "silver_adj_factor": _status_payload(silver_status),
                "stock_basic": _status_payload(stock_basic_status),
                "stock_lifecycle": _status_payload(stock_lifecycle_status),
            },
            "continuity_status": continuity_details,
            "raw_continuity_status": raw_continuity_details,
        },
    )


def _raw_run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_adj_factor_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _silver_run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_adj_factor_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _registered_gap_skip_reason(
    *,
    layer_label: str,
    gap_status: ContinuityRegisteredGapStatus,
) -> str:
    return (
        f"股票当前交易日分区存在缺口，最早缺失日期为 "
        f"{gap_status.first_missing_registered_date}，暂不触发复权因子 "
        f"{layer_label} 更新。"
    )


@dg.sensor(
    job_name="raw_adj_factor_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="复权因子 raw 分区缺失时，触发复权因子 raw 更新任务。",
)
def raw_adj_factor_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_ADJ_FACTOR_RUN_START
    expected_window = _load_expected_current_trade_day_window(context, evaluated_at)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_current_trade_days.name
            )
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )

    if gap_status.first_missing_registered_date is not None:
        reason = _registered_gap_skip_reason(layer_label="raw", gap_status=gap_status)
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=gap_status.first_missing_registered_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            continuity_details=_continuity_details(
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
            ),
            reason_code="missing_registered_partition",
            blocked_component="cn_a_stock_current_trade_days",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "复权因子日常更新窗口尚未到 09:30，暂不触发 raw 更新。"
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=expected_window.max_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=False,
            continuity_details=_continuity_details(
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
            ),
            reason_code="run_window_not_started",
            blocked_component="run_window",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        raw_batch_status = batch_raw_adj_factor_lake_readiness(
            connection=connection,
            lake_root=lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=registered_trade_days,
            full_semantics=True,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=raw_batch_status,
    )
    target_trade_date = _target_date_from_selection(
        expected_window=expected_window,
        gap_status=gap_status,
        selection=selection,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=raw_batch_status,
        selection=selection,
    )

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = (
                "最早未就绪复权因子 raw 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查后修复。"
            )
        else:
            reason = "最近 10 个股票当前交易日的复权因子 raw 分区已经 ready。"
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=True,
            continuity_details=continuity_details,
            reason_code=(
                "materialized_check_failed"
                if selection.blocked_reason == "materialized_check_failed"
                else "all_ready"
            ),
            blocked_component=(
                "raw_adj_factor"
                if selection.blocked_reason == "materialized_check_failed"
                else "none"
            ),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "复权因子 raw 分区缺失，提交最早未就绪股票当前交易日 raw 更新。"
    cursor = _raw_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=selection.selected_trade_date,
        selected_trade_date=selection.selected_trade_date,
        reason=reason,
        source_window_started=True,
        continuity_details=continuity_details,
    )
    return dg.SensorResult(
        run_requests=[_raw_run_request_for_trade_date(selection.selected_trade_date)],
        cursor=cursor,
    )


@dg.sensor(
    job_name="silver_adj_factor_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="复权因子 raw 和股票基础信息 ready 后，触发复权因子 silver-only 更新。",
)
def silver_adj_factor_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_ADJ_FACTOR_RUN_START
    expected_window = _load_expected_current_trade_day_window(context, evaluated_at)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_current_trade_days.name
            )
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )

    if gap_status.first_missing_registered_date is not None:
        reason = _registered_gap_skip_reason(layer_label="silver", gap_status=gap_status)
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=gap_status.first_missing_registered_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            continuity_details=_continuity_details(
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
            ),
            reason_code="missing_registered_partition",
            blocked_component="cn_a_stock_current_trade_days",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "复权因子日常更新窗口尚未到 09:30，暂不触发 silver 更新。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=expected_window.max_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=False,
            continuity_details=_continuity_details(
                expected_window=expected_window,
                gap_status=gap_status,
                batch_readiness=None,
                selection=None,
            ),
            reason_code="run_window_not_started",
            blocked_component="run_window",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        raw_batch_status = batch_raw_adj_factor_lake_readiness(
            connection=connection,
            lake_root=lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=registered_trade_days,
            full_semantics=True,
        )
        silver_batch_status = batch_silver_adj_factor_lake_readiness(
            connection=connection,
            lake_root=lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=registered_trade_days,
            full_semantics=True,
        )

    raw_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=raw_batch_status,
    )
    silver_selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=silver_batch_status,
    )
    raw_target_date = _target_date_from_selection(
        expected_window=expected_window,
        gap_status=gap_status,
        selection=raw_selection,
    )
    target_trade_date = _target_date_from_selection(
        expected_window=expected_window,
        gap_status=gap_status,
        selection=silver_selection,
    )
    raw_continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=raw_batch_status,
        selection=raw_selection,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=silver_batch_status,
        selection=silver_selection,
    )

    raw_first_not_ready = raw_selection.first_not_ready_trade_date
    silver_first_not_ready = silver_selection.first_not_ready_trade_date
    if raw_first_not_ready is not None and (
        silver_first_not_ready is None or raw_first_not_ready <= silver_first_not_ready
    ):
        raw_status = raw_selection.selected_status or raw_batch_status.status_for_trade_date(
            raw_first_not_ready
        )
        if raw_selection.blocked_reason == "materialized_check_failed":
            reason = (
                "最早未就绪复权因子 raw 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动推进 silver，请人工检查后修复。"
            )
        else:
            reason = "复权因子 silver 前置 raw readiness 门禁未满足。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=raw_target_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=True,
            raw_status=raw_status,
            continuity_details=continuity_details,
            raw_continuity_details=raw_continuity_details,
            reason_code=(
                "raw_materialized_check_failed"
                if raw_selection.blocked_reason == "materialized_check_failed"
                else raw_status.reason
            ),
            blocked_component="raw_adj_factor",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if silver_selection.selected_trade_date is None:
        silver_status = silver_selection.selected_status
        if silver_selection.blocked_reason == "materialized_check_failed":
            reason = (
                "最早未就绪复权因子 silver 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查后修复。"
            )
        else:
            reason = "最近 10 个股票当前交易日的复权因子 silver 分区已经 ready。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=True,
            silver_status=silver_status,
            continuity_details=continuity_details,
            raw_continuity_details=raw_continuity_details,
            reason_code=(
                "silver_materialized_check_failed"
                if silver_selection.blocked_reason == "materialized_check_failed"
                else "all_ready"
            ),
            blocked_component=(
                "silver_adj_factor"
                if silver_selection.blocked_reason == "materialized_check_failed"
                else "none"
            ),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    selected_trade_date = silver_selection.selected_trade_date
    raw_status = raw_batch_status.status_for_trade_date(selected_trade_date)
    silver_status = silver_batch_status.status_for_trade_date(selected_trade_date)

    stock_basic_status = stock_basic_ready_without_freshness(context.instance)
    if not stock_basic_status.ready:
        reason = "股票基础信息尚未通过 materialization 和 blocking checks 门禁。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=True,
            raw_status=raw_status,
            silver_status=silver_status,
            stock_basic_status=stock_basic_status,
            continuity_details=continuity_details,
            raw_continuity_details=raw_continuity_details,
            reason_code="stock_basic_not_ready",
            blocked_component="stock_basic",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_lifecycle_status = silver_stock_lifecycle_ready_without_freshness(
        context.instance
    )
    if not stock_lifecycle_status.ready:
        reason = "股票生命周期事实尚未通过 materialization 和 blocking checks 门禁。"
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=True,
            raw_status=raw_status,
            silver_status=silver_status,
            stock_basic_status=stock_basic_status,
            stock_lifecycle_status=stock_lifecycle_status,
            continuity_details=continuity_details,
            raw_continuity_details=raw_continuity_details,
            reason_code="stock_lifecycle_not_ready",
            blocked_component="stock_lifecycle",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "复权因子 silver 门禁已满足，提交最早未就绪股票当前交易日 silver 更新。"
    cursor = _silver_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=selected_trade_date,
        selected_trade_date=selected_trade_date,
        reason=reason,
        source_window_started=True,
        raw_status=raw_status,
        silver_status=silver_status,
        stock_basic_status=stock_basic_status,
        stock_lifecycle_status=stock_lifecycle_status,
        continuity_details=continuity_details,
        raw_continuity_details=raw_continuity_details,
    )
    return dg.SensorResult(
        run_requests=[_silver_run_request_for_trade_date(selected_trade_date)],
        cursor=cursor,
    )
