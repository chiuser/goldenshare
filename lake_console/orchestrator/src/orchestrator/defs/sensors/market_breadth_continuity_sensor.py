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
    batch_gold_market_breadth_lake_readiness,
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
        blocked_component = "gold_market_breadth_daily"
    if reason_code is None and continuity_status is not None:
        blocked_reason = continuity_status.get("blocked_reason")
        first_not_ready_reason = continuity_status.get("first_not_ready_reason")
        first_missing_registered_date = continuity_status.get(
            "first_missing_registered_date"
        )
        if first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "gold_market_breadth_daily"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "gold_market_breadth_daily"
    if reason_code is None:
        reason_code = "no_expected_trade_date" if target_trade_date is None else "all_ready"
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
            sensor_name="market_breadth_continuity_sensor",
            job_name="daily_market_breadth_job",
            asset_family="market_breadth_daily",
            partition_set=cn_a_stock_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=reason,
            next_action=(
                "等待本次 run 完成。"
                if selected_trade_date
                else "按阻断组件修复上游状态，或等待下一次 sensor tick。"
            ),
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
                    "gold_market_breadth_daily": gold_status,
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
    job_name="daily_market_breadth_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票日线 silver ready 后，按 bounded continuity 触发市场宽度 gold 分区生成。",
)
def market_breadth_continuity_sensor(
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
        reason = "没有符合当前窗口的股票 expected trade date，暂不触发市场宽度 gold。"
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
    if not gap_status.ready:
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        reason = (
            "市场宽度检测到股票交易日分区存在注册缺口，等待注册 sensor "
            f"补齐最早缺口 {gap_status.first_missing_registered_date}。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_missing_registered_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    with duckdb_resource.connect() as connection:
        batch_status = batch_gold_market_breadth_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=expected_window.expected_trade_dates,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
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
            reason = "市场宽度 gold 已生成但 lake-derived blocking checks 未全绿，暂不自动重跑。"
        else:
            reason = "最近 10 个 expected stock dates 的市场宽度 gold 都已 ready。"
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
        reason = "市场宽度等待 selected date 的 stock_daily readiness。"
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
            subject="gold_market_breadth_daily",
            unit_id=target_trade_date,
        ),
        partition_key=target_trade_date,
    )
    reason = "市场宽度上游已 ready，提交 gold 分区生成。"
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
