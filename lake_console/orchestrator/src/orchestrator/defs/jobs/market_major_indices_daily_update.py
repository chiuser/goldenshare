import dagster as dg

from orchestrator.defs.assets.market_major_indices import gold_market_major_indices_daily


market_major_indices_daily_update_job = dg.define_asset_job(
    name="market_major_indices_daily_update_job",
    selection=(
        dg.AssetSelection.assets(gold_market_major_indices_daily)
        | dg.AssetSelection.checks_for_assets(gold_market_major_indices_daily)
    ),
    description="按交易日生成首页主要指数日线 gold 分区。",
)
