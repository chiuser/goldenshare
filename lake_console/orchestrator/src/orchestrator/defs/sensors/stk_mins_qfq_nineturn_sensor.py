"""Bounded sensor for the four minute QFQ nine-turn Gold assets."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    build_registered_gap_status,
)
from orchestrator.defs.asset_guards.qfq_nineturn_lake_readiness import (
    batch_gold_stk_mins_qfq_nineturn_readiness,
    batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness,
)
from orchestrator.defs.asset_guards.stk_mins_continuity import (
    load_stock_mins_expected_trade_dates,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.jobs.stk_mins_qfq_nineturn_update import (
    gold_stk_mins_qfq_nineturn_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_SENSOR_WINDOW_MINUTE,
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
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
)


SENSOR_NAME = "gold_stk_mins_qfq_nineturn_update_job_sensor"
JOB_NAME = "gold_stk_mins_qfq_nineturn_update_job"


def _compact_date_status(
    status: StkMinsDateReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "trade_date": status.trade_date,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "reason": status.reason,
        "failed_check_names": list(status.failed_check_names[:3]),
        "expected_file_count": status.expected_file_count,
        "existing_file_count": status.existing_file_count,
    }


def _compact_repair_status(
    status: GoldStkMinsQfqFactorRepairStatus | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "trade_date": status.trade_date,
        "ready": status.ready,
        "reason": status.reason,
        "repair_required": status.repair_required,
        "repair_required_code_count": status.repair_required_code_count,
    }


def _load_expected_trade_dates(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.is_file():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")
    connect_duckdb = context.resources.duckdb.connect
    with connect_duckdb() as connection:
        expected_dates = load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_QFQ_HISTORY_START_DATE,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
        )
    return expected_dates[-QFQ_NINETURN_SENSOR_WINDOW_MINUTE:]


def _first_not_ready(
    batch_status: StkMinsBatchReadiness,
    trade_dates: tuple[str, ...],
) -> tuple[str | None, StkMinsDateReadiness | None]:
    for trade_date in trade_dates:
        status = batch_status.status_for_trade_date(trade_date)
        if not status.ready:
            return trade_date, status
    return None, None


def _previous_trade_date(
    registered_trade_dates: tuple[str, ...],
    target_trade_date: str,
) -> str | None:
    previous = None
    for trade_date in registered_trade_dates:
        if trade_date >= target_trade_date:
            break
        previous = trade_date
    return previous


def _previous_partition_status(
    context: dg.SensorEvaluationContext,
    *,
    previous_trade_date: str | None,
    target_batch_status: StkMinsBatchReadiness,
    target_window_dates: tuple[str, ...],
    registered_trade_dates: tuple[str, ...],
) -> StkMinsDateReadiness | None:
    if previous_trade_date is None:
        return None
    if previous_trade_date in target_window_dates:
        return target_batch_status.status_for_trade_date(previous_trade_date)
    connect_duckdb = context.resources.duckdb.connect
    with connect_duckdb() as connection:
        previous_batch = batch_gold_stk_mins_qfq_nineturn_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=(previous_trade_date,),
            registered_trade_days=registered_trade_dates,
        )
    return previous_batch.status_for_trade_date(previous_trade_date)


def _cursor(
    *,
    evaluated_at: datetime,
    target_date: str | None,
    selected_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    registered_count: int,
    target_batch_status: StkMinsBatchReadiness | None = None,
    target_status: StkMinsDateReadiness | None = None,
    upstream_batch_status: StkMinsBatchReadiness | None = None,
    upstream_status: StkMinsDateReadiness | None = None,
    repair_status: GoldStkMinsQfqFactorRepairStatus | None = None,
    previous_status: StkMinsDateReadiness | None = None,
) -> str:
    gate_statuses = {
        key: value
        for key, value in (
            ("target", _compact_date_status(target_status)),
            ("gold_stk_mins_qfq", _compact_date_status(upstream_status)),
            ("factor_repair", _compact_repair_status(repair_status)),
            ("previous_partition", _compact_date_status(previous_status)),
        )
        if value is not None
    }
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_date is not None
            else SensorCursorDecision.SKIP
        ),
        target_date=selected_date or target_date,
        selected_count=1 if selected_date is not None else 0,
        blocked_count=(
            0 if selected_date is not None or reason_code == "all_ready" else 1
        ),
        sample_keys=(selected_date or target_date,)
        if selected_date or target_date
        else (),
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=JOB_NAME,
            asset_family="stk_mins_qfq_nineturn",
            partition_set=cn_a_stock_mins_silver_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "target": compact_batch_frontier(
                    target_batch_status,
                    selected_trade_date=selected_date,
                ),
                "upstream_qfq": compact_batch_frontier(upstream_batch_status),
            },
            gate_statuses=gate_statuses,
            evidence={
                "registered_count": registered_count,
                "repair_required": (
                    repair_status.repair_required
                    if repair_status is not None
                    else None
                ),
                "repair_required_code_count": (
                    repair_status.repair_required_code_count
                    if repair_status is not None
                    else None
                ),
            },
            performance_ms={
                "target_readiness": (
                    target_batch_status.elapsed_ms
                    if target_batch_status is not None
                    else None
                ),
                "upstream_qfq": (
                    upstream_batch_status.elapsed_ms
                    if upstream_batch_status is not None
                    else None
                ),
            },
        ),
    )


def _result(
    *,
    evaluated_at: datetime,
    target_date: str | None,
    selected_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    registered_count: int,
    target_batch_status: StkMinsBatchReadiness | None = None,
    target_status: StkMinsDateReadiness | None = None,
    upstream_batch_status: StkMinsBatchReadiness | None = None,
    upstream_status: StkMinsDateReadiness | None = None,
    repair_status: GoldStkMinsQfqFactorRepairStatus | None = None,
    previous_status: StkMinsDateReadiness | None = None,
) -> dg.SensorResult:
    cursor = _cursor(
        evaluated_at=evaluated_at,
        target_date=target_date,
        selected_date=selected_date,
        reason_code=reason_code,
        blocked_component=blocked_component,
        summary=summary,
        next_action=next_action,
        registered_count=registered_count,
        target_batch_status=target_batch_status,
        target_status=target_status,
        upstream_batch_status=upstream_batch_status,
        upstream_status=upstream_status,
        repair_status=repair_status,
        previous_status=previous_status,
    )
    if selected_date is None:
        return dg.SensorResult(skip_reason=summary, cursor=cursor)
    return dg.SensorResult(
        run_requests=[
            build_run_request(
                run_key=build_asset_update_run_key(
                    subject="gold_stk_mins_qfq_nineturn_update",
                    unit_id=selected_date,
                ),
                partition_key=selected_date,
            )
        ],
        cursor=cursor,
    )


@dg.sensor(
    job=gold_stk_mins_qfq_nineturn_update_job,
    name=SENSOR_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "四频度分钟前复权行情、因子修复和上一九转分区就绪后，按 first-not-ready 触发分钟前复权九转更新。"
    ),
)
def gold_stk_mins_qfq_nineturn_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    expected_dates = _load_expected_trade_dates(context, evaluated_at)
    registered = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    if not expected_dates:
        return _result(
            evaluated_at=evaluated_at,
            target_date=None,
            selected_date=None,
            reason_code="no_expected_trade_dates",
            blocked_component=cn_a_stock_mins_silver_trade_days.name,
            summary="未触发：交易日历没有可评估的分钟线交易日。",
            next_action="检查 silver_trade_calendar 后等待下一次 tick。",
            registered_count=len(registered),
        )

    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_dates,
        registered_trade_dates=registered,
    )
    if gap_status.has_internal_gap:
        missing_date = gap_status.first_internal_missing_date
        return _result(
            evaluated_at=evaluated_at,
            target_date=missing_date,
            selected_date=None,
            reason_code="missing_registered_partition",
            blocked_component=cn_a_stock_mins_silver_trade_days.name,
            summary=f"未触发：分钟线 Silver 交易日分区存在缺口，首个缺失日期为 {missing_date}。",
            next_action="先补齐 cn_a_stock_mins_silver_trade_days，再等待下一次 tick。",
            registered_count=len(registered),
        )
    actionable_dates = gap_status.actionable_expected_trade_dates
    if not actionable_dates:
        target_date = gap_status.first_trailing_unregistered_date
        return _result(
            evaluated_at=evaluated_at,
            target_date=target_date,
            selected_date=None,
            reason_code="pending_registered_partition_tail",
            blocked_component=cn_a_stock_mins_silver_trade_days.name,
            summary=f"未触发：尾部分钟线交易日 {target_date} 尚未注册。",
            next_action="等待分钟线 Silver 交易日分区注册后由下一次 tick 重试。",
            registered_count=len(registered),
        )

    connect_duckdb = context.resources.duckdb.connect
    with connect_duckdb() as connection:
        target_batch = batch_gold_stk_mins_qfq_nineturn_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=actionable_dates,
            registered_trade_days=registered,
        )
    target_date, target_status = _first_not_ready(target_batch, actionable_dates)
    if target_date is None:
        reason_code = (
            "pending_registered_partition_tail"
            if gap_status.first_trailing_unregistered_date is not None
            else "all_ready"
        )
        return _result(
            evaluated_at=evaluated_at,
            target_date=(
                gap_status.first_trailing_unregistered_date or expected_dates[-1]
            ),
            selected_date=None,
            reason_code=reason_code,
            blocked_component=(
                cn_a_stock_mins_silver_trade_days.name
                if reason_code == "pending_registered_partition_tail"
                else "none"
            ),
            summary=(
                "未触发：已注册的分钟前复权九转分区均已 ready，等待尾部分区注册。"
                if reason_code == "pending_registered_partition_tail"
                else "未触发：最近 5 个分钟前复权九转分区均已 ready。"
            ),
            next_action="无需修复；等待新的已注册交易日。",
            registered_count=len(registered),
            target_batch_status=target_batch,
        )
    if target_status.materialized and not target_status.checks_passed:
        return _result(
            evaluated_at=evaluated_at,
            target_date=target_date,
            selected_date=None,
            reason_code="target_check_failed",
            blocked_component="target_qfq_nineturn_check",
            summary=f"未触发：{target_date} 的分钟九转文件已生成，但聚合 check 未通过。",
            next_action="查看四频度 check metadata，人工修复后再继续。",
            registered_count=len(registered),
            target_batch_status=target_batch,
            target_status=target_status,
        )

    connect_duckdb = context.resources.duckdb.connect
    with connect_duckdb() as connection:
        upstream_batch = batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=(target_date,),
            registered_trade_days=registered,
            full_semantics=True,
        )
    upstream_status = upstream_batch.status_for_trade_date(target_date)
    if not upstream_status.ready:
        return _result(
            evaluated_at=evaluated_at,
            target_date=target_date,
            selected_date=None,
            reason_code="upstream_qfq_not_ready",
            blocked_component="gold_stk_mins_qfq",
            summary=f"未触发：{target_date} 的 30/60/90/120m 前复权行情尚未全部 ready。",
            next_action="先完成所需四频度 QFQ 及 blocking checks。",
            registered_count=len(registered),
            target_batch_status=target_batch,
            target_status=target_status,
            upstream_batch_status=upstream_batch,
            upstream_status=upstream_status,
        )

    repair_status = gold_stk_mins_qfq_factor_repair_status(
        context.instance,
        target_date,
        include_event_storage_ids=False,
    )
    if not repair_status.ready:
        return _result(
            evaluated_at=evaluated_at,
            target_date=target_date,
            selected_date=None,
            reason_code="factor_repair_not_ready",
            blocked_component="gold_stk_mins_qfq_factor_repair",
            summary=f"未触发：{target_date} 的分钟 QFQ factor repair 最终状态尚未 ready。",
            next_action="先完成同日 stock_mins_qfq_factor_repair_job。",
            registered_count=len(registered),
            target_batch_status=target_batch,
            target_status=target_status,
            upstream_batch_status=upstream_batch,
            upstream_status=upstream_status,
            repair_status=repair_status,
        )

    previous_date = _previous_trade_date(registered, target_date)
    previous_status = _previous_partition_status(
        context,
        previous_trade_date=previous_date,
        target_batch_status=target_batch,
        target_window_dates=actionable_dates,
        registered_trade_dates=registered,
    )
    if previous_status is not None and not previous_status.ready:
        return _result(
            evaluated_at=evaluated_at,
            target_date=target_date,
            selected_date=None,
            reason_code="previous_partition_not_ready",
            blocked_component="previous_qfq_nineturn_partition",
            summary=f"未触发：{target_date} 的上一分钟九转分区 {previous_date} 尚未 ready。",
            next_action="先补齐或修复上一九转分区，再等待下一次 tick。",
            registered_count=len(registered),
            target_batch_status=target_batch,
            target_status=target_status,
            upstream_batch_status=upstream_batch,
            upstream_status=upstream_status,
            repair_status=repair_status,
            previous_status=previous_status,
        )

    return _result(
        evaluated_at=evaluated_at,
        target_date=target_date,
        selected_date=target_date,
        reason_code="request_run",
        blocked_component="none",
        summary=f"已触发：提交 {target_date} 的四频度分钟前复权九转更新。",
        next_action="等待 run 和四条聚合 checks 完成。",
        registered_count=len(registered),
        target_batch_status=target_batch,
        target_status=target_status,
        upstream_batch_status=upstream_batch,
        upstream_status=upstream_status,
        repair_status=repair_status,
        previous_status=previous_status,
    )
