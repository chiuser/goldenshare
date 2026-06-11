from datetime import date

import dagster as dg

from orchestrator.defs.assets.stk_mins import GOLD_STK_MINS_QFQ_ASSETS
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    GOLD_STK_MINS_QFQ_WRITER_POOL,
    build_gold_stk_mins_qfq_factor_repair_check_metadata,
)
from orchestrator.defs.stk_mins_qfq_factor_repair import (
    execute_gold_stk_mins_qfq_factor_repair,
)


GOLD_STK_MINS_QFQ_REPAIR_CHECK_ASSET_KEYS = tuple(
    asset.key for asset in GOLD_STK_MINS_QFQ_ASSETS
)

STOCK_MINS_QFQ_FACTOR_REPAIR_CONFIG_SCHEMA = {
    "trade_date": dg.Field(
        str,
        description="股票分钟线 qfq factor repair 的目标交易日，格式 YYYY-MM-DD。",
    )
}


def _trade_date_from_op_config(context: dg.OpExecutionContext) -> str:
    raw_trade_date = str(context.op_config["trade_date"]).strip()
    try:
        return date.fromisoformat(raw_trade_date).isoformat()
    except ValueError as error:
        raise ValueError("trade_date must use YYYY-MM-DD format.") from error


@dg.op(
    required_resource_keys={"lake_root", "duckdb"},
    config_schema=STOCK_MINS_QFQ_FACTOR_REPAIR_CONFIG_SCHEMA,
    pool=GOLD_STK_MINS_QFQ_WRITER_POOL,
)
def stock_mins_qfq_factor_repair_op(context: dg.OpExecutionContext) -> None:
    trade_date = _trade_date_from_op_config(context)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    report = execute_gold_stk_mins_qfq_factor_repair(
        lake_root=context.resources.lake_root.root(),
        duckdb_resource=context.resources.duckdb,
        trade_date=trade_date,
        registered_partition_keys=registered_trade_days,
    )
    missing_repair_count = max(
        report.plan.repair_required_code_count - report.repaired_code_count,
        0,
    )
    passed = (
        report.plan.can_execute_repair
        and missing_repair_count == 0
        and report.derived_failed_code_count == 0
        and report.repaired_code_count == report.plan.repair_required_code_count
    )
    metadata = build_gold_stk_mins_qfq_factor_repair_check_metadata(
        report.plan,
        producer_run_id=context.run_id,
        repair_start_trade_date=report.repair_start_trade_date,
        repair_end_trade_date=report.repair_end_trade_date,
        selected_partition_count=report.selected_partition_count,
        repaired_code_count=report.repaired_code_count,
        skipped_code_count=report.skipped_code_count,
        failed_code_count=missing_repair_count,
        rewritten_file_count=report.rewritten_file_count,
        rewritten_row_count=report.rewritten_row_count,
        repaired_file_samples=report.repaired_file_samples,
        execution_model=report.execution_model,
        planned_batch_count=report.planned_batch_count,
        executed_batch_count=report.executed_batch_count,
        non_empty_batch_count=report.non_empty_batch_count,
        derived_rewrite_required=report.derived_rewrite_required,
        derived_planned_batch_count=report.derived_planned_batch_count,
        derived_executed_batch_count=report.derived_executed_batch_count,
        derived_non_empty_batch_count=report.derived_non_empty_batch_count,
        derived_rewritten_file_count=report.derived_rewritten_file_count,
        derived_rewritten_row_count=report.derived_rewritten_row_count,
        derived_repaired_code_count=report.derived_repaired_code_count,
        derived_failed_code_count=report.derived_failed_code_count,
    )
    for asset_key in GOLD_STK_MINS_QFQ_REPAIR_CHECK_ASSET_KEYS:
        context.log_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
                check_name=GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
                passed=passed,
                metadata=metadata,
                blocking=True,
                partition=trade_date,
            )
        )
    if not passed:
        raise RuntimeError(
            "Gold qfq factor repair did not complete successfully: "
            f"trade_date={trade_date}, reason={report.plan.reason}, "
            f"missing_repair_count={missing_repair_count}, "
            f"derived_failed_code_count={report.derived_failed_code_count}."
        )
    context.log.info(
        "Gold qfq factor repair completed: trade_date=%s reason=%s "
        "repaired_code_count=%s rewritten_file_count=%s",
        trade_date,
        report.plan.reason,
        report.repaired_code_count,
        report.rewritten_file_count,
    )
