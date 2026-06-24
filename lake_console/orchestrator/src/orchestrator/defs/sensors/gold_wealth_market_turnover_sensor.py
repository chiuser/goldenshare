from dataclasses import dataclass
from datetime import date, datetime, timedelta

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
    batch_silver_stk_mins_lake_readiness,
)
from orchestrator.defs.asset_guards.wealth_market_turnover_lake_readiness import (
    WealthMarketTurnoverBatchReadiness,
    WealthMarketTurnoverDateReadiness,
    batch_gold_wealth_market_turnover_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
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
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_CONTINUITY_WINDOW_LIMIT,
    STK_MINS_FREQS,
    STK_MINS_SILVER_HISTORY_START_DATE,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.sensors.stock_mins_silver_sensor import (
    STOCK_MINS_SILVER_RUN_START,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
)


GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME = (
    "gold_wealth_market_turnover_update_job"
)
GOLD_WEALTH_MARKET_TURNOVER_RUN_START = (
    datetime.combine(date.today(), STOCK_MINS_SILVER_RUN_START)
    + timedelta(minutes=10)
).time()


@dataclass(frozen=True)
class GoldWealthMarketTurnoverUpdateDecision:
    target_trade_date: str | None
    run_window_started: bool
    selected_trade_date: str | None
    reason: str
    reason_code: str
    blocked_component: str | None = None


def build_gold_wealth_market_turnover_update_decision(
    *,
    target_trade_date: str | None,
    run_window_started: bool,
    silver_ready: bool = False,
    gold_ready: bool = False,
    gold_has_materialized_check_problem: bool = False,
    blocked_component: str | None = None,
    reason_code: str | None = None,
) -> GoldWealthMarketTurnoverUpdateDecision:
    if not run_window_started:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="财富成交额 gold 日常更新窗口尚未到 20:00，暂不触发。",
            reason_code="run_window_not_started",
            blocked_component=blocked_component,
        )
    if target_trade_date is None:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=None,
            run_window_started=run_window_started,
            selected_trade_date=None,
            reason="没有可用的股票分钟线 silver 交易日分区，无法触发财富成交额更新。",
            reason_code=reason_code or "no_registered_partition",
            blocked_component=blocked_component,
        )
    if not silver_ready:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason="股票分钟线 silver 五频度尚未全部 ready，暂不触发财富成交额更新。",
            reason_code=reason_code or "silver_stk_mins_not_ready",
            blocked_component=blocked_component or "silver_stk_mins",
        )
    if gold_ready:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason="财富成交额 gold 目标分区已经 ready。",
            reason_code="gold_wealth_market_turnover_ready",
            blocked_component=blocked_component,
        )
    if gold_has_materialized_check_problem:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason=(
                "财富成交额 gold 目标分区已生成过，但 blocking check 未通过，"
                "暂不自动覆盖，请人工检查后修复。"
            ),
            reason_code="gold_materialized_check_problem",
            blocked_component="gold_wealth_market_turnover",
        )
    return GoldWealthMarketTurnoverUpdateDecision(
        target_trade_date=target_trade_date,
        run_window_started=True,
        selected_trade_date=target_trade_date,
        reason="财富成交额 gold 门禁已满足，提交单日更新。",
        reason_code="request_run",
        blocked_component=blocked_component,
    )


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


def _has_materialized_check_problem(
    status: StkMinsDateReadiness | WealthMarketTurnoverDateReadiness,
) -> bool:
    return status.materialized and not status.checks_passed


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


def _batch_status_payload(
    status: StkMinsBatchReadiness | WealthMarketTurnoverBatchReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "dataset": status.dataset,
        "expected_start_date": status.expected_start_date,
        "expected_end_date": status.expected_end_date,
        "expected_count": status.expected_count,
        "elapsed_ms": status.elapsed_ms,
    }


