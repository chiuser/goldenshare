"""Asset job for the daily QFQ nine-turn Gold partition."""

import dagster as dg

from orchestrator.defs.assets.qfq_nineturn import gold_stock_daily_qfq_nineturn


gold_stock_daily_qfq_nineturn_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq_nineturn)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq_nineturn)
    ),
    description=(
        "在日线前复权行情和复权因子修复状态就绪后，生成单个交易日的股票日线前复权九转并运行聚合检查。"
    ),
)
