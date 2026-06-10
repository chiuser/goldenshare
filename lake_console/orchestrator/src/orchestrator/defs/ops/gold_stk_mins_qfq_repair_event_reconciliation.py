from datetime import date

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_repair_reconciliation_events import (
    report_stk_mins_qfq_repair_reconciliation_events,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_CONFIG_SCHEMA = {
    "trade_date": dg.Field(
        str,
        description="qfq factor repair 的目标交易日，格式 YYYY-MM-DD。",
    ),
    "source_qfq_factor_repair_event_storage_ids": dg.Field(
        [int],
        description="触发本次普通 qfq 事件补账的 qfq factor repair check event storage id 列表。",
    ),
    "repair_required_codes_hash": dg.Field(
        str,
        description="来自 qfq factor repair affected codes 的稳定 SHA-256 hash。",
    ),
}


def _trade_date_from_op_config(context: dg.OpExecutionContext) -> str:
    raw_trade_date = str(context.op_config["trade_date"]).strip()
    try:
        return date.fromisoformat(raw_trade_date).isoformat()
    except ValueError as error:
        raise ValueError("trade_date must use YYYY-MM-DD format.") from error


def _source_event_ids_from_op_config(context: dg.OpExecutionContext) -> tuple[int, ...]:
    raw_event_ids = context.op_config["source_qfq_factor_repair_event_storage_ids"]
    event_ids = tuple(sorted(int(event_id) for event_id in raw_event_ids))
    if not event_ids:
        raise ValueError(
            "source_qfq_factor_repair_event_storage_ids must not be empty."
        )
    return event_ids


def _repair_required_codes_hash_from_op_config(context: dg.OpExecutionContext) -> str:
    repair_required_codes_hash = str(
        context.op_config["repair_required_codes_hash"]
    ).strip()
    if not repair_required_codes_hash:
        raise ValueError("repair_required_codes_hash must not be empty.")
    return repair_required_codes_hash


@dg.op(
    required_resource_keys={"lake_root", "duckdb"},
    config_schema=GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_CONFIG_SCHEMA,
)
def gold_stk_mins_qfq_repair_event_reconciliation_op(
    context: dg.OpExecutionContext,
) -> None:
    trade_date = _trade_date_from_op_config(context)
    expected_event_ids = _source_event_ids_from_op_config(context)
    expected_codes_hash = _repair_required_codes_hash_from_op_config(context)

    qfq_factor_repair_status = gold_stk_mins_qfq_factor_repair_status(
        context.instance,
        trade_date,
    )
    _assert_reconciliation_source_matches_latest_repair(
        qfq_factor_repair_status=qfq_factor_repair_status,
        expected_event_ids=expected_event_ids,
        expected_codes_hash=expected_codes_hash,
    )

    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    report = report_stk_mins_qfq_repair_reconciliation_events(
        instance=context.instance,
        lake_root=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_partition_keys=registered_trade_days,
        qfq_factor_repair_status=qfq_factor_repair_status,
    )
    context.log.info(
        "Gold qfq repair event reconciliation completed: trade_date=%s "
        "asset_partition_count=%s reported_event_count=%s reason=%s",
        trade_date,
        report.plan.asset_partition_count,
        report.reported_event_count,
        report.plan.reason,
    )


def _assert_reconciliation_source_matches_latest_repair(
    *,
    qfq_factor_repair_status,
    expected_event_ids: tuple[int, ...],
    expected_codes_hash: str,
) -> None:
    if not qfq_factor_repair_status.ready:
        raise dg.Failure(
            "qfq repair event reconciliation requires ready qfq factor repair checks: "
            f"trade_date={qfq_factor_repair_status.trade_date}, "
            f"reason={qfq_factor_repair_status.reason}."
        )
    if not qfq_factor_repair_status.rewrote_history:
        return
    if (
        qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        != expected_event_ids
    ):
        raise dg.Failure(
            "qfq repair event reconciliation source event ids do not match latest "
            "qfq factor repair check events: "
            f"trade_date={qfq_factor_repair_status.trade_date}."
        )
    if qfq_factor_repair_status.repair_required_codes_hash != expected_codes_hash:
        raise dg.Failure(
            "qfq repair event reconciliation repair_required_codes_hash does not "
            "match latest qfq factor repair metadata: "
            f"trade_date={qfq_factor_repair_status.trade_date}."
        )
