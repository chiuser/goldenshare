import dagster as dg

from orchestrator.defs.ops.gold_stock_daily_qfq_factor_repair import (
    gold_stock_daily_qfq_factor_repair_op,
)


GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME = (
    "gold_stock_daily_qfq_factor_repair_job"
)


@dg.job(
    name=GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME,
    description=(
        "复权因子变化后，按自动计算的 affected codes 修复历史股票日线前复权分区。"
    ),
)
def gold_stock_daily_qfq_factor_repair_job() -> None:
    gold_stock_daily_qfq_factor_repair_op()
