from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.storage.dagster_run import RunsFilter

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    is_first_expected_trade_date,
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    batch_gold_stk_mins_qfq_lake_readiness,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_effective_readiness import (
    effective_gold_qfq_readiness_for_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.checks.stk_mins_qfq_macd_kdj_checks import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES,
)
from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_daily_update import (
    gold_stk_mins_qfq_macd_kdj_daily_update_job,
)
from orchestrator.defs.jobs.stock_mins_qfq_daily_update import (
    stock_mins_qfq_daily_update_job,
)
from orchestrator.defs.jobs.stock_mins_qfq_factor_repair import (
    stock_mins_qfq_factor_repair_job,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.health.lake_root import assert_lake_root_available_for_run
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, silver_trade_calendar_path
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
    STK_MINS_MACD_KDJ_BASELINE_START_DATE,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    CN_A_SENSOR_TIMEZONE,
    DatasetReadinessStatus,
    partition_dataset_readiness_status_from_latest_checks,
)


DAGSTER_PARTITION_TAG = "dagster/partition"
STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME = "stock_mins_qfq_daily_update_job"
STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME = "stock_mins_qfq_factor_repair_job"
GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME = (
    "gold_stk_mins_qfq_macd_kdj_daily_update_job"
)
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
class GoldStkMinsQfqMacdKdjDailyRunStatusDecision:
    target_trade_date: str | None
    previous_trade_date: str | None
    selected_trade_date: str | None
    reason: str
    next_action: str


def _normalize_trade_date(raw_trade_date: str | None) -> str | None:
    if raw_trade_date is None:
        return None
    try:
        return date.fromisoformat(str(raw_trade_date).strip()).isoformat()
    except ValueError:
        return None


def _trade_date_from_run_config(run_config: Any) -> str | None:
    if not isinstance(run_config, dict):
        return None
    trade_date = (
        run_config.get("ops", {})
        .get("stock_mins_qfq_factor_repair_op", {})
        .get("config", {})
        .get("trade_date")
    )
    return _normalize_trade_date(trade_date)


def _trade_date_from_dagster_run(dagster_run: object) -> str | None:
    tags = getattr(dagster_run, "tags", {}) or {}
    partition_key = _normalize_trade_date(tags.get(DAGSTER_PARTITION_TAG))
    if partition_key is not None:
        return partition_key
    return _trade_date_from_run_config(getattr(dagster_run, "run_config", None))


def _load_macd_kdj_expected_trade_dates() -> tuple[str, ...]:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    assert_lake_root_available_for_run(lake_root)
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with connect_configured_duckdb() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_MACD_KDJ_BASELINE_START_DATE,
            evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
            same_day_register_start=None,
        )


def _previous_expected_trade_date_for_target(
    expected_trade_dates: tuple[str, ...],
    target_trade_date: str,
) -> str | None:
    return previous_expected_trade_date(
        expected_trade_dates,
        target_trade_date,
    )


def _candidate_repair_trade_dates_for_effective_qfq(
    expected_trade_dates: tuple[str, ...],
    target_trade_date: str,
) -> tuple[str, ...]:
    if target_trade_date not in expected_trade_dates:
        return ()
    target_index = expected_trade_dates.index(target_trade_date)
    upper_index = min(
        len(expected_trade_dates),
        target_index + STK_MINS_CONTINUITY_WINDOW_LIMIT,
    )
    return expected_trade_dates[target_index:upper_index]


def _has_materialized_check_problem(status: DatasetReadinessStatus) -> bool:
    return any(
        asset_status.materialized and not asset_status.checks_passed
        for asset_status in status.statuses
    )


def _successful_run_for_trade_date_exists(
    instance: dg.DagsterInstance,
    *,
    job_name: str,
    trade_date: str,
    triggered_run: object | None = None,
    recent_limit: int = 50,
) -> bool:
    if (
        triggered_run is not None
        and getattr(triggered_run, "job_name", None) == job_name
        and _trade_date_from_dagster_run(triggered_run) == trade_date
        and getattr(triggered_run, "status", None) == dg.DagsterRunStatus.SUCCESS
    ):
        return True

    if job_name == STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME:
        records = instance.get_run_records(
            filters=RunsFilter(
                job_name=job_name,
                statuses=[dg.DagsterRunStatus.SUCCESS],
                tags={DAGSTER_PARTITION_TAG: trade_date},
            ),
            limit=1,
        )
        return bool(records)

    records = instance.get_run_records(
        filters=RunsFilter(
            job_name=job_name,
            statuses=[dg.DagsterRunStatus.SUCCESS],
        ),
        limit=recent_limit,
    )
    return any(
        _trade_date_from_dagster_run(record.dagster_run) == trade_date
        for record in records
    )


