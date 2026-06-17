from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
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
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_SILVER_HISTORY_START_DATE
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    raw_stk_mins_ready_for_trade_date,
    silver_namechange_ready_for_trade_date,
    silver_stk_mins_ready_for_trade_date,
    silver_stock_identity_map_ready_for_trade_date,
    status_payload,
    stock_daily_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
)


STOCK_MINS_SILVER_SENSOR_JOB_NAME = "stock_mins_silver_update_job"
STOCK_MINS_SILVER_RUN_START = time(19, 50)


@dataclass(frozen=True)
class StockMinsSilverUpdateDecision:
    target_trade_date: str | None
    run_window_started: bool
    selected_trade_date: str | None
    reason: str


def _load_stock_mins_silver_expected_trade_dates(
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
            min_trade_date=STK_MINS_SILVER_HISTORY_START_DATE,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
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


def build_stock_mins_silver_update_decision(
    *,
    target_trade_date: str | None,
    run_window_started: bool,
    raw_ready: bool = False,
    stock_daily_ready: bool = False,
    suspend_ready: bool = False,
    identity_map_ready: bool = False,
    namechange_ready: bool = False,
    silver_ready: bool = False,
    silver_has_materialized_check_problem: bool = False,
) -> StockMinsSilverUpdateDecision:
    if target_trade_date is None:
        return StockMinsSilverUpdateDecision(
            target_trade_date=None,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason="没有注册股票分钟线 silver 交易日分区，无法触发 silver 更新。",
        )
    if not run_window_started:
        return StockMinsSilverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="股票分钟线 silver 日常更新窗口尚未到 19:50，暂不触发。",
        )
    if not raw_ready:
        reason = "股票分钟线 raw 五频度尚未全部 ready，暂不触发 silver 更新。"
    elif not stock_daily_ready:
        reason = "股票日线尚未 ready，暂不触发股票分钟线 silver 更新。"
    elif not suspend_ready:
        reason = "停复牌数据尚未 ready，暂不触发股票分钟线 silver 更新。"
    elif not identity_map_ready:
        reason = "股票身份映射尚未满足当日 freshness，暂不触发股票分钟线 silver 更新。"
    elif not namechange_ready:
        reason = "股票曾用名尚未满足当日 freshness，暂不触发股票分钟线 silver 更新。"
    elif silver_ready:
        reason = "最新股票分钟线 silver 交易日的五频度分区已经 ready。"
    elif silver_has_materialized_check_problem:
        reason = (
            "最新股票分钟线 silver 分区已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
    else:
        return StockMinsSilverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=target_trade_date,
            reason="股票分钟线 silver 门禁已满足，提交五频度 silver 更新。",
        )

    return StockMinsSilverUpdateDecision(
        target_trade_date=target_trade_date,
        run_window_started=True,
        selected_trade_date=None,
        reason=reason,
    )


