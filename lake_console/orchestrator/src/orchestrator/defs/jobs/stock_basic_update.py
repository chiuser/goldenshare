import dagster as dg

from orchestrator.defs.assets.stock_basic import raw_tushare_stock_basic, silver_stock_basic


raw_stock_basic_update_job = dg.define_asset_job(
    name="raw_stock_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stock_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stock_basic)
    ),
    description="更新股票基础信息 raw full snapshot。",
)


silver_stock_basic_update_job = dg.define_asset_job(
    name="silver_stock_basic_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_basic)
        | dg.AssetSelection.checks_for_assets(silver_stock_basic)
    ),
    description="raw 股票基础信息 ready 后，更新股票基础信息 silver full snapshot。",
)
