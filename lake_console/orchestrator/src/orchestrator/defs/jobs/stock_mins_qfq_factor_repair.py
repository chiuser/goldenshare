import dagster as dg

from orchestrator.defs.ops.stock_mins_qfq_factor_repair import (
    stock_mins_qfq_factor_repair_op,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME = "stock_mins_qfq_factor_repair_job"


@dg.job(
    name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
    partitions_def=cn_a_stock_mins_silver_trade_days,
    executor_def=dg.in_process_executor,
    description=(
        "检测股票分钟线 qfq 最新复权因子变化；无变化则记录成功，有变化则逐股票回刷历史 gold qfq。"
    ),
)
def stock_mins_qfq_factor_repair_job() -> None:
    stock_mins_qfq_factor_repair_op()
