"""Single-partition jobs for major-index minute Raw and Silver assets."""

import dagster as dg

from orchestrator.defs.assets.major_index_mins_raw import (
    RAW_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_JOB_NAME,
    MAJOR_INDEX_MINS_SILVER_JOB_NAME,
)


raw_major_index_mins_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(*RAW_MAJOR_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_MAJOR_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_major_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按专属交易日分区同步五个主要指数分钟线 Raw 频率。",
)

silver_major_index_mins_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(*SILVER_MAJOR_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*SILVER_MAJOR_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_major_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按专属交易日分区生成主要指数分钟线原生及派生 Silver 频率。",
)

__all__ = [
    "raw_major_index_mins_update_job",
    "silver_major_index_mins_update_job",
]
