from datetime import datetime

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
)
from orchestrator.defs.asset_guards.stk_mins_prod_readiness import (
    StkMinsProdSourceReadiness,
    stk_mins_prod_source_ready_for_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    load_current_listed_stock_codes_for_stk_mins,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.configs import (
    build_stock_mins_raw_update_job_run_config,
)
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
    STK_MINS_RAW_HISTORY_START_DATE,
    STK_MINS_RAW_RUN_START as STOCK_MINS_RAW_RUN_START,
    STK_MINS_RAW_SENSOR_MINIMUM_INTERVAL_SECONDS,
    ProdStkMinsCompletionReference,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    stock_basic_ready_for_trade_date,
)
from orchestrator.defs.sensors.stock_mins_trade_day_sensor import (
    STOCK_MINS_TRADE_DAY_REGISTER_START,
)


STOCK_MINS_RAW_SENSOR_JOB_NAME = "stock_mins_raw_update_from_prod_job"
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
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )

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


def _has_materialized_check_problem(
    status: DatasetReadinessStatus | StkMinsDateReadiness,
) -> bool:
    if isinstance(status, StkMinsDateReadiness):
        return status.materialized and not status.checks_passed
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def _raw_status_payload(
    status: DatasetReadinessStatus | StkMinsDateReadiness | None,
) -> list[dict[str, object]] | dict[str, object] | None:
    return compact_readiness_status(status)


