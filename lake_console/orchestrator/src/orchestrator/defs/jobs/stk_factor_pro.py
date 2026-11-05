"""Single execution process for stock technical factor daily updates."""

import dagster as dg

from orchestrator.defs.assets.stk_factor_pro import stk_factor_pro
from orchestrator.defs.partitions import cn_a_stock_factor_pro_trade_days
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_UPDATE_JOB_NAME,
)

raw_tushare_stk_factor_pro_update_job = dg.define_asset_job(
    name=STK_FACTOR_PRO_UPDATE_JOB_NAME,
    selection=dg.AssetSelection.assets(stk_factor_pro)
    | dg.AssetSelection.checks_for_assets(stk_factor_pro),
    partitions_def=cn_a_stock_factor_pro_trade_days,
    executor_def=dg.in_process_executor,
    description="同一运行完成股票技术因子日数据、两层检查及必要的历史回刷。",
)
