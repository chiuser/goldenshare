from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
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
    ADJ_FACTOR_READINESS_SPECS,
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    GOLD_STK_MINS_QFQ_READINESS_SPECS,
    SILVER_STK_MINS_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
    status_payload,
)


STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME = "stock_mins_qfq_daily_update_job"
STOCK_MINS_QFQ_DAILY_RUN_START = time(20, 10)


@dataclass(frozen=True)
class StockMinsQfqDailyUpdateDecision:
    target_trade_date: str | None
    run_window_started: bool
    selected_trade_date: str | None
    reason: str


def _latest_registered_silver_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _has_materialized_check_problem(status: DatasetReadinessStatus) -> bool:
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


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
            reason="股票分钟线 gold qfq 日常更新窗口尚未到 20:10，暂不触发。",
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


def _not_ready_count(status: DatasetReadinessStatus | None) -> int:
    if status is None or status.ready:
        return 0
    return len([asset_status for asset_status in status.statuses if not asset_status.ready])


def _cursor_payload(
    *,
    decision: StockMinsQfqDailyUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    silver_status: DatasetReadinessStatus | None = None,
    adj_factor_status: DatasetReadinessStatus | None = None,
    gold_status: DatasetReadinessStatus | None = None,
    already_submitted_for_trade_date: bool = False,
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
        if blocked_count == 0 and decision.target_trade_date is None:
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
            "job_name": STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
            "run_window_started": decision.run_window_started,
            "already_submitted_for_trade_date": already_submitted_for_trade_date,
            "silver_status": status_payload(silver_status) if silver_status else None,
            "adj_factor_status": (
                status_payload(adj_factor_status) if adj_factor_status else None
            ),
            "gold_status": status_payload(gold_status) if gold_status else None,
        },
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
    if (
        details.get("selected_trade_date") == target_trade_date
        and details.get("already_submitted_for_trade_date") is True
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
    description="股票分钟线 silver 和复权因子就绪后，触发七频度 gold qfq 更新任务。",
)
def stock_mins_qfq_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= STOCK_MINS_QFQ_DAILY_RUN_START
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_silver_trade_date(
        registered_trade_days,
        evaluated_at,
    )

    silver_status = None
    adj_factor_status = None
    gold_status = None
    if target_trade_date is not None and run_window_started:
        if _already_submitted_for_target_date(context.cursor, target_trade_date):
            decision = StockMinsQfqDailyUpdateDecision(
                target_trade_date=target_trade_date,
                run_window_started=True,
                selected_trade_date=None,
                reason=(
                    "最新股票分钟线 gold qfq 交易日已经提交过 qfq daily run，"
                    "失败时请人工 retry。"
                ),
            )
            cursor = _cursor_payload(
                decision=decision,
                evaluated_at=evaluated_at,
                registered_trade_day_count=len(registered_trade_days),
                already_submitted_for_trade_date=True,
            )
            return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

        silver_status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            SILVER_STK_MINS_READINESS_SPECS,
            partition_key=target_trade_date,
        )
        if silver_status.ready:
            adj_factor_status = partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                ADJ_FACTOR_READINESS_SPECS,
                partition_key=target_trade_date,
            )
        if silver_status.ready and adj_factor_status and adj_factor_status.ready:
            gold_status = partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                GOLD_STK_MINS_QFQ_READINESS_SPECS,
                partition_key=target_trade_date,
            )

    decision = build_stock_mins_qfq_daily_update_decision(
        target_trade_date=target_trade_date,
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
        already_submitted_for_trade_date=bool(decision.selected_trade_date),
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
