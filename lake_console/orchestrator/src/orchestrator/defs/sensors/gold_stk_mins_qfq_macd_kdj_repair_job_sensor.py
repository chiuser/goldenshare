from __future__ import annotations

from dataclasses import dataclass

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
    gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status,
    gold_stk_mins_qfq_macd_kdj_repair_event_storage_ids_identity,
)
from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_daily_update import (
    gold_stk_mins_qfq_macd_kdj_daily_update_job,
)
from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_repair import (
    gold_stk_mins_qfq_macd_kdj_repair_job,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS,
    _trade_date_from_dagster_run,
)
from orchestrator.defs.sensors.readiness import (
    partition_dataset_readiness_status_from_latest_checks,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_JOB_NAME = (
    "gold_stk_mins_qfq_macd_kdj_repair_job"
)


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjRepairRunStatusDecision:
    target_trade_date: str | None
    selected_trade_date: str | None
    reason: str
    stock_codes: tuple[str, ...] = ()
    repair_required_codes_hash: str | None = None
    qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()


def build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
    *,
    target_trade_date: str | None,
    qfq_factor_repair_status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus | None,
    macd_kdj_daily_ready: bool,
) -> GoldStkMinsQfqMacdKdjRepairRunStatusDecision:
    if target_trade_date is None:
        return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
            target_trade_date=None,
            selected_trade_date=None,
            reason="无法从 MACD/KDJ daily run 中解析目标交易日。",
        )
    if not macd_kdj_daily_ready:
        return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=(
                "目标交易日 MACD/KDJ indicator/state 尚未 ready，"
                "暂不触发 repair。"
            ),
        )
    if qfq_factor_repair_status is None or not qfq_factor_repair_status.ready:
        return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=(
                qfq_factor_repair_status.reason
                if qfq_factor_repair_status is not None
                else "同日 qfq factor repair 状态不可用。"
            ),
        )
    if not qfq_factor_repair_status.requires_macd_kdj_repair:
        return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason="qfq factor repair 未改写历史 qfq 文件，无需触发 MACD/KDJ repair。",
        )
    if not qfq_factor_repair_status.automatic_macd_kdj_repair_allowed:
        return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=(
                "qfq factor repair affected codes 超过自动上限，或缺少完整 "
                "code list/hash，暂不自动触发 MACD/KDJ repair。"
            ),
        )
    return GoldStkMinsQfqMacdKdjRepairRunStatusDecision(
        target_trade_date=target_trade_date,
        selected_trade_date=qfq_factor_repair_status.repair_start_trade_date,
        reason="MACD/KDJ daily 成功，提交 scoped MACD/KDJ repair。",
        stock_codes=qfq_factor_repair_status.repair_required_codes,
        repair_required_codes_hash=qfq_factor_repair_status.repair_required_codes_hash,
        qfq_factor_repair_event_storage_ids=(
            qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        ),
    )


def _run_config_for_repair_decision(
    decision: GoldStkMinsQfqMacdKdjRepairRunStatusDecision,
) -> dict[str, object]:
    return {
        "ops": {
            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                "config": {
                    "start_trade_date": decision.selected_trade_date,
                    "freqs": list(STK_MINS_QFQ_FREQS),
                    "stock_codes": list(decision.stock_codes),
                    "reason": f"qfq_factor_repair:{decision.target_trade_date}",
                    "repair_required_codes_hash": decision.repair_required_codes_hash,
                    "source_qfq_factor_repair_event_storage_ids": list(
                        decision.qfq_factor_repair_event_storage_ids
                    ),
                }
            }
        }
    }


def _run_request_for_repair_decision(
    decision: GoldStkMinsQfqMacdKdjRepairRunStatusDecision,
) -> dg.RunRequest:
    qfq_event_identity = gold_stk_mins_qfq_macd_kdj_repair_event_storage_ids_identity(
        decision.qfq_factor_repair_event_storage_ids
    )
    return dg.RunRequest(
        run_key=(
            "gold_stk_mins_qfq_macd_kdj_repair:"
            f"{decision.target_trade_date}:"
            f"{decision.repair_required_codes_hash}:"
            f"{qfq_event_identity}"
        ),
        run_config=_run_config_for_repair_decision(decision),
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stk_mins_qfq_macd_kdj_repair_job,
    monitored_jobs=[gold_stk_mins_qfq_macd_kdj_daily_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "MACD/KDJ daily 成功后，按同日 qfq factor repair affected codes 自动触发 "
        "scoped MACD/KDJ repair；超过 500 个代码时只 skip。"
    ),
)
def gold_stk_mins_qfq_macd_kdj_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    target_trade_date = _trade_date_from_dagster_run(context.dagster_run)
    qfq_factor_repair_status = None
    macd_kdj_daily_ready = False
    if target_trade_date is not None:
        qfq_factor_repair_status = (
            gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status(
                context.instance,
                target_trade_date,
            )
        )
        macd_kdj_daily_status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS,
            partition_key=target_trade_date,
        )
        macd_kdj_daily_ready = macd_kdj_daily_status.ready

    decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
        target_trade_date=target_trade_date,
        qfq_factor_repair_status=qfq_factor_repair_status,
        macd_kdj_daily_ready=macd_kdj_daily_ready,
    )
    if decision.selected_trade_date is None:
        return dg.SkipReason(decision.reason)
    return _run_request_for_repair_decision(decision)
