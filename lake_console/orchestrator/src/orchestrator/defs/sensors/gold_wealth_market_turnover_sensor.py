from dataclasses import dataclass
from datetime import date, datetime, timedelta

import dagster as dg
from dagster._core.storage.dagster_run import RunsFilter

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
PROD_CORE_WEALTH_MARKET_TURNOVER_ASSET_KEY = dg.AssetKey(
    "prod_core_wealth_market_turnover"
)
DAGSTER_RUN_KEY_TAG = "dagster/run_key"
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


@dataclass(frozen=True)
class WealthMarketTurnoverProdCoreReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    failed: bool
    reason: str
    reason_code: str
    failed_component: str | None = None

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "materialized": self.materialized,
            "checks_passed": self.checks_passed,
            "failed": self.failed,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "failed_component": self.failed_component,
        }


def build_gold_wealth_market_turnover_update_decision(
    *,
    target_trade_date: str | None,
    run_window_started: bool,
    silver_ready: bool = False,
    gold_ready: bool = False,
    prod_sync_ready: bool = False,
    prod_sync_failed: bool = False,
    gold_has_materialized_check_problem: bool = False,
    blocked_component: str | None = None,
    reason_code: str | None = None,
) -> GoldWealthMarketTurnoverUpdateDecision:
    if not run_window_started:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=False,
            selected_trade_date=None,
            reason="财富成交额 gold 日常更新窗口尚未到 19:50，暂不触发。",
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
    if not gold_ready:
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
            reason_code=reason_code or "request_run",
            blocked_component=blocked_component,
        )
    if prod_sync_failed:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason=(
                "财富成交额 prod core serving 同步曾失败且尚无成功 materialization，"
                "暂不由 sensor 反复重发，请人工按分区重跑。"
            ),
            reason_code="prod_sync_failed_requires_manual_retry",
            blocked_component="prod_core_db",
        )
    if prod_sync_ready:
        return GoldWealthMarketTurnoverUpdateDecision(
            target_trade_date=target_trade_date,
            run_window_started=True,
            selected_trade_date=None,
            reason="财富成交额 gold 与 prod core serving 目标分区均已 ready。",
            reason_code="wealth_market_turnover_chain_ready",
            blocked_component="none",
        )
    return GoldWealthMarketTurnoverUpdateDecision(
        target_trade_date=target_trade_date,
        run_window_started=True,
        selected_trade_date=target_trade_date,
        reason="财富成交额 gold 已 ready，prod core serving 尚未同步，提交同一个 job 补同步。",
        reason_code=reason_code or "prod_sync_missing",
        blocked_component=blocked_component or "prod_core_db",
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
    status: (
        StkMinsDateReadiness
        | WealthMarketTurnoverDateReadiness
        | WealthMarketTurnoverProdCoreReadiness
    ),
) -> bool:
    return status.materialized and not status.checks_passed


def _has_prod_core_sync_problem(
    status: WealthMarketTurnoverProdCoreReadiness,
) -> bool:
    return status.failed or _has_materialized_check_problem(status)


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
    return compact_batch_frontier(status)


def _date_status_payload(
    status: (
        StkMinsDateReadiness
        | WealthMarketTurnoverDateReadiness
        | WealthMarketTurnoverProdCoreReadiness
        | None
    ),
) -> dict[str, object] | None:
    if status is None:
        return None
    if isinstance(status, WealthMarketTurnoverProdCoreReadiness):
        return {
            "trade_date": status.trade_date,
            "ready": status.ready,
            "materialized": status.materialized,
            "checks_passed": status.checks_passed,
            "failed": status.failed,
            "reason_code": status.reason_code,
            "failed_component": status.failed_component,
        }
    return compact_readiness_status(status)


