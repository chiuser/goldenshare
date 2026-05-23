import dagster as dg

from orchestrator.defs.assets.market_major_indices import gold_market_major_indices


market_major_indices_update_job = dg.define_asset_job(
    name="market_major_indices_update_job",
    selection=(
        dg.AssetSelection.assets(gold_market_major_indices)
        | dg.AssetSelection.checks_for_assets(gold_market_major_indices)
    ),
    description="更新首页主要指数名单资产。",
)
