"""Single-partition jobs for the board Raw assets."""

import dagster as dg

from orchestrator.defs.assets.dc_board_raw import (
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)


raw_tushare_dc_index_update_job = dg.define_asset_job(
    name="raw_tushare_dc_index_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_dc_index)
        | dg.AssetSelection.checks_for_assets(raw_tushare_dc_index)
    ),
    partitions_def=cn_a_dc_index_trade_days,
    description="按交易日同步 dc_index Raw，并执行其单分区核心 check。",
)

raw_tushare_dc_member_update_job = dg.define_asset_job(
    name="raw_tushare_dc_member_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_dc_member)
        | dg.AssetSelection.checks_for_assets(raw_tushare_dc_member)
    ),
    partitions_def=cn_a_dc_member_trade_days,
    description="按交易日同步 dc_member Raw，并执行其单分区核心 check。",
)

raw_tushare_dc_daily_update_job = dg.define_asset_job(
    name="raw_tushare_dc_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_dc_daily)
        | dg.AssetSelection.checks_for_assets(raw_tushare_dc_daily)
    ),
    partitions_def=cn_a_dc_daily_trade_days,
    description="按交易日同步 dc_daily Raw，并执行其单分区核心 check。",
)


__all__ = [
    "raw_tushare_dc_daily_update_job",
    "raw_tushare_dc_index_update_job",
    "raw_tushare_dc_member_update_job",
]
