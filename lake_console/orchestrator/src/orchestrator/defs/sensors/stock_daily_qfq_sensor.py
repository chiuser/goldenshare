from __future__ import annotations

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.jobs.stock_daily_qfq_update import (
    gold_stock_daily_qfq_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_continuity_frontier,
    compact_readiness_status,
    reason_code_from,
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
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    adj_factor_ready_for_trade_date,
    select_first_not_ready_gold_stock_daily_qfq_partition,
    stock_daily_ready_for_trade_date,
)
from orchestrator.defs.stock_daily_qfq import (
    GoldStockDailyQfqTradeFactorCoverage,
    assess_stock_daily_qfq_trade_factor_coverage,
)


GOLD_STOCK_DAILY_QFQ_SENSOR_NAME = "gold_stock_daily_qfq_update_job_sensor"
GOLD_STOCK_DAILY_QFQ_JOB_NAME = "gold_stock_daily_qfq_update_job"


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
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _gold_stock_daily_qfq_run_request_for_trade_date(
    trade_date: str,
) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_stock_daily_qfq_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _dataset_status_materialized(status: DatasetReadinessStatus | None) -> bool:
    return bool(status and all(asset_status.materialized for asset_status in status.statuses))


def _qfq_input_coverage_for_trade_date(
    context: dg.SensorEvaluationContext,
    trade_date: str,
) -> GoldStockDailyQfqTradeFactorCoverage:
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        return assess_stock_daily_qfq_trade_factor_coverage(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            trade_date=trade_date,
        )


def _qfq_input_coverage_blocked_component(
    coverage: GoldStockDailyQfqTradeFactorCoverage,
) -> str:
    if not coverage.stock_daily_file_exists and not coverage.adj_factor_file_exists:
        return "qfq_input_files"
    if not coverage.stock_daily_file_exists or coverage.source_row_count <= 0:
        return "silver_stock_daily"
    return "silver_adj_factor"


def _compact_qfq_input_coverage(
    coverage: GoldStockDailyQfqTradeFactorCoverage,
) -> dict[str, object]:
    return {
        "ready": coverage.ready,
        "reason_code": coverage.reason_code,
        "stock_daily_file_exists": coverage.stock_daily_file_exists,
        "adj_factor_file_exists": coverage.adj_factor_file_exists,
        "source_row_count": coverage.source_row_count,
        "matched_row_count": coverage.matched_row_count,
        "missing_trade_adj_factor_row_count": (
            coverage.missing_trade_adj_factor_row_count
        ),
        "missing_trade_adj_factor_code_samples": list(
            coverage.missing_trade_adj_factor_code_samples
        ),
    }


def _ready_through_trade_date(
    *,
    expected_trade_dates: tuple[str, ...],
    first_not_ready_trade_date: str | None,
) -> str | None:
    if not expected_trade_dates:
        return None
    if first_not_ready_trade_date is None:
        return expected_trade_dates[-1]
    selected_index = expected_trade_dates.index(first_not_ready_trade_date)
    if selected_index == 0:
        return None
    return expected_trade_dates[selected_index - 1]


def _continuity_status(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    first_not_ready_trade_date: str | None,
    selected_status: DatasetReadinessStatus | None,
    selected_trade_date: str | None,
    blocked_reason: str | None,
) -> dict[str, object]:
    expected_trade_dates = expected_window.expected_trade_dates
    return {
        "expected_start_date": expected_window.min_trade_date,
        "expected_end_date": expected_window.max_trade_date,
        "expected_count": len(expected_trade_dates),
        "registered_count": len(gap_status.registered_trade_dates),
        "first_missing_registered_date": gap_status.first_missing_registered_date,
        "registration_gap_class": gap_status.registration_gap_class,
        "first_internal_missing_date": gap_status.first_internal_missing_date,
        "internal_missing_registered_count": gap_status.internal_missing_registered_count,
        "first_trailing_unregistered_date": gap_status.first_trailing_unregistered_date,
        "trailing_unregistered_count": gap_status.trailing_unregistered_count,
        "last_registered_expected_date": gap_status.last_registered_expected_date,
        "actionable_registered_count": len(gap_status.actionable_expected_trade_dates),
        "ready_through_trade_date": _ready_through_trade_date(
            expected_trade_dates=expected_trade_dates,
            first_not_ready_trade_date=first_not_ready_trade_date,
        ),
        "first_not_ready_trade_date": first_not_ready_trade_date,
        "first_not_ready_reason": reason_code_from(
            selected_status.reason if selected_status is not None else None,
            fallback="not_ready",
        )
        if first_not_ready_trade_date is not None
        else None,
        "selected_trade_date": selected_trade_date,
        "blocked_reason": blocked_reason,
    }


