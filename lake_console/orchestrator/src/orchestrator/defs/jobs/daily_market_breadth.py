import dagster as dg

from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily


daily_market_breadth_job = dg.define_asset_job(
    name="daily_market_breadth_job",
    selection=(
        dg.AssetSelection.assets(gold_market_breadth_daily)
        | dg.AssetSelection.checks_for_assets(gold_market_breadth_daily)
    ),
    description="更新市场涨跌分布日表。",
)
