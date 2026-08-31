"""Daily jobs for five-frequency ETF minute Raw and Silver assets."""

import dagster as dg

from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    SILVER_ETF_MINS_ASSETS,
)

raw_etf_mins_update_job = dg.define_asset_job(
    name="raw_etf_mins_update_job",
    selection=(
        dg.AssetSelection.assets(*RAW_ETF_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_ETF_MINS_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description=(
        "从 Prod DB 只读导出单日五频 ETF 分钟 Raw，并执行文件、冻结 Basic 范围和同日五频 N3 "
        "三类 blocking checks；失败不删除 Raw，也不进入 Silver。"
    ),
)

silver_etf_mins_update_job = dg.define_asset_job(
    name="silver_etf_mins_update_job",
    selection=(
        dg.AssetSelection.checks_for_assets(*RAW_ETF_MINS_ASSETS)
        | dg.AssetSelection.assets(*SILVER_ETF_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*SILVER_ETF_MINS_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description=(
        "先重跑目标日五频 Raw blocking checks；全部通过后才生成与 Raw 逐行等价的五频 Silver，"
        "不重跑 Raw writer，也不访问 Prod。"
    ),
)

__all__ = [
    "raw_etf_mins_update_job",
    "silver_etf_mins_update_job",
]
