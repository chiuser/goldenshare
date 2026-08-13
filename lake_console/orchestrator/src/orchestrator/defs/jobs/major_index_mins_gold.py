"""Single-partition job for canonical major-index Gold minute bars."""

import dagster as dg

from orchestrator.defs.assets.major_index_mins_gold import GOLD_MAJOR_INDEX_MINS_ASSETS
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_JOB_NAME,
)

gold_major_index_mins_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_MINS_GOLD_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(*GOLD_MAJOR_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_MAJOR_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_major_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按单日分区生成七频度主要指数 Gold 业务 K 线并执行核心 checks。",
)

__all__ = ["gold_major_index_mins_update_job"]
