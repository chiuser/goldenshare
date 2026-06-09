from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import dagster as dg
from dagster._core.storage.dagster_run import RunsFilter

from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    M12_PENDING_QFQ_FACTOR_REPAIR_TAG,
    M12_QFQ_FACTOR_REPAIR_CODES_HASH_TAG,
    M12_QFQ_FACTOR_REPAIR_EVENT_STORAGE_IDS_TAG,
    M12_QFQ_FACTOR_REPAIR_TRADE_DATE_TAG,
    GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
    gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status,
    gold_stk_mins_qfq_macd_kdj_repair_event_storage_ids_tag_value,
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
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    DatasetReadinessStatus,
    GOLD_STK_MINS_QFQ_READINESS_SPECS,
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
    pending_m12_repair: bool = False
    qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()
    qfq_factor_repair_codes_hash: str | None = None


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


def build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
    *,
    target_trade_date: str | None,
    previous_trade_date: str | None,
    qfq_daily_succeeded: bool,
    qfq_factor_repair_status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus | None,
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
        )
    if not qfq_daily_succeeded:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="同日 stock_mins_qfq_daily_update_job 尚未成功，暂不触发 M12 daily。",
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
        )
    if not qfq_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="股票分钟线 gold qfq 七频度尚未全部 ready，暂不触发 M12 daily。",
        )
    if not previous_state_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="上一交易日 MACD/KDJ state 尚未 ready，暂不触发日常增量。",
        )
    if target_ready:
        return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason="目标交易日七频度 MACD/KDJ indicator/state 已经 ready。",
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
        )
    return GoldStkMinsQfqMacdKdjDailyRunStatusDecision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        selected_trade_date=target_trade_date,
        reason="qfq daily 与 qfq factor repair 同日成功，提交 M12 daily。",
        pending_m12_repair=qfq_factor_repair_status.requires_m12_repair,
        qfq_factor_repair_event_storage_ids=(
            qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        ),
        qfq_factor_repair_codes_hash=(
            qfq_factor_repair_status.repair_required_codes_hash
        ),
    )


def _run_tags_for_qfq_factor_repair_status(
    status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
) -> dict[str, str]:
    tags = {
        M12_PENDING_QFQ_FACTOR_REPAIR_TAG: (
            "true" if status.requires_m12_repair else "false"
        ),
        M12_QFQ_FACTOR_REPAIR_TRADE_DATE_TAG: status.trade_date,
        M12_QFQ_FACTOR_REPAIR_EVENT_STORAGE_IDS_TAG: (
            gold_stk_mins_qfq_macd_kdj_repair_event_storage_ids_tag_value(
                status.qfq_factor_repair_event_storage_ids
            )
        ),
    }
    if status.repair_required_codes_hash is not None:
        tags[M12_QFQ_FACTOR_REPAIR_CODES_HASH_TAG] = status.repair_required_codes_hash
    return tags


def _run_request_for_trade_date(
    trade_date: str,
    *,
    qfq_factor_repair_status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
) -> dg.RunRequest:
    return dg.RunRequest(
        run_key=f"gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}",
        partition_key=trade_date,
        tags=_run_tags_for_qfq_factor_repair_status(qfq_factor_repair_status),
    )


def _evaluate_daily_run_status_decision(
    *,
    context: dg.RunStatusSensorContext,
    target_trade_date: str,
) -> tuple[
    GoldStkMinsQfqMacdKdjDailyRunStatusDecision,
    GoldStkMinsQfqMacdKdjDailyRepairGateStatus | None,
]:
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    previous_trade_date = _previous_registered_trade_date(
        registered_trade_days,
        target_trade_date,
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
    previous_state_ready = previous_trade_date is None
    target_ready = False
    target_has_materialized_check_problem = False
    if qfq_daily_succeeded and qfq_factor_repair_succeeded:
        qfq_factor_repair_status = gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status(
            context.instance,
            target_trade_date,
        )
        if qfq_factor_repair_status.ready:
            qfq_status = partition_dataset_readiness_status_from_latest_checks(
                context.instance,
                GOLD_STK_MINS_QFQ_READINESS_SPECS,
                partition_key=target_trade_date,
            )
            qfq_ready = qfq_status.ready
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
    )
    if decision.selected_trade_date is None or qfq_factor_repair_status is None:
        return dg.SkipReason(decision.reason)
    return _run_request_for_trade_date(
        decision.selected_trade_date,
        qfq_factor_repair_status=qfq_factor_repair_status,
    )
