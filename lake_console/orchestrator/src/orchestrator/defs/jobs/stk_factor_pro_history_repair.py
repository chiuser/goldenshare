"""The stock technical factor administrator's historical repair job."""

import dagster as dg

from orchestrator.defs.ops.stk_factor_pro_history_repair import (
    repair_stk_factor_pro_history,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_REPAIR_JOB_NAME,
)


@dg.job(
    name=STK_FACTOR_PRO_REPAIR_JOB_NAME,
    executor_def=dg.in_process_executor,
    description="按已批准的原范围重新下载并回刷股票技术因子的历史 Raw 和 Silver。",
)
def raw_tushare_stk_factor_pro_repair_job():
    repair_stk_factor_pro_history()
