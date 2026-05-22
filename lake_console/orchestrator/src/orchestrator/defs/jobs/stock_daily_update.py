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
    description=(
        "Partitioned stock daily job that updates only Tushare daily raw/silver "
        "assets for one trade_date partition. Upstream stock_basic and suspend_d "
        "assets must already be ready."
    ),
)