def _effective_qfq_ready_for_target_trade_date(
    context: dg.RunStatusSensorContext,
    *,
    target_trade_date: str,
    expected_trade_dates: tuple[str, ...],
) -> bool:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    assert_lake_root_available_for_run(lake_root)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    candidate_repair_trade_dates = _candidate_repair_trade_dates_for_effective_qfq(
        expected_trade_dates,
        target_trade_date,
    )
    with connect_configured_duckdb() as connection:
        batch_status = batch_gold_stk_mins_qfq_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(target_trade_date,),
            registered_trade_days=registered_trade_days,
            full_semantics=True,
        )
        effective_status = effective_gold_qfq_readiness_for_trade_date(
            connection=connection,
            lake_root=lake_root,
            trade_date=target_trade_date,
            lake_status=batch_status.status_for_trade_date(target_trade_date),
            candidate_repair_trade_dates=candidate_repair_trade_dates,
            repair_status_for_trade_date=lambda repair_trade_date: (
                gold_stk_mins_qfq_factor_repair_status(
                    context.instance,
                    repair_trade_date,
                    include_event_storage_ids=False,
                )
            ),
        ).status
    return effective_status.ready


def build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
    *,
    target_trade_date: str | None,
    previous_trade_date: str | None,
    qfq_daily_succeeded: bool,
    qfq_factor_repair_status: GoldStkMinsQfqFactorRepairStatus | None,
    qfq_ready: bool,
    previous_state_ready: bool,
    target_ready: bool,
    target_has_materialized_check_problem: bool,
) -> GoldStkMinsQfqMacdKdjDailyRunStatusDecision:
    if target_trade_date is None:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=None,
            previous_trade_date=None,
            selected_trade_date=None,
            reason="无法从触发 run 中解析股票分钟线 qfq MACD/KDJ 目标交易日。",
            next_action=(
                "检查触发 run 是否带有 dagster/partition tag，或 factor repair "
                "run config 是否包含 trade_date。"
            ),
        )
    if not qfq_daily_succeeded:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason=(
                "同日 stock_mins_qfq_daily_update_job 尚未成功，"
                "暂不触发 MACD/KDJ daily。"
            ),
            next_action="等待同日 qfq daily 成功后再由 run-status sensor 自动重试。",
        )
    if qfq_factor_repair_status is None or not qfq_factor_repair_status.ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason=(
                qfq_factor_repair_status.reason
                if qfq_factor_repair_status is not None
                else "同日 stock_mins_qfq_factor_repair_job 尚未成功。"
            ),
            next_action=(
                "先等待或修复同日 qfq factor repair；该门禁 ready 后才允许写 "
                "MACD/KDJ indicator/state。"
            ),
        )
    if not qfq_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason=(
                "股票分钟线 gold qfq 七频度尚未全部 ready，"
                "暂不触发 MACD/KDJ daily。"
            ),
            next_action=(
                "先修复同日 gold_stk_mins_qfq 七频度 readiness，再等待下一次 "
                "run-status sensor。"
            ),
        )
    if not previous_state_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="上一交易日 MACD/KDJ state 尚未 ready，暂不触发日常增量。",
            next_action=(
                "先修复上一 expected 交易日的 MACD/KDJ state checks，再重试当日增量。"
            ),
        )
    if target_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="目标交易日七频度 MACD/KDJ indicator/state 已经 ready。",
            next_action="无需处理；当前目标日期已经完成。",
        )
    if target_has_materialized_check_problem:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason=(
                "目标交易日 MACD/KDJ 已生成但 blocking checks 未全绿，"
                "暂不自动重跑，请人工检查。"
            ),
            next_action=(
                "先查看 MACD/KDJ indicator/state checks metadata，人工确认文件事实后再处理。"
            ),
        )
    return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        selected_trade_date=target_trade_date,
        reason="qfq daily 与 qfq factor repair 同日成功，提交 MACD/KDJ daily。",
        next_action=(
            "等待 gold_stk_mins_qfq_macd_kdj_daily_update_job 完成并查看 blocking checks。"
        ),
    )


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_stk_mins_qfq_macd_kdj_daily_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
    )


