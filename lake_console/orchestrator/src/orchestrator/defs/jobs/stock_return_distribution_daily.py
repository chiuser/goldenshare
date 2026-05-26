import dagster as dg

from orchestrator.defs.assets.stock_return_distribution import gold_stock_return_distribution


stock_return_distribution_daily_job = dg.define_asset_job(
    name="stock_return_distribution_daily_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_return_distribution)
        | dg.AssetSelection.checks_for_assets(gold_stock_return_distribution)
    ),
    description="更新股票涨跌幅区间分布日表。",
)