def _summary_and_next_action(
    decision: GoldWealthMarketTurnoverUpdateDecision,
) -> tuple[str, str]:
    if decision.selected_trade_date:
        if decision.reason_code == "prod_sync_missing":
            return (
                f"触发 {decision.selected_trade_date} 财富成交额 prod core serving 补同步。",
                "等待本次 run 完成；完成后确认 prod_core_wealth_market_turnover materialization 成功。",
            )
        return (
            f"触发 {decision.selected_trade_date} 财富成交额 gold 和 prod core serving 更新。",
            "等待本次 run 完成；完成后查看 gold integrity check 与 prod core sync materialization。",
        )
    if decision.reason_code == "run_window_not_started":
        return (
            "跳过：财富成交额日更窗口还没到。",
            "等待 stock mins silver 计划时间再延后 10 分钟；到点后 sensor 会重新检查五频度 silver。",
        )
    if decision.blocked_component == "cn_a_stock_mins_silver_trade_days":
        return (
            "跳过：股票分钟线 silver 交易日分区还没有补齐。",
            "先补齐 cn_a_stock_mins_silver_trade_days 分区，再等待下一次 sensor tick。",
        )
    if decision.blocked_component == "silver_stk_mins":
        return (
            f"跳过：{decision.target_trade_date or '-'} 的 silver_stk_mins 五频度还没有全部 ready。",
            "先修复同日 1/5/15/30/60 分钟 silver 文件或 checks；部分频度 ready 不会触发。",
        )
    if decision.blocked_component == "gold_wealth_market_turnover":
        return (
            f"跳过：{decision.target_trade_date or '-'} 的财富成交额 gold 已有问题状态。",
            "先查看 gold_wealth_market_turnover_integrity_check，人工确认后再修复或重跑。",
        )
    if decision.reason_code == "prod_sync_failed_requires_manual_retry":
        return (
            f"跳过：{decision.target_trade_date or '-'} 的 prod core serving 同步曾失败。",
            "不要让 sensor 反复重发；人工检查 prod 写入错误后按分区重跑同一个 job。",
        )
    if decision.blocked_component == "prod_core_db":
        return (
            f"跳过：{decision.target_trade_date or '-'} 的 prod core serving 尚未 ready。",
            "如果 gold 已 ready，下一次可触发同一个 job 补同步；失败过则人工重跑。",
        )
    if decision.reason_code == "wealth_market_turnover_chain_ready":
        return (
            "跳过：财富成交额 gold 与 prod core serving 最近目标分区均已 ready。",
            "无需处理；等待新的分钟线 silver 交易日分区。",
        )
    return (
        decision.reason,
        "按 cursor 的 blocked_component 修复上游状态，或等待下一次 sensor tick。",
    )


def _cursor_payload(
    *,
    decision: GoldWealthMarketTurnoverUpdateDecision,
    evaluated_at: datetime,
    registered_trade_day_count: int,
    silver_status: StkMinsDateReadiness | None = None,
    gold_status: WealthMarketTurnoverDateReadiness | None = None,
    prod_core_status: WealthMarketTurnoverProdCoreReadiness | None = None,
    silver_continuity_status: StockMinsContinuityStatus | None = None,
    gold_continuity_status: StockMinsContinuityStatus | None = None,
    prod_core_continuity_status: StockMinsContinuityStatus | None = None,
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
        blocked_count += 0 if prod_core_status is None or prod_core_status.ready else 1
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
            prod_core_continuity_status is not None
            and prod_core_continuity_status.first_missing_registered_date
        ):
            blocked_count += 1
        elif (
            prod_core_continuity_status is not None
            and prod_core_continuity_status.blocked
        ):
            blocked_count += 1
        if (
            blocked_count == 0
            and decision.reason_code != "wealth_market_turnover_chain_ready"
        ):
            blocked_count = 1
    summary, next_action = _summary_and_next_action(decision)
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.target_trade_date,
        selected_count=1 if decision.selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=(decision.selected_trade_date,) if decision.selected_trade_date else (),
        details=build_cursor_details(
            sensor_name="gold_wealth_market_turnover_update_job_sensor",
            job_name=GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
            asset_family="wealth_market_turnover",
            partition_set=cn_a_stock_mins_silver_trade_days.name,
            reason_code=decision.reason_code,
            blocked_component=decision.blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "silver": compact_continuity_frontier(
                    silver_continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "gold": compact_continuity_frontier(
                    gold_continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "prod_core": compact_continuity_frontier(
                    prod_core_continuity_status,
                    selected_trade_date=decision.selected_trade_date,
                ),
                "silver_lake": _batch_status_payload(silver_batch_status),
                "gold_lake": _batch_status_payload(gold_batch_status),
            },
            gate_statuses={
                **compact_gate_statuses(
                    {
                        "silver_stk_mins": silver_status,
                        "gold_wealth_market_turnover": gold_status,
                    }
                ),
                "prod_core_wealth_market_turnover": _date_status_payload(
                    prod_core_status
                ),
            },
            evidence={
                "registered_trade_day_count": registered_trade_day_count,
                "selected_trade_date": decision.selected_trade_date,
                "run_window_started": decision.run_window_started,
                "run_start_time": GOLD_WEALTH_MARKET_TURNOVER_RUN_START.isoformat(),
                "freq_count": len(STK_MINS_FREQS),
            },
        ),
    )


