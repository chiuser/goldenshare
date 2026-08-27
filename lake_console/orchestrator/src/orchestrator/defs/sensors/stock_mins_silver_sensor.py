from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
    batch_raw_stk_mins_lake_readiness,
    batch_silver_stk_mins_lake_readiness,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_gate_statuses,
    compact_readiness_status,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_CONTINUITY_WINDOW_LIMIT,
    STK_MINS_SILVER_HISTORY_START_DATE,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    silver_stock_identity_map_ready_for_trade_date,
    stock_daily_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
)


STOCK_MINS_SILVER_SENSOR_JOB_NAME = "stock_mins_silver_update_job"
STOCK_MINS_SILVER_RUN_START = time(19, 15)


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


def _has_materialized_check_problem(
    status: DatasetReadinessStatus | StkMinsDateReadiness,
) -> bool:
    if isinstance(status, StkMinsDateReadiness):
        return status.materialized and not status.checks_passed
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
            reason="股票分钟线 silver 日常更新窗口尚未到 19:15，暂不触发。",
        )
    if not raw_ready:
        reason = "股票分钟线 raw 五频度尚未全部 ready，暂不触发 silver 更新。"
    elif not stock_daily_ready:
        reason = "股票日线尚未 ready，暂不触发股票分钟线 silver 更新。"
    elif not suspend_ready:
        reason = "停复牌数据尚未 ready，暂不触发股票分钟线 silver 更新。"
    elif not identity_map_ready:
        reason = "股票身份映射尚未满足当日 freshness，暂不触发股票分钟线 silver 更新。"
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
    return compact_readiness_status(status)


def _date_status_payload(status: StkMinsDateReadiness | None) -> dict[str, object] | None:
    return compact_readiness_status(status)


