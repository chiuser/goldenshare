"""Single-partition daily job for major-index minute technical assets."""

import dagster as dg

from orchestrator.defs.assets.major_index_mins_technical import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
)

gold_major_index_mins_technical_daily_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(*GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS)
        | dg.AssetSelection.checks_for_assets(
            *GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS
        )
    ),
    partitions_def=cn_major_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description=(
        "按单日分区生成七频度主要指数分钟线技术指标和日终递推状态，"
        "并执行全部 blocking checks。"
    ),
)


__all__ = ["gold_major_index_mins_technical_daily_update_job"]
