import dagster as dg

from orchestrator.defs.assets.index_daily_active_pool import silver_index_daily_active_pool


index_daily_active_pool_initialize_job = dg.define_asset_job(
    name="index_daily_active_pool_initialize_job",
    selection=(
        dg.AssetSelection.assets(silver_index_daily_active_pool)
        | dg.AssetSelection.checks_for_assets(silver_index_daily_active_pool)
    ),
    config={
        "ops": {
            "silver_index_daily_active_pool": {
                "config": {
                    "source_mode": "prod_initialization",
                }
            }
        }
    },
    description="从生产指数日线有效池一次性初始化本地指数日线有效池。",
)
