import dagster as dg

from orchestrator.defs.assets.calendar import raw_tushare_trade_calendar, silver_trade_calendar


calendar_update_job = dg.define_asset_job(
    name="calendar_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_trade_calendar, silver_trade_calendar)
        | dg.AssetSelection.checks_for_assets(raw_tushare_trade_calendar, silver_trade_calendar)
    ),
    description="更新交易日历原始表和标准表。",
)
