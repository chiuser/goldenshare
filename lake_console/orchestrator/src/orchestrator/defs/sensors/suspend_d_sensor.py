from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
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
    CN_A_SENSOR_TIMEZONE,
    RAW_SUSPEND_D_ASSET_KEY,
    SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY,
    AssetReadinessStatus,
    materialized_partition_keys,
    raw_tushare_suspend_d_ready_for_trade_date,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import STOCK_TRADE_DAY_MIN_DATE
from orchestrator.defs.sensors.stock_trade_day_sensor import (
    STOCK_TRADE_DAY_REGISTER_START,
)


MAX_RUN_REQUESTS_PER_TICK = 2


def _eligible_registered_trade_dates(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    today = evaluated_at.date().isoformat()
    return tuple(
        key
        for key in sorted(
            context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
        )
        if key <= today
    )


def _load_expected_stock_trade_day_window(
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
            min_trade_date=STOCK_TRADE_DAY_MIN_DATE,
            same_day_register_start=STOCK_TRADE_DAY_REGISTER_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _stock_trade_day_registered_gap(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    registered_keys: tuple[str, ...],
) -> tuple[ContinuityExpectedDateWindow, ContinuityRegisteredGapStatus]:
    expected_window = _load_expected_stock_trade_day_window(context, evaluated_at)
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_keys,
    )
    return expected_window, gap_status


def _continuity_details(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
) -> dict[str, object]:
    return build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=None,
        selection=None,
    )


def _registered_gap_skip_reason(
    *,
    layer_label: str,
    gap_status: ContinuityRegisteredGapStatus,
) -> str:
    return (
        "股票交易日分区存在缺口，最早缺失日期为 "
        f"{gap_status.first_missing_registered_date}，暂不触发停复牌 "
        f"{layer_label} 更新。"
    )


def _readiness_asset_payload(status: AssetReadinessStatus) -> dict[str, object]:
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


def _raw_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_count: int,
    pending_keys: tuple[str, ...],
    selected_keys: tuple[str, ...],
    continuity_details: dict[str, object] | None,
    blocked_key: str | None = None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_keys
        else SensorCursorDecision.SKIP
    )
    target_date = (
        selected_keys[0]
        if selected_keys
        else blocked_key
        if blocked_key
        else pending_keys[0]
        if pending_keys
        else None
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=len(selected_keys),
        blocked_count=1 if blocked_key and not selected_keys else max(
            0,
            len(pending_keys) - len(selected_keys),
        ),
        sample_keys=selected_keys or ((blocked_key,) if blocked_key else pending_keys),
        details={
            "registered_count": registered_count,
            "pending_count": len(pending_keys),
            "selected_keys": list(selected_keys),
            "blocked_key": blocked_key,
            "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
            "continuity_status": continuity_details,
        },
    )


def _silver_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_count: int,
    pending_keys: tuple[str, ...],
    selected_keys: tuple[str, ...],
    blocked_keys: tuple[str, ...],
    readiness_details: dict[str, dict[str, object]],
    continuity_details: dict[str, object] | None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_keys
        else SensorCursorDecision.SKIP
    )
    target_date = (
        selected_keys[0]
        if selected_keys
        else blocked_keys[0]
        if blocked_keys
        else pending_keys[0]
        if pending_keys
        else None
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=len(selected_keys),
        blocked_count=len(blocked_keys),
        sample_keys=selected_keys or blocked_keys or pending_keys,
        details={
            "registered_count": registered_count,
            "pending_count": len(pending_keys),
            "selected_keys": list(selected_keys),
            "blocked_keys": list(blocked_keys),
            "readiness_details": readiness_details,
            "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
            "continuity_status": continuity_details,
        },
    )


