"""Daily and manual single-partition entry point."""

import dagster as dg

from orchestrator.defs.assets.major_index_quantitative_structure import (
    gold_major_index_quantitative_structure,
)
from orchestrator.defs.partitions import (
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_JOB,
)

gold_major_index_quantitative_structure_update_job = dg.define_asset_job(
    name=STRUCTURE_JOB,
    selection=dg.AssetSelection.assets(gold_major_index_quantitative_structure),
    partitions_def=cn_major_index_quantitative_structure_trade_days,
    executor_def=dg.in_process_executor,
    description="日线和四个分钟周期齐备后，计算指定交易日的量化结构。",
)
