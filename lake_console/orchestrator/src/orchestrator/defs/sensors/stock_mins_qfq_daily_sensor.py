from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    batch_adj_factor_lake_readiness,
)
from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
    batch_gold_stk_mins_qfq_lake_readiness,
    batch_silver_stk_mins_lake_readiness,
)
from orchestrator.defs.partitions import (
    cn_a_stock_current_trade_days,
    cn_a_stock_mins_silver_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_gate_statuses,
    compact_readiness_status,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_HISTORY_START_DATE
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
)


STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME = "stock_mins_qfq_daily_update_job"
STOCK_MINS_QFQ_DAILY_RUN_START = time(19, 30)
STOCK_MINS_QFQ_DAILY_READINESS_WINDOW_LIMIT = 5


@dataclass(frozen=True)
class StockMinsQfqDailyUpdateDecision:
    target_trade_date: str | None
    run_window_started: bool
    selected_trade_date: str | None
    reason: str


@dataclass(frozen=True)
class StockMinsQfqDailyReadinessSnapshot:
    ready: bool
    reason: str
    silver_status: StkMinsDateReadiness | DatasetReadinessStatus | None = None
    adj_factor_status: (
        StkMinsDateReadiness
        | ContinuityDateReadiness
        | DatasetReadinessStatus
        | None
    ) = None
    gold_status: StkMinsDateReadiness | DatasetReadinessStatus | None = None


def _load_stock_mins_qfq_expected_trade_dates(
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
            min_trade_date=STK_MINS_QFQ_HISTORY_START_DATE,
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
    status: StkMinsDateReadiness | ContinuityDateReadiness | DatasetReadinessStatus,
) -> bool:
    if isinstance(status, (StkMinsDateReadiness, ContinuityDateReadiness)):
        return status.materialized and not status.checks_passed
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def _qfq_daily_snapshot_has_materialized_check_problem(
    snapshot: StockMinsQfqDailyReadinessSnapshot,
) -> bool:
    return any(
        status is not None and _has_materialized_check_problem(status)
        for status in (
            snapshot.silver_status,
            snapshot.adj_factor_status,
            snapshot.gold_status,
        )
    )


def _readiness_status_payload(
    status: (
        StkMinsDateReadiness | ContinuityDateReadiness | DatasetReadinessStatus | None
    ),
) -> dict[str, object] | None:
    return compact_readiness_status(status)


def _batch_status_payload(
    batch_status: StkMinsBatchReadiness | ContinuityBatchReadiness | None,
) -> dict[str, object] | None:
    if batch_status is None:
        return None
    return compact_batch_frontier(batch_status)


def build_stock_mins_qfq_daily_update_decision(
    *,
    target_trade_date: str | None,
    run_window_started: bool,
    silver_ready: bool = False,
    adj_factor_ready: bool = False,
    gold_ready: bool = False,
    gold_has_materialized_check_problem: bool = False,
) -> StockMinsQfqDailyUpdateDecision:
    if target_trade_date is None:
        return StockMinsQfqDailyUpdateDecision(
            target_trade_date=None,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason="没有注册股票分钟线 silver 交易日分区，无法触发 gold qfq 更新。",
        )
    if not run_window_started:
        return StockMinsQfqDailyUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="股票分钟线 gold qfq 日常更新窗口尚未到 19:30，暂不触发。",
        )
    if not silver_ready:
        reason = "股票分钟线 silver 五频度尚未全部 ready，暂不触发 gold qfq 更新。"
    elif not adj_factor_ready:
        reason = "当日复权因子尚未 ready，暂不触发股票分钟线 gold qfq 更新。"
    elif gold_ready:
        reason = "最新股票分钟线 gold qfq 交易日的七频度分区已经 ready。"
    elif gold_has_materialized_check_problem:
        reason = (
            "最新股票分钟线 gold qfq 分区已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
    else:
        return StockMinsQfqDailyUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=target_trade_date,
            reason="股票分钟线 gold qfq 门禁已满足，提交七频度 qfq 更新。",
        )

    return StockMinsQfqDailyUpdateDecision(
        target_trade_date=target_trade_date,
        run_window_started=True,
        selected_trade_date=None,
        reason=reason,
    )