def _cursor_summary_and_next_action(
    *,
    reason_code: str,
    target_trade_date: str | None,
    selected_trade_date: str | None,
) -> tuple[str, str]:
    target = selected_trade_date or target_trade_date
    if reason_code == "selected_for_update" and selected_trade_date:
        return (
            f"已触发：提交 {selected_trade_date} 的股票日线前复权更新。",
            "等待本次 run 完成；完成后检查 gold_stock_daily_qfq ordinary checks。",
        )
    if reason_code == "missing_registered_partition":
        return (
            f"未触发：股票交易日分区存在缺口，首个缺失日期为 {target}。",
            "先补齐 cn_a_stock_trade_days dynamic partition，再等待下一次 tick。",
        )
    if reason_code == "pending_registered_partition_tail":
        return (
            f"未触发：股票交易日分区只缺少尾部注册日期 {target}，当前没有可行动分区。",
            "等待 cn_a_stock_trade_days 注册新的交易日分区，再等待下一次 tick。",
        )
    if reason_code == "gold_stock_daily_qfq_not_ready":
        return (
            f"未触发：{target} 的 gold_stock_daily_qfq 已生成但 checks 未通过。",
            "人工检查该分区的 asset checks；修复后再让 sensor 继续推进。",
        )
    if reason_code == "upstream_silver_stock_daily_not_ready":
        return (
            f"未触发：{target} 的 silver_stock_daily 尚未 ready。",
            "先完成同日 silver_stock_daily，再等待下一次 tick。",
        )
    if reason_code == "upstream_silver_adj_factor_not_ready":
        return (
            f"未触发：{target} 的 silver_adj_factor 尚未 ready。",
            "先完成同日 silver_adj_factor，再等待下一次 tick。",
        )
    if reason_code == "upstream_qfq_input_coverage_not_ready":
        return (
            f"未触发：{target} 的同日股票日线与复权因子代码覆盖不一致。",
            "等待或重跑同日 silver_adj_factor；覆盖恢复后 sensor 会自然提交 QFQ 更新。",
        )
    if reason_code == "all_ready":
        return (
            "未触发：最近 10 个股票交易日的 gold_stock_daily_qfq 已经 ready。",
            "等待新的股票交易日分区或新的 not-ready 分区出现。",
        )
    if reason_code == "no_expected_trade_dates":
        return (
            "未触发：交易日历没有可评估的 expected trade date。",
            "检查 silver_trade_calendar 是否已生成并包含 SSE 开市日。",
        )
    return (
        f"未触发：{target or '当前窗口'} 未满足股票日线前复权更新条件。",
        "查看 cursor 中的 reason_code 和 frontier 后处理对应前置条件。",
    )


def _build_cursor(
    *,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    gold_status: DatasetReadinessStatus | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    adj_factor_status: DatasetReadinessStatus | None = None,
    qfq_input_coverage: GoldStockDailyQfqTradeFactorCoverage | None = None,
    first_not_ready_trade_date: str | None = None,
    blocked_reason: str | None = None,
    registered_trade_day_count: int = 0,
) -> str:
    continuity_details = _continuity_status(
        expected_window=expected_window,
        gap_status=gap_status,
        first_not_ready_trade_date=first_not_ready_trade_date,
        selected_status=gold_status,
        selected_trade_date=selected_trade_date,
        blocked_reason=blocked_reason,
    )
    summary, next_action = _cursor_summary_and_next_action(
        reason_code=reason_code,
        target_trade_date=target_trade_date,
        selected_trade_date=selected_trade_date,
    )
    details = build_cursor_details(
        sensor_name=GOLD_STOCK_DAILY_QFQ_SENSOR_NAME,
        job_name=GOLD_STOCK_DAILY_QFQ_JOB_NAME,
        asset_family="stock_daily_qfq",
        partition_set=cn_a_stock_trade_days.name,
        reason_code=reason_code,
        blocked_component=blocked_component,
        summary=summary,
        next_action=next_action,
        evidence={
            "registered_trade_day_count": registered_trade_day_count,
        },
    )
    details["continuity_status"] = compact_continuity_frontier(
        continuity_details,
        selected_trade_date=selected_trade_date,
    )
    if gold_status is not None:
        details["gold_stock_daily_qfq_status"] = compact_readiness_status(gold_status)
    if stock_daily_status is not None and not stock_daily_status.ready:
        details["silver_stock_daily_status"] = compact_readiness_status(
            stock_daily_status
        )
    if adj_factor_status is not None and not adj_factor_status.ready:
        details["silver_adj_factor_status"] = compact_readiness_status(
            adj_factor_status
        )
    if qfq_input_coverage is not None:
        details["qfq_input_coverage"] = _compact_qfq_input_coverage(
            qfq_input_coverage
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
        details=details,
    )


