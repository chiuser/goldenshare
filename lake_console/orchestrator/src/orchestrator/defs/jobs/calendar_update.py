import dagster as dg

from orchestrator.defs.assets.calendar import raw_tushare_trade_calendar, silver_trade_calendar


calendar_update_job = dg.define_asset_job(
    name="calendar_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_trade_calendar, silver_trade_calendar)
        | dg.AssetSelection.checks_for_assets(raw_tushare_trade_calendar, silver_trade_calendar)
    ),
    description=(
        "Low-frequency job that updates Tushare trade calendar raw/silver assets."
    ),
)
