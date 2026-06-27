import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.partitions import cn_a_stock_trade_days


gold_stock_daily_qfq_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq)
    ),
    description="在股票日线和复权因子 silver ready 后，更新股票日线前复权 gold 资产。",
)


gold_stock_daily_qfq_check_refresh_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_check_refresh_job",
    selection=dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq),
    partitions_def=cn_a_stock_trade_days,
    executor_def=dg.in_process_executor,
    description=(
        "仅刷新股票日线前复权 gold 资产的 ordinary asset checks；"
        "不 materialize 资产，不重写 Parquet。"
    ),
)
