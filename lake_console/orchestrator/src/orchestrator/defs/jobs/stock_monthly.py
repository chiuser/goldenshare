"""Monthly primary assets and their explicit blocking checks; one source per run."""

import dagster as dg

from orchestrator.defs.assets.stock_monthly import (
    raw_tushare_stk_period_bar_adj_month,
    silver_stock_monthly,
)

raw_stk_period_bar_adj_month_update_job = dg.define_asset_job(
    "raw_stk_period_bar_adj_month_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_stk_period_bar_adj_month)
    | dg.AssetSelection.checks_for_assets(raw_tushare_stk_period_bar_adj_month),
    executor_def=dg.in_process_executor,
)


silver_stock_monthly_update_job = dg.define_asset_job(
    "silver_stock_monthly_update_job",
    selection=dg.AssetSelection.assets(silver_stock_monthly)
    | dg.AssetSelection.checks_for_assets(silver_stock_monthly),
    executor_def=dg.in_process_executor,
)