@dg.sensor(
    job=gold_stock_daily_qfq_update_job,
    name=GOLD_STOCK_DAILY_QFQ_SENSOR_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票日线与复权因子 silver ready 后，触发股票日线前复权 gold 更新。",
)
def gold_stock_daily_qfq_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    expected_window = _load_expected_stock_trade_day_window(context, evaluated_at)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )

    if not expected_window.expected_trade_dates:
        reason = "股票日线前复权没有可评估的交易日窗口。"
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=None,
            selected_trade_date=None,
            reason_code="no_expected_trade_dates",
            blocked_component="silver_trade_calendar",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if gap_status.has_internal_gap:
        reason = (
            "股票日线前复权交易日分区存在缺口，"
            f"首个内部缺失日期为 {gap_status.first_internal_missing_date}。"
        )
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=gap_status.first_internal_missing_date,
            selected_trade_date=None,
            reason_code="missing_registered_partition",
            blocked_component="cn_a_stock_trade_days",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    actionable_trade_dates = gap_status.actionable_expected_trade_dates
    if not actionable_trade_dates:
        reason = "股票交易日分区尚未注册任何当前窗口内可行动日期。"
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=gap_status.first_trailing_unregistered_date,
            selected_trade_date=None,
            reason_code="pending_registered_partition_tail",
            blocked_component="cn_a_stock_trade_days",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    selected_trade_date, gold_status = (
        select_first_not_ready_gold_stock_daily_qfq_partition(
            context.instance,
            actionable_trade_dates,
        )
    )

    if selected_trade_date is None:
        reason = "最近 10 个股票交易日的股票日线前复权分区已经 ready。"
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=expected_window.max_trade_date,
            selected_trade_date=None,
            reason_code="all_ready",
            blocked_component="none",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if _dataset_status_materialized(gold_status):
        reason = (
            f"{selected_trade_date} 的股票日线前复权分区已生成过，"
            "但 blocking checks 未全绿，暂不自动重跑。"
        )
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason_code="gold_stock_daily_qfq_not_ready",
            blocked_component="gold_stock_daily_qfq",
            gold_status=gold_status,
            first_not_ready_trade_date=selected_trade_date,
            blocked_reason="materialized_check_problem",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    stock_daily_status = stock_daily_ready_for_trade_date(
        context.instance,
        selected_trade_date,
    )
    if not stock_daily_status.ready:
        reason = f"{selected_trade_date} 的 silver_stock_daily readiness 门禁未满足。"
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason_code="upstream_silver_stock_daily_not_ready",
            blocked_component="silver_stock_daily",
            gold_status=gold_status,
            stock_daily_status=stock_daily_status,
            first_not_ready_trade_date=selected_trade_date,
            blocked_reason="upstream_not_ready",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    adj_factor_status = adj_factor_ready_for_trade_date(
        context.instance,
        selected_trade_date,
    )
    if not adj_factor_status.ready:
        reason = f"{selected_trade_date} 的 silver_adj_factor readiness 门禁未满足。"
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason_code="upstream_silver_adj_factor_not_ready",
            blocked_component="silver_adj_factor",
            gold_status=gold_status,
            stock_daily_status=stock_daily_status,
            adj_factor_status=adj_factor_status,
            first_not_ready_trade_date=selected_trade_date,
            blocked_reason="upstream_not_ready",
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    qfq_input_coverage = _qfq_input_coverage_for_trade_date(
        context,
        selected_trade_date,
    )
    if not qfq_input_coverage.ready:
        reason = (
            f"{selected_trade_date} 的 silver_stock_daily 与 silver_adj_factor "
            "同日代码覆盖未满足。"
        )
        cursor = _build_cursor(
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            target_trade_date=selected_trade_date,
            selected_trade_date=None,
            reason_code="upstream_qfq_input_coverage_not_ready",
            blocked_component=_qfq_input_coverage_blocked_component(
                qfq_input_coverage
            ),
            gold_status=gold_status,
            stock_daily_status=stock_daily_status,
            adj_factor_status=adj_factor_status,
            qfq_input_coverage=qfq_input_coverage,
            first_not_ready_trade_date=selected_trade_date,
            blocked_reason=qfq_input_coverage.reason_code,
            registered_trade_day_count=len(registered_trade_days),
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    reason = f"{selected_trade_date} 的股票日线前复权门禁已满足，提交更新。"
    cursor = _build_cursor(
        evaluated_at=evaluated_at,
        expected_window=expected_window,
        gap_status=gap_status,
        target_trade_date=selected_trade_date,
        selected_trade_date=selected_trade_date,
        reason_code="selected_for_update",
        blocked_component="none",
        gold_status=gold_status,
        stock_daily_status=stock_daily_status,
        adj_factor_status=adj_factor_status,
        qfq_input_coverage=qfq_input_coverage,
        first_not_ready_trade_date=selected_trade_date,
        registered_trade_day_count=len(registered_trade_days),
    )
    return dg.SensorResult(
        run_requests=[
            _gold_stock_daily_qfq_run_request_for_trade_date(selected_trade_date)
        ],
        cursor=cursor,
    )
