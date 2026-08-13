"""Single-partition job for canonical ordinary-index Gold minute bars."""

import dagster as dg

from orchestrator.defs.assets.index_mins_gold import GOLD_INDEX_MINS_ASSETS
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_GOLD_JOB_NAME

gold_index_mins_update_job = dg.define_asset_job(
    name=INDEX_MINS_GOLD_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(*GOLD_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_a_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按单日分区生成七频度指数 Gold 业务 K 线并执行核心 checks。",
)

__all__ = ["gold_index_mins_update_job"]
