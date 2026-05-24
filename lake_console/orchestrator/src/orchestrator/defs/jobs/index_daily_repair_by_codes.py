import dagster as dg

from orchestrator.defs.backfills.index_daily_repair_by_codes import (
    evaluate_index_daily_repair_by_codes_checks,
    repair_index_daily_by_codes,
)


@dg.job(description="按指数代码修复指数日线缺漏数据。")
def index_daily_repair_by_codes_job():
    evaluate_index_daily_repair_by_codes_checks(repair_index_daily_by_codes())
