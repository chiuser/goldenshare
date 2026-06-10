import dagster as dg

from orchestrator.defs.ops.gold_stk_mins_qfq_repair_event_reconciliation import (
    gold_stk_mins_qfq_repair_event_reconciliation_op,
)


GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_JOB_NAME = (
    "gold_stk_mins_qfq_repair_event_reconciliation_job"
)


@dg.job(
    name=GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_JOB_NAME,
    executor_def=dg.in_process_executor,
    description=(
        "qfq factor repair 成功改写历史 gold qfq 后，补发受影响普通 qfq "
        "asset partitions 的 runless materialization/check events。"
    ),
)
def gold_stk_mins_qfq_repair_event_reconciliation_job() -> None:
    gold_stk_mins_qfq_repair_event_reconciliation_op()
