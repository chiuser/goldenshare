import dagster as dg

from orchestrator.defs.assets.market_major_indices import gold_market_major_indices


market_major_indices_initialize_job = dg.define_asset_job(
    name="market_major_indices_initialize_job",
    selection=(
        dg.AssetSelection.assets(gold_market_major_indices)
        | dg.AssetSelection.checks_for_assets(gold_market_major_indices)
    ),
    config={
        "ops": {
            "gold_market_major_indices": {
                "config": {
                    "source_mode": "prod_initialization",
                }
            }
        }
    },
    description="从生产主要指数配置一次性初始化本地首页主要指数名单。",
)
