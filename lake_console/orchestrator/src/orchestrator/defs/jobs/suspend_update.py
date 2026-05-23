import dagster as dg

from orchestrator.defs.assets.suspend_d import raw_tushare_suspend_d, silver_stock_suspend_daily


suspend_update_job = dg.define_asset_job(
    name="suspend_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_suspend_d, silver_stock_suspend_daily)
        | dg.AssetSelection.checks_for_assets(raw_tushare_suspend_d, silver_stock_suspend_daily)
    ),
    description="更新股票停复牌原始表和标准表。",
)
