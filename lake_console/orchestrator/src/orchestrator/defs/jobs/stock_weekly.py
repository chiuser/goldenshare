"""Retained direct-source weekly Raw job and its blocking checks."""

import dagster as dg

from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    silver_stock_weekly,
)

raw_stk_period_bar_adj_week_update_job = dg.define_asset_job(
    "raw_stk_period_bar_adj_week_update_job",
    description="预检齐备后以当日业务日期下载完整21列，仅更新当前周；历史维护独立执行。",
    selection=dg.AssetSelection.assets(raw_tushare_stk_period_bar_adj_week)
    | dg.AssetSelection.checks_for_assets(raw_tushare_stk_period_bar_adj_week),
    executor_def=dg.in_process_executor,
)


silver_stock_weekly_update_job = dg.define_asset_job(
    "silver_stock_weekly_update_job",
    selection=dg.AssetSelection.assets(silver_stock_weekly)
    | dg.AssetSelection.checks_for_assets(silver_stock_weekly),
    executor_def=dg.in_process_executor,
)
