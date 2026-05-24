import dagster as dg

from orchestrator.defs.assets.index_daily import raw_tushare_index_daily, silver_index_daily


index_daily_update_job = dg.define_asset_job(
    name="index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_index_daily, silver_index_daily)
        | dg.AssetSelection.checks_for_assets(raw_tushare_index_daily, silver_index_daily)
    ),
    description="更新指数日线原始表和标准表。",
)
