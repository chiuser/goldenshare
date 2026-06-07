import dagster as dg

from orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair import (
    gold_stk_mins_qfq_macd_kdj_repair_op,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_JOB_NAME = "gold_stk_mins_qfq_macd_kdj_repair_job"


@dg.job(
    name=GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_JOB_NAME,
    executor_def=dg.in_process_executor,
    description="从指定起始交易日向后重算股票分钟线 qfq MACD/KDJ 指标和 state。",
)
def gold_stk_mins_qfq_macd_kdj_repair_job() -> None:
    gold_stk_mins_qfq_macd_kdj_repair_op()
