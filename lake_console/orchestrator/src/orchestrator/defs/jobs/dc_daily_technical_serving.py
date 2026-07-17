"""Dagster job definitions for local board technical serving."""

import dagster as dg

from orchestrator.defs.assets.dc_daily_technical_serving import (
    ch_dc_daily_technical,
    prod_ch_dc_daily_technical,
)
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days


ch_dc_daily_technical_update_job = dg.define_asset_job(
    name="ch_dc_daily_technical_update_job",
    selection=(
        dg.AssetSelection.assets(ch_dc_daily_technical)
        | dg.AssetSelection.checks_for_assets(ch_dc_daily_technical)
    ),
    partitions_def=cn_a_dc_daily_trade_days,
    description="按交易日把 gold_dc_daily_technical 写入本机 ClickHouse serving。",
)


prod_ch_dc_daily_technical_sync_job = dg.define_asset_job(
    name="prod_ch_dc_daily_technical_sync_job",
    selection=(
        dg.AssetSelection.assets(prod_ch_dc_daily_technical)
        | dg.AssetSelection.checks_for_assets(prod_ch_dc_daily_technical)
    ),
    partitions_def=cn_a_dc_daily_trade_days,
    description="将本机 ClickHouse 板块技术指标 serving 按交易日同步到 Prod ClickHouse。",
)


__all__ = [
    "ch_dc_daily_technical_update_job",
    "prod_ch_dc_daily_technical_sync_job",
]
