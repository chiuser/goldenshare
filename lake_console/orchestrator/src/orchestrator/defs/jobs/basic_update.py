import dagster as dg

from orchestrator.defs.assets.stock_basic import raw_tushare_stock_basic, silver_stock_basic


basic_update_job = dg.define_asset_job(
    name="basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stock_basic, silver_stock_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stock_basic, silver_stock_basic)
    ),
    description="Low-frequency job that updates Tushare stock_basic raw/silver assets.",
)