def _run_key_for_trade_date(trade_date: str) -> str:
    return build_asset_update_run_key(
        subject="gold_wealth_market_turnover",
        unit_id=trade_date,
    )


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_wealth_market_turnover",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _prod_core_status_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> WealthMarketTurnoverProdCoreReadiness:
    materializations = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=PROD_CORE_WEALTH_MARKET_TURNOVER_ASSET_KEY,
            asset_partitions=[trade_date],
        ),
        limit=1,
    )
    run_key = _run_key_for_trade_date(trade_date)
    if materializations.records:
        return WealthMarketTurnoverProdCoreReadiness(
            trade_date=trade_date,
            ready=True,
            materialized=True,
            checks_passed=True,
            failed=False,
            reason="ready",
            reason_code="ready",
        )

    failed_runs = instance.get_run_records(
        filters=RunsFilter(
            job_name=GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
            statuses=[dg.DagsterRunStatus.FAILURE],
            tags={DAGSTER_RUN_KEY_TAG: run_key},
        ),
        limit=1,
    )
    if failed_runs:
        return WealthMarketTurnoverProdCoreReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            failed=True,
            reason="prod core wealth_market_turnover sync failed",
            reason_code="prod_sync_failed_requires_manual_retry",
            failed_component="prod_core_db",
        )

    return WealthMarketTurnoverProdCoreReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=True,
        failed=False,
        reason="missing prod core wealth_market_turnover materialization",
        reason_code="prod_sync_missing",
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
    prod_core_status: WealthMarketTurnoverProdCoreReadiness | None = None
    prod_core_continuity_status: StockMinsContinuityStatus | None = None

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
            prod_core_selection = select_first_not_ready_trade_date(
                partition_set_name=cn_a_stock_mins_silver_trade_days.name,
                expected_trade_dates=window_trade_dates,
                registered_trade_days=registered_trade_days,
                readiness_for_trade_date=lambda trade_date: (
                    _prod_core_status_for_trade_date(context.instance, trade_date)
                ),
                has_materialized_check_problem=_has_prod_core_sync_problem,
            )
            prod_core_continuity_status = prod_core_selection.status
            target_trade_date = _target_trade_date_from_continuity_status(
                prod_core_selection.status
            )
            prod_core_status = (
                prod_core_selection.selected_status
                if isinstance(
                    prod_core_selection.selected_status,
                    WealthMarketTurnoverProdCoreReadiness,
                )
                else None
            )
            if prod_core_selection.status.first_missing_registered_date is not None:
                decision = build_gold_wealth_market_turnover_update_decision(
                    target_trade_date=(
                        prod_core_selection.status.first_missing_registered_date
                    ),
                    run_window_started=True,
                    silver_ready=False,
                    blocked_component="cn_a_stock_mins_silver_trade_days",
                    reason_code="missing_registered_partition",
                )
            elif prod_core_status is not None and prod_core_status.failed:
                decision = build_gold_wealth_market_turnover_update_decision(
                    target_trade_date=prod_core_status.trade_date,
                    run_window_started=True,
                    silver_ready=True,
                    gold_ready=True,
                    prod_sync_failed=True,
                    reason_code=prod_core_status.reason_code,
                )
            elif prod_core_selection.selected_trade_date is not None:
                if prod_core_status is None:
                    raise RuntimeError("prod core readiness selected status is missing.")
                selected_gold_status = _gold_status_for_trade_date(
                    prod_core_selection.selected_trade_date
                )
                selected_silver_status = _silver_status_for_trade_date(
                    prod_core_selection.selected_trade_date
                )
                decision = build_gold_wealth_market_turnover_update_decision(
                    target_trade_date=prod_core_selection.selected_trade_date,
                    run_window_started=True,
                    silver_ready=selected_silver_status.ready,
                    gold_ready=selected_gold_status.ready,
                    prod_sync_ready=prod_core_status.ready,
                    reason_code=prod_core_status.reason_code,
                    blocked_component="prod_core_db",
                )
                silver_status = selected_silver_status
                gold_status = selected_gold_status
            else:
                decision = build_gold_wealth_market_turnover_update_decision(
                    target_trade_date=target_trade_date,
                    run_window_started=True,
                    silver_ready=True,
                    gold_ready=True,
                    prod_sync_ready=True,
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
        prod_core_status=prod_core_status,
        silver_continuity_status=silver_selection.status,
        gold_continuity_status=(
            gold_selection.status if gold_selection is not None else None
        ),
        prod_core_continuity_status=prod_core_continuity_status,
        silver_batch_status=silver_batch_status,
        gold_batch_status=gold_batch_status,
    )
    if not decision.selected_trade_date:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[_run_request_for_trade_date(decision.selected_trade_date)],
        cursor=cursor,
    )
