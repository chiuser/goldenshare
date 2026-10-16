"""Manual event reporting for completed Raw files; no download or Parquet writes."""

import dagster as dg

BOOTSTRAP_CHECKS_JOB_NAME = "raw_stk_period_bar_adj_week_event_backfill_job"
from orchestrator.defs.ops.stock_weekly_bootstrap_checks import (
    report_stock_weekly_bootstrap_checks,
)


@dg.job(
    name=BOOTSTRAP_CHECKS_JOB_NAME,
    executor_def=dg.in_process_executor,
    description="手动补录新直接源执行receipt的周线物化/checks；保留旧记录，只补缺失事件。",
)
def raw_stk_period_bar_adj_week_event_backfill_job():
    report_stock_weekly_bootstrap_checks()