def _not_ready_count(
    status: (
        StkMinsDateReadiness | ContinuityDateReadiness | DatasetReadinessStatus | None
    ),
) -> int:
    if status is None or status.ready:
        return 0
    if isinstance(status, (StkMinsDateReadiness, ContinuityDateReadiness)):
        return 1
    return len([asset_status for asset_status in status.statuses if not asset_status.ready])


def _blocked_component_for_cursor(
    *,
    silver_status: StkMinsDateReadiness | DatasetReadinessStatus | None,
    adj_factor_status: (
        StkMinsDateReadiness
        | ContinuityDateReadiness
        | DatasetReadinessStatus
        | None
    ),
    gold_status: StkMinsDateReadiness | DatasetReadinessStatus | None,
) -> str | None:
    for component, status in (
        ("silver_stk_mins", silver_status),
        ("adj_factor", adj_factor_status),
        ("gold_stk_mins_qfq", gold_status),
    ):
        if status is not None and not status.ready:
            return component
    return None


def _cursor_summary_and_next_action(
    *,
    decision: StockMinsQfqDailyUpdateDecision,
    reason_code: str,
    blocked_component: str | None,
    already_submitted_for_trade_date: bool,
) -> tuple[str, str]:
    target_trade_date = decision.target_trade_date
    if decision.selected_trade_date:
        return (
            f"已触发：提交股票分钟线 gold qfq 七频度更新，交易日 {decision.selected_trade_date}。",
            "等待 stock_mins_qfq_daily_update_job 完成，然后查看 gold_stk_mins_qfq checks。",
        )
    if already_submitted_for_trade_date:
        return (
            f"未触发：股票分钟线 gold qfq 在 {target_trade_date} 已经提交过 run。",
            "如上一轮 run 失败，请在 Dagster run 页面人工 retry，不由 sensor 重复提交。",
        )
    if reason_code == "missing_registered_partition":
        return (
            f"未触发：股票分钟线 qfq 交易日分区存在缺口，目标停在 {target_trade_date}。",
            "先补齐 cn_a_stock_mins_silver_trade_days 动态分区，再等待下一次 tick。",
        )
    if blocked_component == "silver_stk_mins":
        return (
            f"未触发：gold qfq 在 {target_trade_date} 被 silver_stk_mins 阻断。",
            "先完成同日 silver_stk_mins 五频度更新与 checks，再等待下一次 tick。",
        )
    if blocked_component == "adj_factor":
        return (
            f"未触发：gold qfq 在 {target_trade_date} 被 adj_factor 阻断。",
            "先完成同日 silver_adj_factor 更新与 checks，再等待下一次 tick。",
        )
    if blocked_component == "gold_stk_mins_qfq":
        return (
            f"未触发：gold qfq 在 {target_trade_date} 已有未通过状态。",
            "先查看 gold_stk_mins_qfq gate_statuses 和 failed check，人工确认后再修复。",
        )
    if reason_code == "run_window_not_started":
        return (
            "未触发：股票分钟线 gold qfq 日常更新窗口尚未开始。",
            "等到 19:30 后，下一次 tick 会重新判断是否提交更新。",
        )
    if reason_code == "no_registered_partition":
        return (
            "未触发：没有可处理的股票分钟线 qfq 交易日分区。",
            "先确认 cn_a_stock_mins_silver_trade_days 是否已注册目标交易日。",
        )
    return (
        "未触发：股票分钟线 gold qfq continuity 窗口内分区已经 ready。",
        "无需处理；等待新交易日分区或后续 factor repair 检测。",
    )


