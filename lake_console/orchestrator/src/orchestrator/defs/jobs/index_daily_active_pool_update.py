import dagster as dg

from orchestrator.defs.assets.index_daily_active_pool import silver_index_daily_active_pool


index_daily_active_pool_update_job = dg.define_asset_job(
    name="index_daily_active_pool_update_job",
    selection=(
        dg.AssetSelection.assets(silver_index_daily_active_pool)
        | dg.AssetSelection.checks_for_assets(silver_index_daily_active_pool)
    ),
    description="按完整成员列表维护指数日线有效池，并重新生成标准资产。",
)
