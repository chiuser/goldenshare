import dagster as dg

from orchestrator.defs.assets.calendar import raw_tushare_trade_calendar, silver_trade_calendar
from orchestrator.defs.assets.stock_basic import raw_tushare_stock_basic, silver_stock_basic
from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily
from orchestrator.defs.assets.suspend_d import raw_tushare_suspend_d, silver_stock_suspend_daily


bootstrap_calendar_job = dg.define_asset_job(
    name="bootstrap_calendar_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_trade_calendar, silver_trade_calendar)
        | dg.AssetSelection.checks_for_assets(raw_tushare_trade_calendar, silver_trade_calendar)
    ),
    description=(
        "Migration-only job that bootstraps trade_calendar from the old lake into "
        "the new raw/silver lake paths."
    ),
)


bootstrap_basic_update_job = dg.define_asset_job(
    name="bootstrap_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stock_basic, silver_stock_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stock_basic, silver_stock_basic)
    ),
    description=(
        "Migration-only job that bootstraps stock_basic from the old lake into "
        "the new raw/silver lake paths."
    ),
)


bootstrap_quote_daily_job = dg.define_asset_job(
    name="bootstrap_quote_daily_job",
    selection=(
        dg.AssetSelection.assets(
            raw_tushare_stock_daily,
            silver_stock_daily,
            raw_tushare_suspend_d,
            silver_stock_suspend_daily,
        )
        | dg.AssetSelection.checks_for_assets(
            raw_tushare_stock_daily,
            silver_stock_daily,
            raw_tushare_suspend_d,
            silver_stock_suspend_daily,
        )
    ),
    description=(
        "Migration-only job that bootstraps quote daily raw partitions from the old lake "
        "and materializes the corresponding silver quote assets."
    ),
)
