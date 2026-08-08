"""Asset job for the four minute QFQ nine-turn Gold partitions."""

import dagster as dg

from orchestrator.defs.assets.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_ASSETS,
)


gold_stk_mins_qfq_nineturn_update_job = dg.define_asset_job(
    name="gold_stk_mins_qfq_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(*GOLD_STK_MINS_QFQ_NINETURN_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_STK_MINS_QFQ_NINETURN_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description=(
        "在分钟前复权行情和因子修复状态就绪后，按同一交易日生成 30、60、90、120 分钟前复权九转并运行聚合检查。"
    ),
)
