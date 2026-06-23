import dagster as dg

from orchestrator.defs.assets.index_daily import (
    raw_index_daily,
    raw_tushare_index_daily_by_code,
)


index_daily_update_job = dg.define_asset_job(
    name="index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_index_daily_by_code)
        | dg.AssetSelection.checks_for_assets(raw_tushare_index_daily_by_code)
    ),
    description="按指数代码更新 Tushare index_daily 原始表。",
)


raw_index_daily_update_job = dg.define_asset_job(
    name="raw_index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_index_daily)
        | dg.AssetSelection.checks_for_assets(raw_index_daily)
    ),
    description="按交易日从 prod core DB 只读同步指数日线 raw by-date 分区。",
)
