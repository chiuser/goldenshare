import dagster as dg

from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily
from orchestrator.defs.assets.suspend_d import raw_tushare_suspend_d, silver_stock_suspend_daily


quote_daily_job = dg.define_asset_job(
    name="quote_daily_job",
    selection=(
        dg.AssetSelection.assets(
            raw_tushare_stock_daily,
            raw_tushare_suspend_d,
            silver_stock_daily,
            silver_stock_suspend_daily,
        )
        | dg.AssetSelection.checks_for_assets(
            raw_tushare_stock_daily,
            raw_tushare_suspend_d,
            silver_stock_daily,
            silver_stock_suspend_daily,
        )
    ),
    description=(
        "Daily quote job that fetches Tushare raw quote assets and materializes "
        "the corresponding silver quote assets for one trade_date partition."
    ),
)
