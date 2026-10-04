"""Layer-isolated primary weekly jobs and the manual-only alternate job."""

import dagster as dg

from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    raw_tushare_stk_period_bar_week,
    raw_tushare_weekly,
)

raw_stk_period_bar_week_update_job = dg.define_asset_job(
    "raw_stk_period_bar_week_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_stk_period_bar_week)
    | dg.AssetSelection.checks_for_assets(raw_tushare_stk_period_bar_week),
    executor_def=dg.in_process_executor,
)
raw_stk_period_bar_adj_week_update_job = dg.define_asset_job(
    "raw_stk_period_bar_adj_week_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_stk_period_bar_adj_week)
    | dg.AssetSelection.checks_for_assets(raw_tushare_stk_period_bar_adj_week),
    executor_def=dg.in_process_executor,
)
raw_tushare_weekly_update_job = dg.define_asset_job(
    "raw_tushare_weekly_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_weekly)
    | dg.AssetSelection.checks_for_assets(raw_tushare_weekly),
    executor_def=dg.in_process_executor,
)
