"""Asset jobs for the daily stock nine-turn dataset."""

import dagster as dg

from orchestrator.defs.assets.stk_nineturn import (
    raw_tushare_stk_nineturn,
    silver_stock_nineturn_daily,
)


raw_stk_nineturn_update_job = dg.define_asset_job(
    name="raw_stk_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stk_nineturn)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stk_nineturn)
    ),
    description="从 Tushare 更新单个交易日的神奇九转 raw 分区并运行两个 blocking checks。",
)


silver_stock_nineturn_daily_update_job = dg.define_asset_job(
    name="silver_stock_nineturn_daily_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_nineturn_daily)
        | dg.AssetSelection.checks_for_assets(silver_stock_nineturn_daily)
    ),
    description=(
        "把单个交易日神奇九转 Raw 分区按统一股票身份映射规范化为 Silver，"
        "并运行两个 blocking checks。"
    ),
)
