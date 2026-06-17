from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
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
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_RAW_HISTORY_START_DATE
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    raw_stk_mins_ready_for_trade_date,
    status_payload,
    stock_basic_ready_for_trade_date,
)
from orchestrator.defs.sensors.stock_mins_trade_day_sensor import (
    STOCK_MINS_TRADE_DAY_REGISTER_START,
)


STOCK_MINS_RAW_SENSOR_JOB_NAME = "stock_mins_raw_update_from_prod_job"
STOCK_MINS_RAW_RUN_START = time(19, 30)
STOCK_MINS_RAW_SOURCE = "prod_db"


def _load_stock_mins_raw_expected_trade_dates(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_RAW_HISTORY_START_DATE,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_MINS_TRADE_DAY_REGISTER_START,
        )


def _target_trade_date_from_continuity_status(
    status: StockMinsContinuityStatus,
) -> str | None:
    return (
        status.next_actionable_trade_date
        or status.first_not_ready_trade_date
        or status.first_missing_registered_date
        or status.ready_through_trade_date
        or status.expected_end_date
    )


def _has_materialized_check_problem(status: DatasetReadinessStatus) -> bool:
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: DatasetReadinessStatus | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
    continuity_status: StockMinsContinuityStatus | None = None,
    blocked_fallback: int = 0,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not selected_trade_date:
        if raw_status is not None and not raw_status.ready:
            blocked_count = len(
                [asset_status for asset_status in raw_status.statuses if not asset_status.ready]
            )
        elif stock_basic_status is not None and not stock_basic_status.ready:
            blocked_count = 1
        elif continuity_status is not None and continuity_status.first_missing_registered_date:
            blocked_count = max(
                1,
                continuity_status.expected_count - continuity_status.registered_count,
            )
        elif continuity_status is not None and continuity_status.blocked:
            blocked_count = 1
        else:
            blocked_count = blocked_fallback

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "source": STOCK_MINS_RAW_SOURCE,
            "job_name": STOCK_MINS_RAW_SENSOR_JOB_NAME,
            "source_window_started": source_window_started,
            "stock_basic_freshness_required": True,
            "raw_status": status_payload(raw_status) if raw_status else None,
            "stock_basic_status": (
                status_payload(stock_basic_status) if stock_basic_status else None
            ),
            "continuity_status": (
                continuity_status.to_cursor_details()
                if continuity_status is not None
                else None
            ),
        },
    )


def _run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="stock_mins_raw_update_from_prod",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


@dg.sensor(
    job_name=STOCK_MINS_RAW_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票分钟线交易日分区和基础信息 freshness/checks 就绪后，触发五频度 prod DB raw 更新任务。",
)
def stock_mins_raw_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    source_window_started = evaluated_at.time() >= STOCK_MINS_RAW_RUN_START
    expected_trade_dates = _load_stock_mins_raw_expected_trade_dates(
        context,
        evaluated_at,
    )
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_trade_days.name
            )
        )
    )
    selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_trade_days.name,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=lambda trade_date: raw_stk_mins_ready_for_trade_date(
            context.instance,
            trade_date,
        ),
        has_materialized_check_problem=_has_materialized_check_problem,
    )
    continuity_status = selection.status
    target_trade_date = _target_trade_date_from_continuity_status(continuity_status)
    raw_status = (
        selection.selected_status
        if isinstance(selection.selected_status, DatasetReadinessStatus)
        else None
    )

    if continuity_status.first_missing_registered_date is not None:
        reason = (
            "股票分钟线 raw 交易日分区存在缺口，"
            f"最早缺失日期为 {continuity_status.first_missing_registered_date}，"
            "暂不触发 raw 更新。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            continuity_status=continuity_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not source_window_started:
        reason = "股票分钟线 raw 日常更新窗口尚未到 19:30，暂不触发。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if selection.selected_trade_date is None:
        if continuity_status.blocked_reason == "materialized_check_problem":
            reason = (
                "最早未就绪股票分钟线 raw 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查后修复。"
            )
        else:
            reason = "股票分钟线 raw continuity 窗口内分区已经生成完成并通过 blocking checks。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            continuity_status=continuity_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    selected_trade_date = selection.selected_trade_date
    stock_basic_status = stock_basic_ready_for_trade_date(
        context.instance,
        selected_trade_date,
    )
    if not stock_basic_status.ready:
        reason = "股票基础信息尚未满足目标交易日 freshness 和 blocking checks 门禁。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            stock_basic_status=stock_basic_status,
            continuity_status=continuity_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = "股票分钟线 raw 门禁已满足，提交五频度 prod DB raw 更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        target_trade_date=target_trade_date,
        selected_trade_date=selected_trade_date,
        reason=reason,
        source_window_started=source_window_started,
        raw_status=raw_status,
        stock_basic_status=stock_basic_status,
        continuity_status=continuity_status,
    )
    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(selected_trade_date)],
        cursor=cursor,
    )
