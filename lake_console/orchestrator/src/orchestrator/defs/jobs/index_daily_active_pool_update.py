import dagster as dg

from orchestrator.defs.assets.index_daily_active_pool import silver_index_daily_active_pool


index_daily_active_pool_update_job = dg.define_asset_job(
    name="index_daily_active_pool_update_job",
    selection=(
        dg.AssetSelection.assets(silver_index_daily_active_pool)
        | dg.AssetSelection.checks_for_assets(silver_index_daily_active_pool)
    ),
    description="更新指数日线有效指数池标准资产。",
)
