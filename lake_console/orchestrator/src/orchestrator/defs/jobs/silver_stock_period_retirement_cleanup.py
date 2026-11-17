"""One retirement job, one explicit frequency per run."""

import dagster as dg

from orchestrator.defs.ops.silver_stock_period_retirement_cleanup import (
    silver_stock_period_retirement_cleanup_op,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import JOB_NAME


@dg.job(
    name=JOB_NAME,
    executor_def=dg.in_process_executor,
    description="当期Silver成功后，仅清理本频Silver退市股票；Raw保留，前次失败未补齐则启动即失败。",
)
def silver_stock_period_retirement_cleanup_job():
    silver_stock_period_retirement_cleanup_op()
