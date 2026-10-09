"""Independent layer selections for daily market moneyflow updates."""

import dagster as dg

from orchestrator.defs.assets.moneyflow_mkt_dc import (
    raw_tushare_moneyflow_mkt_dc,
    silver_moneyflow_mkt_dc,
)
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days

raw_tushare_moneyflow_mkt_dc_update_job = dg.define_asset_job(
    name="raw_tushare_moneyflow_mkt_dc_update_job",
    selection=dg.AssetSelection.assets(raw_tushare_moneyflow_mkt_dc)
    | dg.AssetSelection.checks_for_assets(raw_tushare_moneyflow_mkt_dc),
    partitions_def=cn_a_moneyflow_mkt_dc_trade_days,
    description="仅采集大盘资金流Raw并执行同分区blocking file check。",
)

silver_moneyflow_mkt_dc_update_job = dg.define_asset_job(
    name="silver_moneyflow_mkt_dc_update_job",
    selection=dg.AssetSelection.assets(silver_moneyflow_mkt_dc)
    | dg.AssetSelection.checks_for_assets(silver_moneyflow_mkt_dc),
    partitions_def=cn_a_moneyflow_mkt_dc_trade_days,
    description="只读同日已绿Raw，仅生成大盘资金流Silver并执行逐字段对账check。",
)
