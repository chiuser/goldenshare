from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.market_breadth_lake_readiness import (
    batch_gold_stock_return_distribution_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
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
from orchestrator.defs.sensors.cn_a_trade_day_sensor import STOCK_TRADE_DAY_MIN_DATE
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    stock_daily_ready_for_trade_date,
)
from orchestrator.defs.sensors.stock_trade_day_sensor import (
    STOCK_TRADE_DAY_REGISTER_START,
)


def _status_payload(status: ContinuityDateReadiness | None) -> dict[str, object] | None:
    return compact_readiness_status(status)


def _stock_daily_status_payload(
    status: DatasetReadinessStatus | None,
) -> list[dict[str, object]] | None:
    return compact_readiness_status(status)


def _summary_and_next_action(
    *,
    reason: str,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str | None,
) -> tuple[str, str]:
    if selected_trade_date:
        return (
            f"触发 {selected_trade_date} 收益率分布 gold 生成。",
            "等待本次 run 完成；完成后查看 gold_stock_return_distribution blocking checks。",
        )
    if blocked_component == "cn_a_stock_trade_days":
        return (
            "跳过：股票交易日分区还没有补齐。",
            "等待 cn_a_stock_trade_days 注册缺失交易日后，下一次 sensor tick 会继续检查。",
        )
    if blocked_component == "silver_stock_daily":
        return (
            f"跳过：{target_trade_date or '-'} 的 silver_stock_daily 还没有 ready，收益率分布不能计算。",
            "先修复同日 silver_stock_daily 文件或 blocking checks，再等待下一次 sensor tick。",
        )
    if blocked_component == "gold_stock_return_distribution":
        if reason_code == "all_ready":
            return (
                "跳过：最近窗口内收益率分布 gold 已全部 ready。",
                "无需处理；等待新的股票交易日分区或上游变化。",
            )
        return (
            f"跳过：{target_trade_date or '-'} 的收益率分布 gold 状态需要人工确认。",
            "先查看 gold_stock_return_distribution checks 的失败项，确认后再修复或重跑。",
        )
    return (
        reason,
        "按 cursor 的 blocked_component 修复上游状态，或等待下一次 sensor tick。",
    )


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    selected_trade_date: str | None,
    reason: str,
    continuity_status: dict[str, object] | None = None,
    batch_status: ContinuityBatchReadiness | None = None,
    gold_status: ContinuityDateReadiness | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    blocked_fallback: int = 0,
) -> str:
    selected_count = 1 if selected_trade_date else 0
    blocked_count = 0
    if not selected_trade_date:
        if stock_daily_status is not None and not stock_daily_status.ready:
            blocked_count = 1
        elif gold_status is not None and not gold_status.ready:
            blocked_count = 1
        else:
            blocked_count = blocked_fallback
    reason_code = "request_run" if selected_trade_date else None
    blocked_component = None
    if reason_code is None and stock_daily_status is not None and not stock_daily_status.ready:
        reason_code = stock_daily_status.reason
        blocked_component = "silver_stock_daily"
    if reason_code is None and gold_status is not None and not gold_status.ready:
        reason_code = gold_status.reason
        blocked_component = "gold_stock_return_distribution"
    if reason_code is None and continuity_status is not None:
        blocked_reason = continuity_status.get("blocked_reason")
        first_not_ready_reason = continuity_status.get("first_not_ready_reason")
        if continuity_status.get("registration_gap_class") == "internal":
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "gold_stock_return_distribution"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "gold_stock_return_distribution"
    if reason_code is None:
        reason_code = "no_expected_trade_date" if target_trade_date is None else "all_ready"
    summary, next_action = _summary_and_next_action(
        reason=reason,
        target_trade_date=target_trade_date,
        selected_trade_date=selected_trade_date,
        reason_code=reason_code,
        blocked_component=blocked_component,
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=selected_count,
        blocked_count=blocked_count,
        sample_keys=[selected_trade_date] if selected_trade_date else [],
        details=build_cursor_details(
            sensor_name="stock_return_distribution_continuity_sensor",
            job_name="stock_return_distribution_daily_job",
            asset_family="stock_return_distribution",
            partition_set=cn_a_stock_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": compact_continuity_frontier(
                    continuity_status,
                    selected_trade_date=selected_trade_date,
                ),
                "gold": compact_batch_frontier(
                    batch_status,
                    selected_trade_date=selected_trade_date,
                ),
            },
            gate_statuses=compact_gate_statuses(
                {
                    "gold_stock_return_distribution": gold_status,
                    "silver_stock_daily": stock_daily_status,
                }
            ),
            evidence={
                "registered_trade_day_count": registered_trade_day_count,
                "selected_trade_date": selected_trade_date,
            },
        ),
    )


@dg.sensor(
    job_name="stock_return_distribution_daily_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票日线 silver ready 后，按 bounded continuity 触发涨跌幅分布 gold 分区生成。",
)
def stock_return_distribution_continuity_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb

    with duckdb_resource.connect() as connection:
        expected_window = load_expected_trade_date_window(
            connection,
            silver_trade_calendar_path(lake_root_path),
            evaluated_at=evaluated_at,
            min_trade_date=STOCK_TRADE_DAY_MIN_DATE,
            same_day_register_start=STOCK_TRADE_DAY_REGISTER_START,
        )

    if not expected_window.expected_trade_dates:
        reason = "没有符合当前窗口的股票 expected trade date，暂不触发涨跌幅分布 gold。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    if gap_status.has_internal_gap:
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        reason = (
            "涨跌幅分布检测到股票交易日分区存在内部注册缺口，等待注册 sensor "
            f"补齐最早缺口 {gap_status.first_internal_missing_date}。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_internal_missing_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    actionable_trade_dates = gap_status.actionable_expected_trade_dates
    if not actionable_trade_dates:
        reason = "当前没有已注册且可行动的股票交易日分区，等待注册 sensor。"
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_trailing_unregistered_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    with duckdb_resource.connect() as connection:
        batch_status = batch_gold_stock_return_distribution_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=actionable_trade_dates,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=actionable_trade_dates,
        readiness=batch_status,
    )
    continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=batch_status,
        selection=selection,
    )
    target_trade_date = selection.first_not_ready_trade_date
    gold_status = selection.selected_status

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = "涨跌幅分布 gold 已生成但 lake-derived blocking checks 未全绿，暂不自动重跑。"
        else:
            reason = "最近 10 个 expected stock dates 的涨跌幅分布 gold 都已 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            batch_status=batch_status,
            gold_status=gold_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    target_trade_date = selection.selected_trade_date
    assert target_trade_date is not None
    stock_daily_status = stock_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not stock_daily_status.ready:
        reason = "涨跌幅分布等待 selected date 的 stock_daily readiness。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            batch_status=batch_status,
            gold_status=gold_status,
            stock_daily_status=stock_daily_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    run_request = build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_stock_return_distribution",
            unit_id=target_trade_date,
        ),
        partition_key=target_trade_date,
    )
    reason = "涨跌幅分布上游已 ready，提交 gold 分区生成。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        selected_trade_date=target_trade_date,
        reason=reason,
        continuity_status=continuity_status,
        batch_status=batch_status,
        gold_status=gold_status,
        stock_daily_status=stock_daily_status,
    )
    return dg.SensorResult(run_requests=[run_request], cursor=cursor)
