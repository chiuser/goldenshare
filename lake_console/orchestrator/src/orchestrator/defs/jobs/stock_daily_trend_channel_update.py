"""Daily update job for paired stock trend-channel assets."""

import dagster as dg

from orchestrator.defs.assets.stock_daily_trend_channel import (
    RESULT_ASSET_KEY,
    STATE_ASSET_KEY,
)

_TREND_CHANNEL_ASSETS = (
    dg.AssetKey(RESULT_ASSET_KEY),
    dg.AssetKey(STATE_ASSET_KEY),
)


gold_stock_daily_trend_channel_update_job = dg.define_asset_job(
    name="gold_stock_daily_trend_channel_update_job",
    selection=(
        dg.AssetSelection.assets(*_TREND_CHANNEL_ASSETS)
        | dg.AssetSelection.checks_for_assets(*_TREND_CHANNEL_ASSETS)
    ),
    description=(
        "按单个交易日同时生成股票前复权趋势通道 result/state，并执行三个 "
        "blocking checks。"
    ),
)
