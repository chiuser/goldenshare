"""Independent stock period factor-change history job."""

import dagster as dg

from orchestrator.defs.ops.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_op,
)
from orchestrator.defs.run_contracts.stock_period_history_repair import JOB_NAME


@dg.job(
    name=JOB_NAME,
    executor_def=dg.in_process_executor,
    description="自动回刷复权因子变化的两频历史，或按明确名单和记录键人工维护所选频率；失败整批重跑。",
)
def raw_stock_period_history_repair_job():
    raw_stock_period_history_repair_op()