@dg.sensor(
    job_name="raw_suspend_d_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"duckdb", "lake_root"},
    description="停复牌 raw 分区缺失时，触发停复牌 raw 更新任务。",
)
def raw_suspend_d_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_keys = _eligible_registered_trade_dates(context, evaluated_at)
    expected_window, gap_status = _stock_trade_day_registered_gap(
        context,
        evaluated_at=evaluated_at,
        registered_keys=registered_keys,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
    )
    if gap_status.first_missing_registered_date is not None:
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_count=len(registered_keys),
            pending_keys=(),
            selected_keys=(),
            blocked_key=gap_status.first_missing_registered_date,
            continuity_details=continuity_details,
        )
        return dg.SensorResult(
            skip_reason=_registered_gap_skip_reason(
                layer_label="raw",
                gap_status=gap_status,
            ),
            cursor=cursor,
        )

    raw_materialized_keys = materialized_partition_keys(
        context.instance,
        (RAW_SUSPEND_D_ASSET_KEY,),
    )
    pending_keys = tuple(
        key for key in registered_keys if key not in raw_materialized_keys
    )
    selected_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    cursor = _raw_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        pending_keys=pending_keys,
        selected_keys=selected_keys,
        blocked_key=None,
        continuity_details=continuity_details,
    )

    if not selected_keys:
        if not registered_keys:
            skip_reason = "当前没有已注册股票交易日分区。"
        else:
            skip_reason = "当前停复牌 raw 分区都已经生成完成。"
        return dg.SensorResult(skip_reason=skip_reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=trade_date,
                run_key=build_asset_update_run_key(
                    subject="raw_suspend_d_update",
                    unit_id=trade_date,
                ),
            )
            for trade_date in selected_keys
        ],
        cursor=cursor,
    )


@dg.sensor(
    job_name="silver_suspend_d_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"duckdb", "lake_root"},
    description="停复牌 raw ready 后，触发停复牌 silver-only 更新。",
)
def silver_suspend_d_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_keys = _eligible_registered_trade_dates(context, evaluated_at)
    expected_window, gap_status = _stock_trade_day_registered_gap(
        context,
        evaluated_at=evaluated_at,
        registered_keys=registered_keys,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
    )
    if gap_status.first_missing_registered_date is not None:
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_count=len(registered_keys),
            pending_keys=(),
            selected_keys=(),
            blocked_keys=(gap_status.first_missing_registered_date,),
            readiness_details={},
            continuity_details=continuity_details,
        )
        return dg.SensorResult(
            skip_reason=_registered_gap_skip_reason(
                layer_label="silver",
                gap_status=gap_status,
            ),
            cursor=cursor,
        )

    silver_materialized_keys = materialized_partition_keys(
        context.instance,
        (SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY,),
    )
    pending_keys = tuple(
        key for key in registered_keys if key not in silver_materialized_keys
    )
    candidate_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    selected_keys: list[str] = []
    blocked_keys: list[str] = []
    readiness_details: dict[str, dict[str, object]] = {}

    for trade_date in candidate_keys:
        raw_status = raw_tushare_suspend_d_ready_for_trade_date(
            context.instance,
            trade_date,
        )
        readiness_details.setdefault(trade_date, {})
        readiness_details[trade_date]["raw_tushare_suspend_d"] = (
            _readiness_asset_payload(raw_status)
        )
        if not raw_status.ready:
            blocked_keys.append(trade_date)
            continue

        selected_keys.append(trade_date)

    selected_tuple = tuple(selected_keys)
    cursor = _silver_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        pending_keys=pending_keys,
        selected_keys=selected_tuple,
        blocked_keys=tuple(blocked_keys),
        readiness_details=readiness_details,
        continuity_details=continuity_details,
    )

    if not selected_tuple:
        if not pending_keys:
            skip_reason = "当前停复牌 silver 分区都已经生成完成。"
        elif blocked_keys:
            skip_reason = "停复牌 silver 前置 raw readiness 门禁未满足。"
        else:
            skip_reason = "当前没有满足门禁的停复牌 silver 待补分区。"
        return dg.SensorResult(skip_reason=skip_reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=trade_date,
                run_key=build_asset_update_run_key(
                    subject="silver_suspend_d_update",
                    unit_id=trade_date,
                ),
            )
            for trade_date in selected_tuple
        ],
        cursor=cursor,
    )