def _cursor_summary_and_next_action(
    *,
    selected_trade_date: str | None,
    target_trade_date: str | None,
    reason_code: str,
    blocked_component: str | None,
) -> tuple[str, str]:
    if selected_trade_date:
        return (
            f"已触发：提交股票分钟线 raw 五频度更新，交易日 {selected_trade_date}。",
            "等待 stock_mins_raw_update_from_prod_job 完成，然后查看 raw_stk_mins checks。",
        )
    if blocked_component == "cn_a_stock_mins_trade_days":
        return (
            f"未触发：股票分钟线 raw 交易日分区存在缺口，目标停在 {target_trade_date}。",
            "先补齐 cn_a_stock_mins_trade_days 动态分区，再等待下一次 tick。",
        )
    if blocked_component == "stock_basic":
        return (
            f"未触发：股票分钟线 raw 在 {target_trade_date} 被 stock_basic 阻断。",
            "先完成 stock_basic freshness 与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "raw_stk_mins":
        return (
            f"未触发：股票分钟线 raw 在 {target_trade_date} 已有未通过状态。",
            "先查看 raw_stk_mins gate_statuses 和 failed check，人工确认后再修复。",
        )
    if blocked_component == "prod_ops_task_run":
        return (
            f"未触发：股票分钟线 raw 在 {target_trade_date} 等待 prod 全市场完成记录。",
            "等待 prod 的 stk_mins 全市场任务成功结束后，15 分钟后重新检查。",
        )
    if blocked_component == "prod_stk_mins_coverage":
        return (
            f"未触发：股票分钟线 raw 在 {target_trade_date} 的 prod 五频度代码覆盖尚未完整。",
            "等待 prod 补齐缺失代码后，15 分钟后重新检查。",
        )
    if blocked_component == "historical_raw_recovery":
        return (
            f"未触发：股票分钟线 raw 的 {target_trade_date} 已错过当日自动窗口。",
            "不要自动补跑；请使用受控 stk_mins raw recovery 流程处理历史缺口。",
        )
    if reason_code == "run_window_not_started":
        return (
            "未触发：股票分钟线 raw 日常更新窗口尚未开始。",
            f"等到 {STOCK_MINS_RAW_RUN_START.strftime('%H:%M')} 后，下一次 tick 会重新判断是否提交更新。",
        )
    if reason_code == "no_registered_partition":
        return (
            "未触发：没有可处理的股票分钟线 raw 交易日分区。",
            "先确认 cn_a_stock_mins_trade_days 是否已注册目标交易日。",
        )
    return (
        "未触发：股票分钟线 raw continuity 窗口内分区已经 ready。",
        "无需处理；等待新交易日分区或下一次更新窗口。",
    )


def _cursor_payload(
    *,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason: str,
    source_window_started: bool,
    raw_status: DatasetReadinessStatus | StkMinsDateReadiness | None = None,
    stock_basic_status: DatasetReadinessStatus | None = None,
    continuity_status: StockMinsContinuityStatus | None = None,
    raw_batch_status: StkMinsBatchReadiness | None = None,
    prod_source_status: StkMinsProdSourceReadiness | None = None,
    blocked_fallback: int = 0,
    reason_code_override: str | None = None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not selected_trade_date:
        if raw_status is not None and not raw_status.ready:
            if isinstance(raw_status, StkMinsDateReadiness):
                blocked_count = max(1, len(raw_status.failed_check_names))
            else:
                blocked_count = len(
                    [
                        asset_status
                        for asset_status in raw_status.statuses
                        if not asset_status.ready
                    ]
                )
        elif stock_basic_status is not None and not stock_basic_status.ready:
            blocked_count = 1
        elif prod_source_status is not None and not prod_source_status.ready:
            coverage_status = prod_source_status.coverage_status
            blocked_count = max(
                1,
                sum(
                    coverage.missing_code_count
                    for coverage in (
                        coverage_status.frequency_coverages
                        if coverage_status is not None
                        else ()
                    )
                ),
            )
        elif (
            continuity_status is not None
            and continuity_status.first_missing_registered_date
        ):
            blocked_count = max(
                1,
                continuity_status.expected_count - continuity_status.registered_count,
            )
        elif continuity_status is not None and continuity_status.blocked:
            blocked_count = 1
    else:
        blocked_count = blocked_fallback

    reason_code = reason_code_override
    blocked_component = None
    if reason_code is None and continuity_status is not None:
        if continuity_status.first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_mins_trade_days"
    if reason_code is None and stock_basic_status is not None and not stock_basic_status.ready:
        reason_code = "stock_basic_not_ready"
        blocked_component = "stock_basic"
    if reason_code is None and prod_source_status is not None and not prod_source_status.ready:
        reason_code = prod_source_status.reason_code
        blocked_component = (
            "prod_ops_task_run"
            if prod_source_status.coverage_status is None
            else "prod_stk_mins_coverage"
        )
    if reason_code is None and continuity_status is not None:
        if continuity_status.first_not_ready_reason is not None:
            reason_code = continuity_status.first_not_ready_reason
            blocked_component = "raw_stk_mins"
        elif continuity_status.blocked_reason is not None:
            reason_code = continuity_status.blocked_reason
            blocked_component = "raw_stk_mins"
    if reason_code is None and raw_status is not None and not raw_status.ready:
        reason_code = getattr(raw_status, "reason", "raw_stk_mins_not_ready")
        blocked_component = "raw_stk_mins"
    if reason_code is None:
        if selected_trade_date:
            reason_code = "request_run"
        elif not source_window_started:
            reason_code = "run_window_not_started"
        elif target_trade_date is None:
            reason_code = "no_registered_partition"
        else:
            reason_code = "all_ready"
    if reason == "historical_raw_recovery_required":
        reason_code = "historical_raw_recovery_required"
        blocked_component = "historical_raw_recovery"
    summary, next_action = _cursor_summary_and_next_action(
        selected_trade_date=selected_trade_date,
        target_trade_date=target_trade_date,
        reason_code=reason_code,
        blocked_component=blocked_component,
    )

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details=build_cursor_details(
            sensor_name="stock_mins_raw_sensor",
            job_name=STOCK_MINS_RAW_SENSOR_JOB_NAME,
            asset_family="stock_mins_raw",
            partition_set=cn_a_stock_mins_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": compact_continuity_frontier(
                    continuity_status,
                    selected_trade_date=selected_trade_date,
                ),
                "raw": compact_batch_frontier(
                    raw_batch_status,
                    selected_trade_date=selected_trade_date,
                ),
            },
            gate_statuses=compact_gate_statuses(
                {
                    "raw_stk_mins": raw_status,
                    "stock_basic": stock_basic_status,
                }
            ),
            evidence={
                "registered_trade_day_count": registered_trade_day_count,
                "source": STOCK_MINS_RAW_SOURCE,
                "source_window_started": source_window_started,
                "stock_basic_freshness_required": True,
                "prod_source": _compact_prod_source_status(prod_source_status),
            },
        ),
    )