def _date_status_payload(
    status: StkMinsDateReadiness | WealthMarketTurnoverDateReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return status.to_cursor_details()


def _cursor_payload(
    *,
    decision: GoldWealthMarketTurnoverUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    silver_status: StkMinsDateReadiness | None = None,
    gold_status: WealthMarketTurnoverDateReadiness | None = None,
    silver_continuity_status: StockMinsContinuityStatus | None = None,
    gold_continuity_status: StockMinsContinuityStatus | None = None,
    silver_batch_status: StkMinsBatchReadiness | None = None,
    gold_batch_status: WealthMarketTurnoverBatchReadiness | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REQUEST_RUNS
        if decision.selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_trade_date:
        blocked_count += 0 if silver_status is None or silver_status.ready else 1
        blocked_count += 0 if gold_status is None or gold_status.ready else 1
        if (
            silver_continuity_status is not None
            and silver_continuity_status.first_missing_registered_date
        ):
            blocked_count += 1
        elif (
            silver_continuity_status is not None
            and silver_continuity_status.blocked
        ):
            blocked_count += 1
        if (
            gold_continuity_status is not None
            and gold_continuity_status.first_missing_registered_date
        ):
            blocked_count += 1
        elif gold_continuity_status is not None and gold_continuity_status.blocked:
            blocked_count += 1
        if (
            blocked_count == 0
            and decision.reason_code != "gold_wealth_market_turnover_ready"
        ):
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
            "reason_code": decision.reason_code,
            "blocked_component": decision.blocked_component,
            "job_name": GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
            "run_window_started": decision.run_window_started,
            "run_start_time": GOLD_WEALTH_MARKET_TURNOVER_RUN_START.isoformat(),
            "freqs": list(STK_MINS_FREQS),
            "silver_status": _date_status_payload(silver_status),
            "gold_status": _date_status_payload(gold_status),
            "silver_batch_status": _batch_status_payload(silver_batch_status),
            "gold_batch_status": _batch_status_payload(gold_batch_status),
            "silver_continuity_status": (
                silver_continuity_status.to_cursor_details()
                if silver_continuity_status is not None
                else None
            ),
            "gold_continuity_status": (
                gold_continuity_status.to_cursor_details()
                if gold_continuity_status is not None
                else None
            ),
        },
    )


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_wealth_market_turnover",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


