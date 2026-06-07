import dagster as dg

from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily


raw_stock_daily_update_job = dg.define_asset_job(
    name="raw_stock_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stock_daily)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stock_daily)
    ),
    description="更新股票日线 raw 资产，要求基础信息、停复牌和 Tushare 源站就绪。",
)


silver_stock_daily_update_job = dg.define_asset_job(
    name="silver_stock_daily_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_daily)
        | dg.AssetSelection.checks_for_assets(silver_stock_daily)
    ),
    description="在股票日线 raw 通过 blocking checks 后，更新股票日线 silver 资产。",
)
