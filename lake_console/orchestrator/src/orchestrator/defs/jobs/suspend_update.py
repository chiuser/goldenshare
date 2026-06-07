import dagster as dg

from orchestrator.defs.assets.suspend_d import raw_tushare_suspend_d, silver_stock_suspend_daily


raw_suspend_d_update_job = dg.define_asset_job(
    name="raw_suspend_d_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_suspend_d)
        | dg.AssetSelection.checks_for_assets(raw_tushare_suspend_d)
    ),
    description="更新股票停复牌 raw 原始表。",
)


silver_suspend_d_update_job = dg.define_asset_job(
    name="silver_suspend_d_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_suspend_daily)
        | dg.AssetSelection.checks_for_assets(silver_stock_suspend_daily)
    ),
    description="在停复牌 raw ready 后，更新股票停复牌 silver 标准表。",
)