def _asset_status_payload(status: AssetReadinessStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
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


def _not_ready_count(status: DatasetReadinessStatus | None) -> int:
    if status is None or status.ready:
        return 0
    return len([asset_status for asset_status in status.statuses if not asset_status.ready])


def _cursor_payload(
    *,
    decision: StockMinsSilverUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    raw_status: DatasetReadinessStatus | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    suspend_status: DatasetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    namechange_status: AssetReadinessStatus | None = None,
    silver_status: DatasetReadinessStatus | None = None,
    continuity_status: StockMinsContinuityStatus | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REQUEST_RUNS
        if decision.selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_trade_date:
        blocked_count += _not_ready_count(raw_status)
        blocked_count += _not_ready_count(stock_daily_status)
        blocked_count += _not_ready_count(suspend_status)
        blocked_count += 0 if identity_map_status is None or identity_map_status.ready else 1
        blocked_count += 0 if namechange_status is None or namechange_status.ready else 1
        blocked_count += _not_ready_count(silver_status)
        if continuity_status is not None and continuity_status.first_missing_registered_date:
            blocked_count += 1
        elif continuity_status is not None and continuity_status.blocked:
            blocked_count += 1
        if (
            blocked_count == 0
            and decision.target_trade_date is not None
            and not (silver_status is not None and silver_status.ready)
        ):
            blocked_count = 1
        elif blocked_count == 0 and decision.target_trade_date is None:
            blocked_count = 1

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.target_trade_date,
        selected_count=1 if decision.selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(decision.selected_trade_date,) if decision.selected_trade_date else (),
        details={
            "partition_set": cn_a_stock_mins_silver_trade_days.name,
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": decision.selected_trade_date,
            "reason": decision.reason,
            "job_name": STOCK_MINS_SILVER_SENSOR_JOB_NAME,
            "run_window_started": decision.run_window_started,
            "raw_status": status_payload(raw_status) if raw_status else None,
            "stock_daily_status": (
                status_payload(stock_daily_status) if stock_daily_status else None
            ),
            "suspend_status": status_payload(suspend_status) if suspend_status else None,
            "identity_map_status": _asset_status_payload(identity_map_status),
            "namechange_status": _asset_status_payload(namechange_status),
            "silver_status": status_payload(silver_status) if silver_status else None,
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
            subject="stock_mins_silver_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


@dg.sensor(
    job_name=STOCK_MINS_SILVER_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票分钟线 silver 分区和上游门禁就绪后，触发五频度 silver 更新任务。",
)
def stock_mins_silver_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= STOCK_MINS_SILVER_RUN_START
    expected_trade_dates = _load_stock_mins_silver_expected_trade_dates(
        context,
        evaluated_at,
    )
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=lambda trade_date: silver_stk_mins_ready_for_trade_date(
            context.instance,
            trade_date,
        ),
        has_materialized_check_problem=_has_materialized_check_problem,
    )
    continuity_status = selection.status
    target_trade_date = _target_trade_date_from_continuity_status(
        continuity_status
    )
    silver_status = (
        selection.selected_status
        if isinstance(selection.selected_status, DatasetReadinessStatus)
        else None
    )

    raw_status = None
    stock_daily_status = None
    suspend_status = None
    identity_map_status = None
    namechange_status = None
    if continuity_status.first_missing_registered_date is not None:
        decision = StockMinsSilverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason=(
                "股票分钟线 silver 交易日分区存在缺口，"
                f"最早缺失日期为 {continuity_status.first_missing_registered_date}，"
                "请先补注册 silver 分区。"
            ),
        )
    elif not run_window_started:
        decision = StockMinsSilverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="股票分钟线 silver 日常更新窗口尚未到 19:50，暂不触发。",
        )
    elif selection.selected_trade_date is None:
        if continuity_status.blocked_reason == "materialized_check_problem":
            reason = (
                "最早未就绪股票分钟线 silver 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查后修复。"
            )
        else:
            reason = "股票分钟线 silver continuity 窗口内分区已经 ready。"
        decision = StockMinsSilverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason=reason,
        )
    else:
        selected_trade_date = selection.selected_trade_date
        raw_status = raw_stk_mins_ready_for_trade_date(
            context.instance,
            selected_trade_date,
        )
        stock_daily_status = stock_daily_ready_for_trade_date(
            context.instance,
            selected_trade_date,
        )
        suspend_status = suspend_d_ready_for_trade_date(
            context.instance,
            selected_trade_date,
        )
        identity_map_status = silver_stock_identity_map_ready_for_trade_date(
            context.instance,
            selected_trade_date,
        )
        namechange_status = silver_namechange_ready_for_trade_date(
            context.instance,
            selected_trade_date,
        )

        decision = build_stock_mins_silver_update_decision(
            target_trade_date=selected_trade_date,
            run_window_started=run_window_started,
            raw_ready=raw_status.ready if raw_status else False,
            stock_daily_ready=stock_daily_status.ready if stock_daily_status else False,
            suspend_ready=suspend_status.ready if suspend_status else False,
            identity_map_ready=identity_map_status.ready if identity_map_status else False,
            namechange_ready=namechange_status.ready if namechange_status else False,
            silver_ready=silver_status.ready if silver_status else False,
            silver_has_materialized_check_problem=(
                _has_materialized_check_problem(silver_status) if silver_status else False
            ),
        )
    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        raw_status=raw_status,
        stock_daily_status=stock_daily_status,
        suspend_status=suspend_status,
        identity_map_status=identity_map_status,
        namechange_status=namechange_status,
        silver_status=silver_status,
        continuity_status=continuity_status,
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
