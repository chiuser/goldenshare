import dagster as dg

from orchestrator.defs.assets.index_daily import raw_tushare_index_daily_by_code


index_daily_update_job = dg.define_asset_job(
    name="index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_index_daily_by_code)
        | dg.AssetSelection.checks_for_assets(raw_tushare_index_daily_by_code)
    ),
    description="按指数代码更新 Tushare index_daily 原始表。",
)
