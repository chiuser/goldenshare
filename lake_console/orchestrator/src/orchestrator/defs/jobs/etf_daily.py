"""Single-partition Raw jobs for ETF daily source datasets."""

import dagster as dg

from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_JOB_NAME,
    RAW_FUND_DAILY_JOB_NAME,
)

raw_fund_daily_update_job = dg.define_asset_job(
    name=RAW_FUND_DAILY_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(raw_tushare_fund_daily)
        | dg.AssetSelection.checks_for_assets(raw_tushare_fund_daily)
    ),
    partitions_def=cn_a_etf_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="同步一个交易日的基金日线 Raw，并运行三个阻断检查。",
)

raw_fund_adj_update_job = dg.define_asset_job(
    name=RAW_FUND_ADJ_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(raw_tushare_fund_adj)
        | dg.AssetSelection.checks_for_assets(raw_tushare_fund_adj)
    ),
    partitions_def=cn_a_etf_mins_trade_days,
    executor_def=dg.in_process_executor,
    description="同步一个交易日的基金复权因子 Raw，并运行三个阻断检查。",
)


__all__ = ["raw_fund_adj_update_job", "raw_fund_daily_update_job"]
