import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq


gold_stock_daily_qfq_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq)
    ),
    description="在股票日线和复权因子 silver ready 后，更新股票日线前复权 gold 资产。",
)
