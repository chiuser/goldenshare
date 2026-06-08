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
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    GOLD_STK_MINS_QFQ_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
    status_payload,
)
from orchestrator.defs.checks.stk_mins_qfq_macd_kdj_checks import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME = (
    "gold_stk_mins_qfq_macd_kdj_daily_update_job"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_RUN_START = time(21, 20)
GOLD_STK_MINS_QFQ_MACD_KDJ_FREQS = (1, 5, 15, 30, 60, 90, 120)
GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS = tuple(
    AssetReadinessSpec(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m"),
        GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES,
    )
    for freq in GOLD_STK_MINS_QFQ_MACD_KDJ_FREQS
) + tuple(
    AssetReadinessSpec(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"),
        GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES,
    )
    for freq in GOLD_STK_MINS_QFQ_MACD_KDJ_FREQS
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS = tuple(
    AssetReadinessSpec(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"),
        GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES,
    )
    for freq in GOLD_STK_MINS_QFQ_MACD_KDJ_FREQS
)


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjDailyUpdateDecision:
    target_trade_date: str | None
    previous_trade_date: str | None
    run_window_started: bool
    selected_trade_date: str | None
    reason: str


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _previous_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    target_trade_date: str,
) -> str | None:
    previous_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date < target_trade_date
    )
    return previous_days[-1] if previous_days else None


def _has_materialized_check_problem(status: DatasetReadinessStatus) -> bool:
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def build_gold_stk_mins_qfq_macd_kdj_daily_update_decision(
    *,
    target_trade_date: str | None,
    previous_trade_date: str | None,
    run_window_started: bool,
    qfq_ready: bool = False,
    previous_state_ready: bool = False,
    target_ready: bool = False,
    target_has_materialized_check_problem: bool = False,
) -> GoldStkMinsQfqMacdKdjDailyUpdateDecision:
    if target_trade_date is None:
        return GoldStkMinsQfqMacdKdjDailyUpdateDecision(
            target_trade_date=None,
            previous_trade_date=None,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason="没有注册股票分钟线 silver 交易日分区，无法触发 qfq MACD/KDJ 更新。",
        )
    if not run_window_started:
        return GoldStkMinsQfqMacdKdjDailyUpdateDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="股票分钟线 qfq MACD/KDJ 日常更新窗口尚未到 21:20，暂不触发。",
        )
    if not qfq_ready:
        reason = "股票分钟线 gold qfq 七频度尚未全部 ready，暂不触发 MACD/KDJ 更新。"
    elif not previous_state_ready:
        reason = "上一交易日 MACD/KDJ state 尚未 ready，暂不触发日常增量。"
    elif target_ready:
        reason = "最新股票分钟线 qfq MACD/KDJ 交易日的七频度指标和 state 已经 ready。"
    elif target_has_materialized_check_problem:
        reason = (
            "最新股票分钟线 qfq MACD/KDJ 分区已生成过，但 blocking checks 未全绿，"
            "暂不自动重跑，请人工检查后修复。"
        )
    else:
        return GoldStkMinsQfqMacdKdjDailyUpdateDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            run_window_started=True,
            selected_trade_date=target_trade_date,
            reason="股票分钟线 qfq MACD/KDJ 门禁已满足，提交七频度指标更新。",
        )

    return GoldStkMinsQfqMacdKdjDailyUpdateDecision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
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
    decision: GoldStkMinsQfqMacdKdjDailyUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    qfq_status: DatasetReadinessStatus | None = None,
    previous_state_status: DatasetReadinessStatus | None = None,
    target_status: DatasetReadinessStatus | None = None,
    already_submitted_for_trade_date: bool = False,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REQUEST_RUNS
        if decision.selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_trade_date:
        blocked_count += _not_ready_count(qfq_status)
        blocked_count += _not_ready_count(previous_state_status)
        blocked_count += _not_ready_count(target_status)
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
            "previous_trade_date": decision.previous_trade_date,
            "reason": decision.reason,
            "job_name": GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME,
            "run_window_started": decision.run_window_started,
            "already_submitted_for_trade_date": already_submitted_for_trade_date,
            "qfq_status": status_payload(qfq_status) if qfq_status else None,
            "previous_state_status": (
                status_payload(previous_state_status) if previous_state_status else None
            ),
            "target_status": status_payload(target_status) if target_status else None,
        },
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


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=f"gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}",
        partition_key=trade_date,
    )


@dg.sensor(
    job_name=GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票分钟线 qfq 七频度 ready 且上一交易日 state ready 后，触发 MACD/KDJ 更新任务。",
)
def gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = (
        evaluated_at.time() >= GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_RUN_START
    )
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    previous_trade_date = (
        _previous_registered_trade_date(registered_trade_days, target_trade_date)
        if target_trade_date is not None
        else None
    )

    qfq_status = None
    previous_state_status = None
    target_status = None
    previous_state_ready = previous_trade_date is None
    if target_trade_date is not None and run_window_started:
        if _already_submitted_for_target_date(context.cursor, target_trade_date):
            decision = GoldStkMinsQfqMacdKdjDailyUpdateDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=previous_trade_date,
                run_window_started=True,
                selected_trade_date=None,
                reason=(
                    "最新股票分钟线 qfq MACD/KDJ 交易日已经提交过 daily run，"
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

        qfq_status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            GOLD_STK_MINS_QFQ_READINESS_SPECS,
            partition_key=target_trade_date,
        )
        if qfq_status.ready and previous_trade_date is not None:
            previous_state_status = partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS,
                partition_key=previous_trade_date,
            )
            previous_state_ready = previous_state_status.ready
        if qfq_status.ready and previous_state_ready:
            target_status = partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS,
                partition_key=target_trade_date,
            )

    decision = build_gold_stk_mins_qfq_macd_kdj_daily_update_decision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        run_window_started=run_window_started,
        qfq_ready=qfq_status.ready if qfq_status else False,
        previous_state_ready=previous_state_ready,
        target_ready=target_status.ready if target_status else False,
        target_has_materialized_check_problem=(
            _has_materialized_check_problem(target_status) if target_status else False
        ),
    )
    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        qfq_status=qfq_status,
        previous_state_status=previous_state_status,
        target_status=target_status,
        already_submitted_for_trade_date=bool(decision.selected_trade_date),
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