def _evaluate_daily_run_status_decision(
    *,
    context: dg.RunStatusSensorContext,
    target_trade_date: str,
    expected_trade_dates: tuple[str, ...],
) -> tuple[
    GoldStkMinsQfqMacdKdjDailyRunStatusDecision,
    GoldStkMinsQfqFactorRepairStatus | None,
]:
    if target_trade_date not in expected_trade_dates:
        return (
            GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=None,
                selected_trade_date=None,
                reason=(
                    "目标交易日不在股票分钟线 expected calendar，"
                    f"暂不触发 MACD/KDJ daily: target_trade_date={target_trade_date}。"
                ),
                next_action=(
                    "先确认 cn_a_stock_mins_silver_trade_days 和股票分钟线 expected calendar。"
                ),
            ),
            None,
        )
    previous_trade_date = _previous_expected_trade_date_for_target(
        expected_trade_dates,
        target_trade_date,
    )
    is_first_expected_target = is_first_expected_trade_date(
        expected_trade_dates,
        target_trade_date,
    )
    if previous_trade_date is None and not is_first_expected_target:
        return (
            GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=None,
                selected_trade_date=None,
                reason=(
                    "无法找到目标交易日的上一 expected trade date，"
                    f"暂不触发 MACD/KDJ daily: target_trade_date={target_trade_date}。"
                ),
                next_action=(
                    "先修复股票分钟线 expected calendar 连续性，再重新评估该目标日期。"
                ),
            ),
            None,
        )
    qfq_daily_succeeded = _successful_run_for_trade_date_exists(
        context.instance,
        job_name=STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
        trade_date=target_trade_date,
        triggered_run=context.dagster_run,
    )
    qfq_factor_repair_succeeded = _successful_run_for_trade_date_exists(
        context.instance,
        job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
        trade_date=target_trade_date,
        triggered_run=context.dagster_run,
    )
    qfq_factor_repair_status = None
    qfq_ready = False
    previous_state_ready = is_first_expected_target
    target_ready = False
    target_has_materialized_check_problem = False
    if qfq_daily_succeeded and qfq_factor_repair_succeeded:
        qfq_factor_repair_status = gold_stk_mins_qfq_factor_repair_status(
            context.instance,
            target_trade_date,
            include_event_storage_ids=False,
        )
        if qfq_factor_repair_status.ready:
            qfq_ready = _effective_qfq_ready_for_target_trade_date(
                context,
                target_trade_date=target_trade_date,
                expected_trade_dates=expected_trade_dates,
            )
            if qfq_ready and previous_trade_date is not None:
                previous_state_status = (
                    partition_dataset_readiness_status_from_latest_checks(
                        context.instance,
                        GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS,
                        partition_key=previous_trade_date,
                    )
                )
                previous_state_ready = previous_state_status.ready
            if qfq_ready and previous_state_ready:
                target_status = partition_dataset_readiness_status_from_latest_checks(
                    context.instance,
                    GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS,
                    partition_key=target_trade_date,
                )
                target_ready = target_status.ready
                target_has_materialized_check_problem = (
                    _has_materialized_check_problem(target_status)
                )

    decision = build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        qfq_daily_succeeded=qfq_daily_succeeded,
        qfq_factor_repair_status=qfq_factor_repair_status,
        qfq_ready=qfq_ready,
        previous_state_ready=previous_state_ready,
        target_ready=target_ready,
        target_has_materialized_check_problem=target_has_materialized_check_problem,
    )
    return decision, qfq_factor_repair_status


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stk_mins_qfq_macd_kdj_daily_update_job,
    monitored_jobs=[stock_mins_qfq_daily_update_job, stock_mins_qfq_factor_repair_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "stock_mins_qfq_daily_update_job 与 stock_mins_qfq_factor_repair_job "
        "同日成功后触发七频度股票分钟线 qfq MACD/KDJ daily 更新。"
    ),
)
def gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    target_trade_date = _trade_date_from_dagster_run(context.dagster_run)
    if target_trade_date is None:
        return dg.SkipReason("触发 run 缺少可解析的 trade_date。")

    decision, qfq_factor_repair_status = _evaluate_daily_run_status_decision(
        context=context,
        target_trade_date=target_trade_date,
        expected_trade_dates=_load_macd_kdj_expected_trade_dates(),
    )
    if decision.selected_trade_date is None or qfq_factor_repair_status is None:
        return dg.SkipReason(f"{decision.reason} 下一步：{decision.next_action}")
    return _run_request_for_trade_date(decision.selected_trade_date)
