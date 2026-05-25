import dagster as dg

from orchestrator.defs.assets.index_daily import silver_index_daily


silver_index_daily_update_job = dg.define_asset_job(
    name="silver_index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(silver_index_daily)
        | dg.AssetSelection.checks_for_assets(silver_index_daily)
    ),
    description="按交易日生成指数日线 silver 分区。",
)
