import dagster as dg

from orchestrator.defs.assets.calendar import (
    raw_tushare_trade_calendar,
    silver_trade_calendar,
)

calendar_update_job = dg.define_asset_job(
    name="calendar_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_trade_calendar, silver_trade_calendar)
        | dg.AssetSelection.checks_for_assets(raw_tushare_trade_calendar, silver_trade_calendar)
    ),
    description=(
        "读取 Tushare 已发布的全部上交所交易日历，分层校验候选文件后更新 Raw 和 Silver，"
        "并执行正式交易日历检查。失败后先看对应 asset check metadata。"
    ),
)