def _batch_status_payload(
    status: StkMinsBatchReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return compact_batch_frontier(status)


def _not_ready_count(
    status: DatasetReadinessStatus | StkMinsDateReadiness | None,
) -> int:
    if status is None or status.ready:
        return 0
    if isinstance(status, StkMinsDateReadiness):
        return max(1, len(status.failed_check_names))
    return len([asset_status for asset_status in status.statuses if not asset_status.ready])


def _cursor_summary_and_next_action(
    *,
    decision: StockMinsSilverUpdateDecision,
    reason_code: str,
    blocked_component: str | None,
) -> tuple[str, str]:
    target_trade_date = decision.target_trade_date
    if decision.selected_trade_date:
        return (
            f"已触发：提交股票分钟线 silver 五频度更新，交易日 {decision.selected_trade_date}。",
            "等待 stock_mins_silver_update_job 完成，然后查看 silver_stk_mins checks。",
        )
    if blocked_component == "cn_a_stock_mins_silver_trade_days":
        return (
            f"未触发：股票分钟线 silver 交易日分区存在缺口，目标停在 {target_trade_date}。",
            "先补齐 cn_a_stock_mins_silver_trade_days 动态分区，再等待下一次 tick。",
        )
    if blocked_component == "raw_stk_mins":
        return (
            f"未触发：股票分钟线 silver 在 {target_trade_date} 被 raw_stk_mins 阻断。",
            "先完成同日 raw_stk_mins 五频度更新与 checks，再等待下一次 tick。",
        )
    if blocked_component == "stock_daily":
        return (
            f"未触发：股票分钟线 silver 在 {target_trade_date} 被 stock_daily 阻断。",
            "先完成同日 silver_stock_daily freshness 与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "suspend_d":
        return (
            f"未触发：股票分钟线 silver 在 {target_trade_date} 被 suspend_d 阻断。",
            "先完成同日停复牌数据 freshness 与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "stock_identity_map":
        return (
            f"未触发：股票分钟线 silver 在 {target_trade_date} 被 stock_identity_map 阻断。",
            "先完成股票身份映射 freshness，再等待下一次 tick。",
        )
    if blocked_component == "silver_stk_mins":
        return (
            f"未触发：股票分钟线 silver 在 {target_trade_date} 已有未通过状态。",
            "先查看 silver_stk_mins gate_statuses 和 failed check，人工确认后再修复。",
        )
    if reason_code == "run_window_not_started":
        return (
            "未触发：股票分钟线 silver 日常更新窗口尚未开始。",
            "等到 19:15 后，下一次 tick 会重新判断是否提交更新。",
        )
    if reason_code == "no_registered_partition":
        return (
            "未触发：没有可处理的股票分钟线 silver 交易日分区。",
            "先确认 cn_a_stock_mins_silver_trade_days 是否已注册目标交易日。",
        )
    return (
        "未触发：股票分钟线 silver continuity 窗口内分区已经 ready。",
        "无需处理；等待新交易日分区或下一次更新窗口。",
    )


def _cursor_payload(
    *,
    decision: StockMinsSilverUpdateDecision,
    evaluated_at: datetime,
    raw_registered_trade_day_count: int,
    registered_trade_day_count: int,
    raw_status: StkMinsDateReadiness | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    suspend_status: DatasetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    silver_status: StkMinsDateReadiness | None = None,
    raw_continuity_status: StockMinsContinuityStatus | None = None,
    continuity_status: StockMinsContinuityStatus | None = None,
    raw_batch_status: StkMinsBatchReadiness | None = None,
    silver_batch_status: StkMinsBatchReadiness | None = None,
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

    blocked_component = None
    reason_code = None
    if continuity_status is not None:
        if continuity_status.first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_mins_silver_trade_days"
        elif continuity_status.first_not_ready_reason is not None:
            reason_code = continuity_status.first_not_ready_reason
            blocked_component = "silver_stk_mins"
        elif continuity_status.blocked_reason is not None:
            reason_code = continuity_status.blocked_reason
            blocked_component = "silver_stk_mins"
    if reason_code is None and raw_continuity_status is not None:
        if raw_continuity_status.first_missing_registered_date is not None:
            reason_code = "raw_missing_registered_partition"
            blocked_component = "raw_stk_mins"
        elif raw_continuity_status.first_not_ready_reason is not None:
            reason_code = raw_continuity_status.first_not_ready_reason
            blocked_component = "raw_stk_mins"
        elif raw_continuity_status.blocked_reason is not None:
            reason_code = f"raw_{raw_continuity_status.blocked_reason}"
            blocked_component = "raw_stk_mins"
    if reason_code is None:
        for component, status in (
            ("raw_stk_mins", raw_status),
            ("stock_daily", stock_daily_status),
            ("suspend_d", suspend_status),
            ("stock_identity_map", identity_map_status),
            ("silver_stk_mins", silver_status),
        ):
            if status is not None and not status.ready:
                reason_code = getattr(status, "reason", f"{component}_not_ready")
                blocked_component = component
                break
    if reason_code is None:
        if decision.selected_trade_date:
            reason_code = "request_run"
        elif not decision.run_window_started:
            reason_code = "run_window_not_started"
        elif decision.target_trade_date is None:
            reason_code = "no_registered_partition"
        else:
            reason_code = "all_ready"
    summary, next_action = _cursor_summary_and_next_action(
        decision=decision,
        reason_code=reason_code,
        blocked_component=blocked_component,
    )

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.target_trade_date,
        selected_count=1 if decision.selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(decision.selected_trade_date,) if decision.selected_trade_date else (),
        details=build_cursor_details(
            sensor_name="stock_mins_silver_sensor",
            job_name=STOCK_MINS_SILVER_SENSOR_JOB_NAME,
            asset_family="stock_mins_silver",
            partition_set=cn_a_stock_mins_silver_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "raw": compact_continuity_frontier(
                    raw_continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "silver": compact_continuity_frontier(
                    continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "raw_lake": _batch_status_payload(raw_batch_status),
                "silver_lake": _batch_status_payload(silver_batch_status),
            },
            gate_statuses={
                **compact_gate_statuses(
                    {
                        "raw_stk_mins": raw_status,
                        "stock_daily": stock_daily_status,
                        "suspend_d": suspend_status,
                        "stock_identity_map": identity_map_status,
                        "silver_stk_mins": silver_status,
                    }
                )
            },
            evidence={
                "raw_partition_set": cn_a_stock_mins_trade_days.name,
                "raw_registered_trade_day_count": raw_registered_trade_day_count,
                "registered_trade_day_count": registered_trade_day_count,
                "run_window_started": decision.run_window_started,
            },
        ),
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
    window_trade_dates = expected_trade_dates[-STK_MINS_CONTINUITY_WINDOW_LIMIT:]
    raw_registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_trade_days.name
            )
        )
    )
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    raw_batch_status: StkMinsBatchReadiness | None = None
    silver_batch_status: StkMinsBatchReadiness | None = None

    def _batch_raw_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness:
        nonlocal raw_batch_status
        if raw_batch_status is None:
            lake_root = context.resources.lake_root
            duckdb_resource = context.resources.duckdb
            with duckdb_resource.connect() as connection:
                raw_batch_status = batch_raw_stk_mins_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                    registered_trade_days=raw_registered_trade_days,
                    full_semantics=True,
                )
        return raw_batch_status.status_for_trade_date(trade_date)

    def _batch_silver_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness:
        nonlocal silver_batch_status
        if silver_batch_status is None:
            lake_root = context.resources.lake_root
            duckdb_resource = context.resources.duckdb
            with duckdb_resource.connect() as connection:
                silver_batch_status = batch_silver_stk_mins_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                    registered_trade_days=registered_trade_days,
                    full_semantics=True,
                )
        return silver_batch_status.status_for_trade_date(trade_date)

    selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        expected_trade_dates=window_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=_batch_silver_status_for_trade_date,
        has_materialized_check_problem=_has_materialized_check_problem,
    )
    raw_readiness_selection = (
        select_first_not_ready_trade_date(
            partition_set_name=cn_a_stock_mins_trade_days.name,
            expected_trade_dates=window_trade_dates,
            registered_trade_days=raw_registered_trade_days,
            readiness_for_trade_date=_batch_raw_status_for_trade_date,
            has_materialized_check_problem=_has_materialized_check_problem,
        )
        if selection.status.first_missing_registered_date is None
        else None
    )
    continuity_status = selection.status
    target_trade_date = _target_trade_date_from_continuity_status(
        continuity_status
    )
    silver_status = (
        selection.selected_status
        if isinstance(selection.selected_status, StkMinsDateReadiness)
        else None
    )
    raw_continuity_status = (
        raw_readiness_selection.status
        if raw_readiness_selection is not None
        else None
    )

    raw_status = None
    stock_daily_status = None
    suspend_status = None
    identity_map_status = None
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
            reason="股票分钟线 silver 日常更新窗口尚未到 19:15，暂不触发。",
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
        raw_block_trade_date = None
        if raw_continuity_status is not None:
            raw_block_trade_date = (
                raw_continuity_status.first_missing_registered_date
                or raw_continuity_status.first_not_ready_trade_date
            )
        raw_status = (
            raw_readiness_selection.selected_status
            if (
                raw_readiness_selection is not None
                and isinstance(raw_readiness_selection.selected_status, StkMinsDateReadiness)
            )
            else None
        )
        if raw_block_trade_date is not None and raw_block_trade_date <= selected_trade_date:
            if raw_status is None and raw_continuity_status.first_missing_registered_date is None:
                raw_status = _batch_raw_status_for_trade_date(raw_block_trade_date)
            decision = StockMinsSilverUpdateDecision(
                target_trade_date=raw_block_trade_date,
                run_window_started=run_window_started,
                selected_trade_date=None,
                reason=(
                    "股票分钟线 raw continuity 窗口存在缺口或未 ready 日期，"
                    f"最早日期为 {raw_block_trade_date}，"
                    "暂不提交后续 silver 更新。"
                ),
            )
        else:
            raw_status = _batch_raw_status_for_trade_date(selected_trade_date)
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

            decision = build_stock_mins_silver_update_decision(
                target_trade_date=selected_trade_date,
                run_window_started=run_window_started,
                raw_ready=raw_status.ready if raw_status else False,
                stock_daily_ready=stock_daily_status.ready if stock_daily_status else False,
                suspend_ready=suspend_status.ready if suspend_status else False,
                identity_map_ready=identity_map_status.ready if identity_map_status else False,
                silver_ready=silver_status.ready if silver_status else False,
                silver_has_materialized_check_problem=(
                    _has_materialized_check_problem(silver_status)
                    if silver_status
                    else False
                ),
            )
    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        raw_registered_trade_day_count=len(raw_registered_trade_days),
        registered_trade_day_count=len(registered_trade_days),
        raw_status=raw_status,
        stock_daily_status=stock_daily_status,
        suspend_status=suspend_status,
        identity_map_status=identity_map_status,
        silver_status=silver_status,
        raw_continuity_status=raw_continuity_status,
        continuity_status=continuity_status,
        raw_batch_status=raw_batch_status,
        silver_batch_status=silver_batch_status,
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
