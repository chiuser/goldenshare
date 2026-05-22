import dagster as dg

from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily
from orchestrator.defs.assets.suspend_d import raw_tushare_suspend_d, silver_stock_suspend_daily


stock_quote_daily_update_job = dg.define_asset_job(
    name="stock_quote_daily_update_job",
    selection=(
        dg.AssetSelection.assets(
            raw_tushare_suspend_d,
            silver_stock_suspend_daily,
            raw_tushare_stock_daily,
            silver_stock_daily,
        )
        | dg.AssetSelection.checks_for_assets(
            raw_tushare_suspend_d,
            silver_stock_suspend_daily,
            raw_tushare_stock_daily,
            silver_stock_daily,
        )
    ),
    description=(
        "Partitioned stock quote job that updates suspend_d and daily raw/silver "
        "assets for one trade_date partition."
    ),
)
