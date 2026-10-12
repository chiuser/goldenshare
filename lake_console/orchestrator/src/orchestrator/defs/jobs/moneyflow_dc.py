"""Independent layer selections for daily DC stock moneyflow updates."""

import dagster as dg

from orchestrator.defs.assets.moneyflow_dc import (
    raw_tushare_moneyflow_dc,
    silver_moneyflow_dc,
)
from orchestrator.defs.partitions import cn_a_moneyflow_dc_trade_days

raw_tushare_moneyflow_dc_update_job = dg.define_asset_job(
    name="raw_tushare_moneyflow_dc_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_moneyflow_dc)
    | dg.AssetSelection.checks_for_assets(raw_tushare_moneyflow_dc),
    partitions_def=cn_a_moneyflow_dc_trade_days,
    description="仅采集东方财富个股资金流Raw并执行同分区blocking file check。",
)

silver_moneyflow_dc_update_job = dg.define_asset_job(
    name="silver_moneyflow_dc_update_job",
    selection=dg.AssetSelection.assets(silver_moneyflow_dc)
    | dg.AssetSelection.checks_for_assets(silver_moneyflow_dc),
    partitions_def=cn_a_moneyflow_dc_trade_days,
    description="只读同日已绿Raw，仅生成东方财富个股资金流Silver并执行逐字段对账check。",
)
