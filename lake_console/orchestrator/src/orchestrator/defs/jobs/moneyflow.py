"""Independent layer selections for daily traditional stock moneyflow updates."""

import dagster as dg

from orchestrator.defs.assets.moneyflow import (
    raw_tushare_moneyflow,
    silver_moneyflow,
)
from orchestrator.defs.partitions import cn_a_moneyflow_trade_days

raw_tushare_moneyflow_update_job = dg.define_asset_job(
    name="raw_tushare_moneyflow_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_moneyflow)
    | dg.AssetSelection.checks_for_assets(raw_tushare_moneyflow),
    partitions_def=cn_a_moneyflow_trade_days,
    description="仅采集个股资金流Raw并执行同分区blocking file check。",
)

silver_moneyflow_update_job = dg.define_asset_job(
    name="silver_moneyflow_update_job",
    selection=dg.AssetSelection.assets(silver_moneyflow)
    | dg.AssetSelection.checks_for_assets(silver_moneyflow),
    partitions_def=cn_a_moneyflow_trade_days,
    description="只读同日已绿Raw，仅生成个股资金流Silver并执行逐字段对账check。",
)
