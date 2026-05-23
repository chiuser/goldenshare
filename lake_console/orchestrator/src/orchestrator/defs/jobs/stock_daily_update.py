import dagster as dg

from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily


stock_daily_update_job = dg.define_asset_job(
    name="stock_daily_update_job",
    selection=(
        dg.AssetSelection.assets(
            raw_tushare_stock_daily,
            silver_stock_daily,
        )
        | dg.AssetSelection.checks_for_assets(
            raw_tushare_stock_daily,
            silver_stock_daily,
        )
    ),
    description="更新股票日线原始表和标准表，要求基础信息和停复牌已就绪。",
)
