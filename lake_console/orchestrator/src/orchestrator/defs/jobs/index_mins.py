"""Single-partition jobs for index minute Raw and Silver assets."""

import dagster as dg

from orchestrator.defs.assets.index_mins_raw import RAW_INDEX_MINS_ASSETS
from orchestrator.defs.assets.index_mins_silver_defs import SILVER_INDEX_MINS_ASSETS
from orchestrator.defs.partitions import cn_a_index_mins_trade_days


raw_index_mins_update_job = dg.define_asset_job(
    name="raw_index_mins_update_job",
    selection=(
        dg.AssetSelection.assets(*RAW_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_a_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按专属指数分钟线交易日分区同步五个 Prod-backed Raw 频率。",
)


silver_index_mins_update_job = dg.define_asset_job(
    name="silver_index_mins_update_job",
    selection=(
        dg.AssetSelection.assets(*SILVER_INDEX_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*SILVER_INDEX_MINS_ASSETS)
    ),
    partitions_def=cn_a_index_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="按专属指数分钟线交易日分区生成五个原生及两个派生 Silver 频率。",
)


__all__ = ["raw_index_mins_update_job", "silver_index_mins_update_job"]