def _cursor_reason_code(
    *,
    decision: StockMinsQfqDailyUpdateDecision,
    continuity_status: StockMinsContinuityStatus | None,
    silver_status: StkMinsDateReadiness | DatasetReadinessStatus | None,
    adj_factor_status: (
        StkMinsDateReadiness
        | ContinuityDateReadiness
        | DatasetReadinessStatus
        | None
    ),
    gold_status: StkMinsDateReadiness | DatasetReadinessStatus | None,
    already_submitted_for_trade_date: bool,
) -> str:
    if decision.selected_trade_date:
        return "request_run"
    if already_submitted_for_trade_date:
        return "already_submitted_for_trade_date"
    if not decision.run_window_started:
        return "run_window_not_started"
    if continuity_status is not None:
        if continuity_status.first_missing_registered_date is not None:
            return "missing_registered_partition"
        if continuity_status.first_not_ready_reason is not None:
            return continuity_status.first_not_ready_reason
        if continuity_status.blocked_reason is not None:
            return continuity_status.blocked_reason
    blocked_component = _blocked_component_for_cursor(
        silver_status=silver_status,
        adj_factor_status=adj_factor_status,
        gold_status=gold_status,
    )
    if blocked_component is not None:
        return f"{blocked_component}_not_ready"
    if decision.target_trade_date is None:
        return "no_registered_partition"
    return "all_ready"


def _cursor_payload(
    *,
    decision: StockMinsQfqDailyUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    silver_status: StkMinsDateReadiness | DatasetReadinessStatus | None = None,
    adj_factor_status: (
        StkMinsDateReadiness
        | ContinuityDateReadiness
        | DatasetReadinessStatus
        | None
    ) = None,
    gold_status: StkMinsDateReadiness | DatasetReadinessStatus | None = None,
    silver_batch_status: StkMinsBatchReadiness | None = None,
    adj_factor_batch_status: ContinuityBatchReadiness | None = None,
    gold_batch_status: StkMinsBatchReadiness | None = None,
    already_submitted_for_trade_date: bool = False,
    continuity_status: StockMinsContinuityStatus | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REQUEST_RUNS
        if decision.selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_trade_date:
        blocked_count += _not_ready_count(silver_status)
        blocked_count += _not_ready_count(adj_factor_status)
        blocked_count += _not_ready_count(gold_status)
        if continuity_status is not None and continuity_status.first_missing_registered_date:
            blocked_count += 1
        elif continuity_status is not None and continuity_status.blocked:
            blocked_count += 1
        if blocked_count == 0 and decision.target_trade_date is None:
            blocked_count = 1

    reason_code = _cursor_reason_code(
        decision=decision,
        continuity_status=continuity_status,
        silver_status=silver_status,
        adj_factor_status=adj_factor_status,
        gold_status=gold_status,
        already_submitted_for_trade_date=already_submitted_for_trade_date,
    )
    blocked_component = _blocked_component_for_cursor(
        silver_status=silver_status,
        adj_factor_status=adj_factor_status,
        gold_status=gold_status,
    )
    summary, next_action = _cursor_summary_and_next_action(
        decision=decision,
        reason_code=reason_code,
        blocked_component=blocked_component,
        already_submitted_for_trade_date=already_submitted_for_trade_date,
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.target_trade_date,
        selected_count=1 if decision.selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(decision.selected_trade_date,) if decision.selected_trade_date else (),
        details=build_cursor_details(
            sensor_name="stock_mins_qfq_daily_update_job_sensor",
            job_name=STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
            asset_family="stock_mins_qfq",
            partition_set=cn_a_stock_mins_silver_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": compact_continuity_frontier(
                    continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "silver": _batch_status_payload(silver_batch_status),
                "adj_factor": _batch_status_payload(adj_factor_batch_status),
                "gold": _batch_status_payload(gold_batch_status),
            },
            gate_statuses=compact_gate_statuses(
                {
                    "silver_stk_mins": silver_status,
                    "adj_factor": adj_factor_status,
                    "gold_stk_mins_qfq": gold_status,
                }
            ),
            evidence={
                "registered_trade_day_count": registered_trade_day_count,
                "run_window_started": decision.run_window_started,
            },
            runtime_state={
                "selected_trade_date": decision.selected_trade_date,
                "already_submitted_for_trade_date": already_submitted_for_trade_date,
            },
        ),
    )


