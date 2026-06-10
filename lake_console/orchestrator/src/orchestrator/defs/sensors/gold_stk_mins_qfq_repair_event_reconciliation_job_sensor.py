from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
    gold_stk_mins_qfq_factor_repair_event_storage_ids_identity,
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.jobs.gold_stk_mins_qfq_repair_event_reconciliation import (
    gold_stk_mins_qfq_repair_event_reconciliation_job,
)
from orchestrator.defs.jobs.stock_mins_qfq_factor_repair import (
    stock_mins_qfq_factor_repair_job,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_JOB_NAME = (
    "gold_stk_mins_qfq_repair_event_reconciliation_job"
)


@dataclass(frozen=True)
class GoldStkMinsQfqRepairEventReconciliationRunStatusDecision:
    target_trade_date: str | None
    selected_trade_date: str | None
    reason: str
    repair_required_codes_hash: str | None = None
    qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()


def build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision(
    *,
    target_trade_date: str | None,
    qfq_factor_repair_status: GoldStkMinsQfqFactorRepairStatus | None,
) -> GoldStkMinsQfqRepairEventReconciliationRunStatusDecision:
    if target_trade_date is None:
        return GoldStkMinsQfqRepairEventReconciliationRunStatusDecision(
            target_trade_date=None,
            selected_trade_date=None,
            reason="无法从 qfq factor repair run config 中解析目标交易日。",
        )
    if qfq_factor_repair_status is None or not qfq_factor_repair_status.ready:
        return GoldStkMinsQfqRepairEventReconciliationRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason=(
                qfq_factor_repair_status.reason
                if qfq_factor_repair_status is not None
                else "同日 qfq factor repair 状态不可用。"
            ),
        )
    if not qfq_factor_repair_status.rewrote_history:
        return GoldStkMinsQfqRepairEventReconciliationRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason="qfq factor repair 未改写历史 qfq 文件，无需补普通 qfq 资产事件。",
        )
    if (
        qfq_factor_repair_status.repair_required_codes_hash is None
        or not qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
    ):
        return GoldStkMinsQfqRepairEventReconciliationRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason="qfq factor repair 缺少 hash 或 check event storage ids，暂不补事件。",
        )
    return GoldStkMinsQfqRepairEventReconciliationRunStatusDecision(
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason="qfq factor repair 成功改写历史 qfq，提交普通 qfq asset event reconciliation。",
        repair_required_codes_hash=qfq_factor_repair_status.repair_required_codes_hash,
        qfq_factor_repair_event_storage_ids=(
            qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        ),
    )


def _run_config_for_reconciliation_decision(
    decision: GoldStkMinsQfqRepairEventReconciliationRunStatusDecision,
) -> dict[str, object]:
    return {
        "ops": {
            "gold_stk_mins_qfq_repair_event_reconciliation_op": {
                "config": {
                    "trade_date": decision.selected_trade_date,
                    "source_qfq_factor_repair_event_storage_ids": list(
                        decision.qfq_factor_repair_event_storage_ids
                    ),
                    "repair_required_codes_hash": (
                        decision.repair_required_codes_hash
                    ),
                }
            }
        }
    }


def _run_request_for_reconciliation_decision(
    decision: GoldStkMinsQfqRepairEventReconciliationRunStatusDecision,
) -> dg.RunRequest:
    qfq_event_identity = gold_stk_mins_qfq_factor_repair_event_storage_ids_identity(
        decision.qfq_factor_repair_event_storage_ids
    )
    return dg.RunRequest(
        run_key=(
            "gold_stk_mins_qfq_repair_event_reconciliation:"
            f"{decision.target_trade_date}:"
            f"{decision.repair_required_codes_hash}:"
            f"{qfq_event_identity}"
        ),
        run_config=_run_config_for_reconciliation_decision(decision),
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stk_mins_qfq_repair_event_reconciliation_job,
    monitored_jobs=[stock_mins_qfq_factor_repair_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "qfq factor repair 成功后，如果它改写了历史 gold qfq 文件，则补发普通 "
        "qfq asset partitions 的 runless materialization/check events。"
    ),
)
def gold_stk_mins_qfq_repair_event_reconciliation_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    target_trade_date = _trade_date_from_factor_repair_run(context.dagster_run)
    qfq_factor_repair_status = None
    if target_trade_date is not None:
        qfq_factor_repair_status = gold_stk_mins_qfq_factor_repair_status(
            context.instance,
            target_trade_date,
        )

    decision = build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision(
        target_trade_date=target_trade_date,
        qfq_factor_repair_status=qfq_factor_repair_status,
    )
    if decision.selected_trade_date is None:
        return dg.SkipReason(decision.reason)
    return _run_request_for_reconciliation_decision(decision)


def _trade_date_from_factor_repair_run(dagster_run: object) -> str | None:
    return _trade_date_from_run_config(getattr(dagster_run, "run_config", None))


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


def _normalize_trade_date(raw_trade_date: object) -> str | None:
    if raw_trade_date is None:
        return None
    try:
        return date.fromisoformat(str(raw_trade_date).strip()).isoformat()
    except ValueError:
        return None
