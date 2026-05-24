import dagster as dg

from orchestrator.defs.backfills.index_daily_history import (
    evaluate_index_daily_history_backfill_checks,
    materialize_index_daily_history_backfill,
)


@dg.job(description="按交易日区间受控回补指数日线原始表和标准表。")
def index_daily_history_backfill_job():
    evaluate_index_daily_history_backfill_checks(materialize_index_daily_history_backfill())
