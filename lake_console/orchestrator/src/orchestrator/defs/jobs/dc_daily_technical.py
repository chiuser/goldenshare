"""Dagster job for the normal Gold board technical-indicator update."""

import dagster as dg

from orchestrator.defs.assets.dc_daily_technical_asset import gold_dc_daily_technical


gold_dc_daily_technical_update_job = dg.define_asset_job(
    name="gold_dc_daily_technical_update_job",
    selection=(
        dg.AssetSelection.assets(gold_dc_daily_technical)
        | dg.AssetSelection.checks_for_assets(gold_dc_daily_technical)
    ),
    description="按交易日生成 dc_daily 技术指标 Gold，并执行唯一核心 check。",
)


__all__ = ["gold_dc_daily_technical_update_job"]