def _window_not_started_cursor_payload(
    *,
    evaluated_at: datetime,
    reason: str,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.SKIP,
        target_date=None,
        selected_count=0,
        blocked_count=0,
        sample_keys=(),
        details=build_cursor_details(
            sensor_name="stock_mins_qfq_daily_update_job_sensor",
            job_name=STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
            asset_family="stock_mins_qfq",
            partition_set=cn_a_stock_mins_silver_trade_days.name,
            reason_code="run_window_not_started",
            blocked_component="run_window",
            summary=reason,
            next_action="等待 19:30 后由下一次 sensor tick 自动重试。",
            evidence={"run_window_started": False},
        ),
    )


def _run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="stock_mins_qfq_daily_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _already_submitted_for_target_date(
    cursor: str | None,
    target_trade_date: str,
) -> bool:
    cursor_payload = load_sensor_cursor(cursor)
    details = sensor_cursor_details(cursor_payload)
    runtime_state = cursor_runtime_state(details)
    if (
        (
            runtime_state.get("selected_trade_date")
            or details.get("selected_trade_date")
        )
        == target_trade_date
        and (
            runtime_state.get("already_submitted_for_trade_date")
            if "already_submitted_for_trade_date" in runtime_state
            else details.get("already_submitted_for_trade_date")
        )
        is True
    ):
        return True

    if cursor_payload.get("target_date") != target_trade_date:
        return False
    if cursor_payload.get("decision") != SensorCursorDecision.REQUEST_RUNS.value:
        return False

    selected_count = cursor_payload.get("selected_count")
    if (
        isinstance(selected_count, int)
        and not isinstance(selected_count, bool)
        and selected_count > 0
    ):
        return True

    sample_keys = cursor_payload.get("sample_keys")
    return isinstance(sample_keys, list) and target_trade_date in sample_keys