@dg.sensor(
    job_name=GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="股票分钟线 silver 五频度 ready 后，触发财富市场成交额 gold 快照。",
)
def gold_wealth_market_turnover_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    run_window_started = evaluated_at.time() >= GOLD_WEALTH_MARKET_TURNOVER_RUN_START
    if not run_window_started:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=None,
            run_window_started=False,
            reason_code="run_window_not_started",
        )
        cursor = _cursor_payload(
            decision=decision,
            evaluated_at=evaluated_at,
            registered_trade_day_count=0,
        )
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    expected_trade_dates = _load_stock_mins_silver_expected_trade_dates(
        context,
        evaluated_at,
    )
    window_trade_dates = expected_trade_dates[-STK_MINS_CONTINUITY_WINDOW_LIMIT:]
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    silver_batch_status: StkMinsBatchReadiness | None = None
    gold_batch_status: WealthMarketTurnoverBatchReadiness | None = None

    def _silver_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness:
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
                    freqs=STK_MINS_FREQS,
                    full_semantics=True,
                )
        return silver_batch_status.status_for_trade_date(trade_date)

    def _gold_status_for_trade_date(
        trade_date: str,
    ) -> WealthMarketTurnoverDateReadiness:
        nonlocal gold_batch_status
        if gold_batch_status is None:
            lake_root = context.resources.lake_root
            duckdb_resource = context.resources.duckdb
            with duckdb_resource.connect() as connection:
                gold_batch_status = batch_gold_wealth_market_turnover_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=window_trade_dates,
                )
        return gold_batch_status.status_for_trade_date(trade_date)

    silver_selection = select_first_not_ready_trade_date(
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        expected_trade_dates=window_trade_dates,
        registered_trade_days=registered_trade_days,
        readiness_for_trade_date=_silver_status_for_trade_date,
        has_materialized_check_problem=_has_materialized_check_problem,
    )
    silver_status = (
        silver_selection.selected_status
        if isinstance(silver_selection.selected_status, StkMinsDateReadiness)
        else None
    )
    gold_selection = None
    gold_status = None

    if silver_selection.status.first_missing_registered_date is not None:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=silver_selection.status.first_missing_registered_date,
            run_window_started=True,
            silver_ready=False,
            blocked_component="cn_a_stock_mins_silver_trade_days",
            reason_code="missing_registered_partition",
        )
    elif silver_selection.selected_trade_date is not None:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=silver_selection.selected_trade_date,
            run_window_started=True,
            silver_ready=False,
            blocked_component="silver_stk_mins",
            reason_code=silver_selection.status.first_not_ready_reason
            or "silver_stk_mins_not_ready",
        )
    elif silver_selection.status.first_not_ready_trade_date is not None:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=silver_selection.status.first_not_ready_trade_date,
            run_window_started=True,
            silver_ready=False,
            blocked_component="silver_stk_mins",
            reason_code=silver_selection.status.blocked_reason
            or silver_selection.status.first_not_ready_reason
            or "silver_stk_mins_not_ready",
        )
    else:
        gold_selection = select_first_not_ready_trade_date(
            partition_set_name=cn_a_stock_mins_silver_trade_days.name,
            expected_trade_dates=window_trade_dates,
            registered_trade_days=registered_trade_days,
            readiness_for_trade_date=_gold_status_for_trade_date,
            has_materialized_check_problem=_has_materialized_check_problem,
        )
        target_trade_date = _target_trade_date_from_continuity_status(
            gold_selection.status
        )
        gold_status = (
            gold_selection.selected_status
            if isinstance(
                gold_selection.selected_status,
                WealthMarketTurnoverDateReadiness,
            )
            else None
        )

        if gold_selection.status.first_missing_registered_date is not None:
            decision = build_gold_wealth_market_turnover_update_decision(
                target_trade_date=gold_selection.status.first_missing_registered_date,
                run_window_started=True,
                silver_ready=False,
                blocked_component="cn_a_stock_mins_silver_trade_days",
                reason_code="missing_registered_partition",
            )
        elif gold_selection.selected_trade_date is None:
            decision = build_gold_wealth_market_turnover_update_decision(
                target_trade_date=target_trade_date,
                run_window_started=True,
                silver_ready=True,
                gold_ready=True,
            )
        else:
            selected_trade_date = gold_selection.selected_trade_date
            selected_gold_status = _gold_status_for_trade_date(selected_trade_date)
            selected_silver_status = _silver_status_for_trade_date(selected_trade_date)
            decision = build_gold_wealth_market_turnover_update_decision(
                target_trade_date=selected_trade_date,
                run_window_started=True,
                silver_ready=selected_silver_status.ready,
                gold_ready=selected_gold_status.ready,
                gold_has_materialized_check_problem=_has_materialized_check_problem(
                    selected_gold_status
                ),
                reason_code=selected_silver_status.reason
                if not selected_silver_status.ready
                else selected_gold_status.reason,
                blocked_component=(
                    "silver_stk_mins"
                    if not selected_silver_status.ready
                    else "gold_wealth_market_turnover"
                ),
            )
            silver_status = selected_silver_status
            gold_status = selected_gold_status

    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        registered_trade_day_count=len(registered_trade_days),
        silver_status=silver_status,
        gold_status=gold_status,
        silver_continuity_status=silver_selection.status,
        gold_continuity_status=(
            gold_selection.status if gold_selection is not None else None
        ),
        silver_batch_status=silver_batch_status,
        gold_batch_status=gold_batch_status,
    )
    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
