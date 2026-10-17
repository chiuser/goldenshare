"""Retained direct-source weekly Raw job and its blocking checks."""

import dagster as dg

from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    silver_stock_weekly,
)

raw_stk_period_bar_adj_week_update_job = dg.define_asset_job(
    "raw_stk_period_bar_adj_week_update_job",
    description="Tushare HTTP直接源：先补欠账，再更新当前周；因子变更合并两频历史刷新，按冻结意图恢复。",
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
