"""Single-partition jobs for daily index technical factors."""

import dagster as dg

from orchestrator.defs.assets.idx_factor_pro_raw import (
    raw_tushare_idx_factor_pro,
)
from orchestrator.defs.assets.idx_factor_pro_silver import (
    silver_index_factor_pro,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_JOB_NAME,
    IDX_FACTOR_PRO_SILVER_JOB_NAME,
)

raw_tushare_idx_factor_pro_update_job = dg.define_asset_job(
    name=IDX_FACTOR_PRO_RAW_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(raw_tushare_idx_factor_pro)
        | dg.AssetSelection.checks_for_assets(raw_tushare_idx_factor_pro)
    ),
    partitions_def=cn_major_index_factor_trade_days,
    executor_def=dg.in_process_executor,
    description="按专属交易日分区同步主要指数日级技术因子 Raw。",
)

silver_index_factor_pro_update_job = dg.define_asset_job(
    name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(silver_index_factor_pro)
        | dg.AssetSelection.checks_for_assets(silver_index_factor_pro)
    ),
    partitions_def=cn_major_index_factor_trade_days,
    executor_def=dg.in_process_executor,
    description="Raw 同分区 ready 后生成主要指数日级技术因子 Silver。",
)


__all__ = [
    "raw_tushare_idx_factor_pro_update_job",
    "silver_index_factor_pro_update_job",
]