def _compact_prod_source_status(
    status: StkMinsProdSourceReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    task_run = status.task_run_status.task_run
    coverage_status = status.coverage_status
    first_missing = None
    if coverage_status is not None and coverage_status.first_missing_freq is not None:
        coverage_by_freq = coverage_status.coverage_by_freq()
        coverage = coverage_by_freq[coverage_status.first_missing_freq]
        first_missing = {
            "freq": coverage.freq,
            "missing_code_count": coverage.missing_code_count,
            "missing_code_samples": list(coverage.missing_code_samples),
        }
    return {
        "ready": status.ready,
        "reason_code": status.reason_code,
        "task_run_id": task_run.task_run_id if task_run is not None else None,
        "candidate_task_run_id": status.task_run_status.candidate_task_run_id,
        "candidate_status": status.task_run_status.candidate_status,
        "task_run_elapsed_ms": status.task_run_status.elapsed_ms,
        "coverage_elapsed_ms": (
            coverage_status.elapsed_ms if coverage_status is not None else None
        ),
        "frequency_present_code_counts": (
            {
                str(coverage.freq): coverage.present_code_count
                for coverage in coverage_status.frequency_coverages
            }
            if coverage_status is not None
            else {}
        ),
        "first_missing": first_missing,
        "error_type": (
            coverage_status.error_type
            if coverage_status is not None
            else status.task_run_status.error_type
        ),
    }


def _run_request_for_trade_date(
    trade_date: str,
    *,
    prod_completion_reference: ProdStkMinsCompletionReference,
):
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="stock_mins_raw_update_from_prod",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
        run_config=build_stock_mins_raw_update_job_run_config(
            source=STOCK_MINS_RAW_SOURCE,
            prod_completion_reference=prod_completion_reference,
        ),
    )


@dg.sensor(
    job_name=STOCK_MINS_RAW_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=STK_MINS_RAW_SENSOR_MINIMUM_INTERVAL_SECONDS,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "prod_postgres"},
    description=(
        "股票分钟线交易日分区、基础信息、prod 全市场 TaskRun 与五频度代码覆盖"
        "全部就绪后，触发五频度 prod DB raw 更新任务。"
    ),
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
    window_trade_dates = expected_trade_dates[-STK_MINS_CONTINUITY_WINDOW_LIMIT:]
    raw_batch_status: StkMinsBatchReadiness | None = None

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
                    registered_trade_days=registered_trade_days,
                    full_semantics=True,
                )
        return raw_batch_status.status_for_trade_date(trade_date)

    selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_trade_days.name,
        expected_trade_dates=window_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=_batch_raw_status_for_trade_date,
        has_materialized_check_problem=_has_materialized_check_problem,
    )
    continuity_status = selection.status
    target_trade_date = _target_trade_date_from_continuity_status(continuity_status)
    raw_status = (
        selection.selected_status
        if isinstance(
            selection.selected_status,
            DatasetReadinessStatus | StkMinsDateReadiness,
        )
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
            raw_batch_status=raw_batch_status,
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
            raw_batch_status=raw_batch_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    selected_trade_date = selection.selected_trade_date
    if selected_trade_date != evaluated_at.date().isoformat():
        reason = "historical_raw_recovery_required"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            continuity_status=continuity_status,
            raw_batch_status=raw_batch_status,
        )
        return dg.SensorResult(
            skip_reason=(
                "最早未就绪股票分钟线 raw 分区已错过当日自动窗口，"
                "请使用受控历史 recovery 流程处理。"
            ),
            cursor=cursor,
        )

    if not source_window_started:
        reason = (
            "股票分钟线 raw 日常更新窗口尚未到 "
            f"{STOCK_MINS_RAW_RUN_START.strftime('%H:%M')}，暂不触发。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            registered_trade_day_count=len(registered_trade_days),
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=reason,
            source_window_started=source_window_started,
            raw_status=raw_status,
            continuity_status=continuity_status,
            raw_batch_status=raw_batch_status,
            blocked_fallback=1,
            reason_code_override="run_window_not_started",
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

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
            raw_batch_status=raw_batch_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_codes = load_current_listed_stock_codes_for_stk_mins(
        lake_root=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        partition_key=selected_trade_date,
    )
    prod_source_status = stk_mins_prod_source_ready_for_trade_date(
        prod_postgres=context.resources.prod_postgres,
        trade_date=selected_trade_date,
        stock_codes=stock_codes,
        observed_at=evaluated_at,
    )
    if not prod_source_status.ready or prod_source_status.completion_reference is None:
        reason = "prod 股票分钟线源端尚未满足全市场完成与代码覆盖门禁。"
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
            raw_batch_status=raw_batch_status,
            prod_source_status=prod_source_status,
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
        raw_batch_status=raw_batch_status,
        prod_source_status=prod_source_status,
    )
    return dg.SensorResult(
        run_requests=[
            _run_request_for_trade_date(
                selected_trade_date,
                prod_completion_reference=prod_source_status.completion_reference,
            )
        ],
        cursor=cursor,
    )
