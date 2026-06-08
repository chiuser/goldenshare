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
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    GOLD_STK_MINS_QFQ_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
    status_payload,
)


STOCK_MINS_QFQ_FACTOR_REPAIR_SENSOR_JOB_NAME = "stock_mins_qfq_factor_repair_job"
STOCK_MINS_QFQ_FACTOR_REPAIR_RUN_START = time(20, 40)


@dataclass(frozen=True)
class StockMinsQfqFactorRepairDecision:
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


def build_stock_mins_qfq_factor_repair_decision(
    *,
    target_trade_date: str | None,
    run_window_started: bool,
    gold_ready: bool = False,
    gold_has_materialized_check_problem: bool = False,
) -> StockMinsQfqFactorRepairDecision:
    if target_trade_date is None:
        return StockMinsQfqFactorRepairDecision(
            target_trade_date=None,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason="没有注册股票分钟线 silver 交易日分区，无法触发 gold qfq factor repair。",
        )
    if not run_window_started:
        return StockMinsQfqFactorRepairDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="股票分钟线 gold qfq factor repair 窗口尚未到 20:40，暂不触发。",
        )
    if gold_has_materialized_check_problem:
        return StockMinsQfqFactorRepairDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason=(
                "最新股票分钟线 gold qfq 分区已生成过，但 blocking checks 未全绿，"
                "暂不触发 factor repair。"
            ),
        )
    if not gold_ready:
        return StockMinsQfqFactorRepairDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason="最新股票分钟线 gold qfq 七频度尚未全部 ready，暂不触发 factor repair。",
        )
    return StockMinsQfqFactorRepairDecision(
        target_trade_date=target_trade_date,
        run_window_started=True,
        selected_trade_date=target_trade_date,
        reason="股票分钟线 gold qfq 已 ready，提交 factor repair 检测与必要回刷。",
    )


def _not_ready_count(status: DatasetReadinessStatus | None) -> int:
    if status is None or status.ready:
        return 0
    return len([asset_status for asset_status in status.statuses if not asset_status.ready])


def _cursor_payload(
    *,
    decision: StockMinsQfqFactorRepairDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
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
            "job_name": STOCK_MINS_QFQ_FACTOR_REPAIR_SENSOR_JOB_NAME,
            "run_window_started": decision.run_window_started,
            "already_submitted_for_trade_date": already_submitted_for_trade_date,
            "gold_status": status_payload(gold_status) if gold_status else None,
        },
    )


def _run_config_for_trade_date(trade_date: str) -> dict[str, object]:
    return {
        "ops": {
            "stock_mins_qfq_factor_repair_op": {
                "config": {
                    "trade_date": trade_date,
                }
            }
        }
    }


def _run_request_for_trade_date(trade_date: str):
    return build_run_request(
        run_key=f"stock_mins_qfq_factor_repair:{trade_date}",
        run_config=_run_config_for_trade_date(trade_date),
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
    job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票分钟线 gold qfq 当日七频度 ready 后，触发 factor repair 检测与必要回刷。",
)
def stock_mins_qfq_factor_repair_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = (
        evaluated_at.time() >= STOCK_MINS_QFQ_FACTOR_REPAIR_RUN_START
    )
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

    gold_status = None
    if target_trade_date is not None and run_window_started:
        if _already_submitted_for_target_date(context.cursor, target_trade_date):
            decision = StockMinsQfqFactorRepairDecision(
                target_trade_date=target_trade_date,
                run_window_started=True,
                selected_trade_date=None,
                reason=(
                    "最新股票分钟线 gold qfq 交易日已经提交过 factor repair run，"
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

        gold_status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            GOLD_STK_MINS_QFQ_READINESS_SPECS,
            partition_key=target_trade_date,
        )

    decision = build_stock_mins_qfq_factor_repair_decision(
        target_trade_date=target_trade_date,
        run_window_started=run_window_started,
        gold_ready=gold_status.ready if gold_status else False,
        gold_has_materialized_check_problem=(
            _has_materialized_check_problem(gold_status) if gold_status else False
        ),
    )
    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        gold_status=gold_status,
        already_submitted_for_trade_date=bool(decision.selected_trade_date),
    )

    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