@dg.sensor(
    job_name=STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票分钟线 silver 和复权因子就绪后，触发七频度 gold qfq 更新任务。",
)
def stock_mins_qfq_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= STOCK_MINS_QFQ_DAILY_RUN_START
    if not run_window_started:
        reason = "股票分钟线 gold qfq 日常更新窗口尚未到 19:30，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_window_not_started_cursor_payload(
                evaluated_at=evaluated_at,
                reason=reason,
            ),
        )

    expected_trade_dates = _load_stock_mins_qfq_expected_trade_dates(
        context,
        evaluated_at,
    )
    window_trade_dates = expected_trade_dates[
        -STOCK_MINS_QFQ_DAILY_READINESS_WINDOW_LIMIT:
    ]
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    registered_stock_current_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
        )
    )
    silver_batch_status: StkMinsBatchReadiness | None = None
    adj_factor_batch_status: ContinuityBatchReadiness | None = None
    gold_batch_status: StkMinsBatchReadiness | None = None

    def _batch_readiness_for_trade_date(
        trade_date: str,
    ) -> StockMinsQfqDailyReadinessSnapshot:
        nonlocal silver_batch_status, adj_factor_batch_status, gold_batch_status
        lake_root = context.resources.lake_root
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            if silver_batch_status is None:
                silver_batch_status = batch_silver_stk_mins_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                    registered_trade_days=registered_trade_days,
                    full_semantics=True,
                )
            silver_status = silver_batch_status.status_for_trade_date(trade_date)
            if not silver_status.ready:
                return StockMinsQfqDailyReadinessSnapshot(
                    ready=False,
                    reason=silver_status.reason,
                    silver_status=silver_status,
                )

            if adj_factor_batch_status is None:
                adj_factor_batch_status = batch_adj_factor_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                    registered_trade_days=registered_stock_current_trade_days,
                    full_semantics=True,
                )
            adj_factor_status = adj_factor_batch_status.status_for_trade_date(
                trade_date
            )
            if not adj_factor_status.ready:
                return StockMinsQfqDailyReadinessSnapshot(
                    ready=False,
                    reason=adj_factor_status.reason,
                    silver_status=silver_status,
                    adj_factor_status=adj_factor_status,
                )

            if gold_batch_status is None:
                gold_batch_status = batch_gold_stk_mins_qfq_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                    registered_trade_days=registered_trade_days,
                    full_semantics=True,
                )
            gold_status = gold_batch_status.status_for_trade_date(trade_date)
        return StockMinsQfqDailyReadinessSnapshot(
            ready=gold_status.ready,
            reason=gold_status.reason,
            silver_status=silver_status,
            adj_factor_status=adj_factor_status,
            gold_status=gold_status,
        )

    selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        expected_trade_dates=window_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=_batch_readiness_for_trade_date,
        has_materialized_check_problem=(
            _qfq_daily_snapshot_has_materialized_check_problem
        ),
    )
    continuity_status = selection.status
    target_trade_date = _target_trade_date_from_continuity_status(
        continuity_status
    )
    readiness_snapshot = (
        selection.selected_status
        if isinstance(selection.selected_status, StockMinsQfqDailyReadinessSnapshot)
        else None
    )

    silver_status = readiness_snapshot.silver_status if readiness_snapshot else None
    adj_factor_status = (
        readiness_snapshot.adj_factor_status if readiness_snapshot else None
    )
    gold_status = readiness_snapshot.gold_status if readiness_snapshot else None
    already_submitted_for_trade_date = False
    if continuity_status.first_missing_registered_date is not None:
        decision = StockMinsQfqDailyUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason=(
                "股票分钟线 silver 交易日分区存在缺口，"
                f"最早缺失日期为 {continuity_status.first_missing_registered_date}，"
                "请先补注册 silver 分区。"
            ),
        )
    elif selection.selected_trade_date is None:
        if continuity_status.blocked_reason == "materialized_check_problem":
            reason = (
                "最早未就绪股票分钟线 gold qfq 分区已生成过，但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查后修复。"
            )
        else:
            reason = "股票分钟线 gold qfq continuity 窗口内分区已经 ready。"
        decision = StockMinsQfqDailyUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason=reason,
        )
    else:
        selected_trade_date = selection.selected_trade_date
        if _already_submitted_for_target_date(context.cursor, selected_trade_date):
            already_submitted_for_trade_date = True
            decision = StockMinsQfqDailyUpdateDecision(
                target_trade_date=selected_trade_date,
                run_window_started=True,
                selected_trade_date=None,
                reason=(
                    "最新股票分钟线 gold qfq 交易日已经提交过 qfq daily run，"
                    "失败时请人工 retry。"
                ),
            )
        else:
            decision = build_stock_mins_qfq_daily_update_decision(
                target_trade_date=selected_trade_date,
                run_window_started=run_window_started,
                silver_ready=silver_status.ready if silver_status else False,
                adj_factor_ready=adj_factor_status.ready if adj_factor_status else False,
                gold_ready=gold_status.ready if gold_status else False,
                gold_has_materialized_check_problem=(
                    _has_materialized_check_problem(gold_status) if gold_status else False
                ),
            )

    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        silver_status=silver_status,
        adj_factor_status=adj_factor_status,
        gold_status=gold_status,
        silver_batch_status=silver_batch_status,
        adj_factor_batch_status=adj_factor_batch_status,
        gold_batch_status=gold_batch_status,
        already_submitted_for_trade_date=(
            already_submitted_for_trade_date or bool(decision.selected_trade_date)
        ),
        continuity_status=continuity_status,
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
