import dagster as dg

from orchestrator.defs.assets.wealth_market_turnover import gold_wealth_market_turnover


gold_wealth_market_turnover_update_job = dg.define_asset_job(
    name="gold_wealth_market_turnover_update_job",
    selection=(
        dg.AssetSelection.assets(gold_wealth_market_turnover)
        | dg.AssetSelection.checks_for_assets(gold_wealth_market_turnover)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成财富市场成交额 gold 快照。",
)
