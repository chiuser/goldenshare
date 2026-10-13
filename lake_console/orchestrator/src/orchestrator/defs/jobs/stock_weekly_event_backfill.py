"""Manual checks-only bootstrap job; no schedule, sensor or asset writes."""

import dagster as dg

from orchestrator.defs.bootstrap.stock_weekly_events import BOOTSTRAP_CHECKS_JOB_NAME
from orchestrator.defs.ops.stock_weekly_bootstrap_checks import (
    report_stock_weekly_bootstrap_checks,
)


@dg.job(
    name=BOOTSTRAP_CHECKS_JOB_NAME,
    executor_def=dg.in_process_executor,
    description="手动补录已验收复权周线B0检查，每批最多33周；保留旧记录，可按同计划续跑。",
)
def raw_stk_period_bar_adj_week_event_backfill_job():
    report_stock_weekly_bootstrap_checks()
