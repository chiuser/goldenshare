"""One retirement job, one explicit frequency per run."""

import dagster as dg

from orchestrator.defs.ops.raw_stock_period_retirement_cleanup import (
    raw_stock_period_retirement_cleanup_op,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import JOB_NAME


@dg.job(
    name=JOB_NAME,
    executor_def=dg.in_process_executor,
    description="当期Raw成功后，按已确认退市名单清理本频历史；原范围整批重跑并交付同频Silver。",
)
def raw_stock_period_retirement_cleanup_job():
    raw_stock_period_retirement_cleanup_op()
