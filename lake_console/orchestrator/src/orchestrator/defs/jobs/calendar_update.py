import dagster as dg

from orchestrator.defs.assets.calendar import raw_tushare_trade_calendar, silver_trade_calendar


calendar_update_job = dg.define_asset_job(
    name="calendar_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_trade_calendar, silver_trade_calendar)
        | dg.AssetSelection.checks_for_assets(raw_tushare_trade_calendar, silver_trade_calendar)
    ),
    description=(
        "更新 Tushare 交易日历 raw 和 A 股标准交易日历 silver，并执行交易日历字段、"
        "开市日和唯一键检查。失败后先看对应 asset check metadata。"
    ),
)
