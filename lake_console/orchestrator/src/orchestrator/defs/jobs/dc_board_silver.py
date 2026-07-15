"""Single-partition jobs for the board Silver assets."""

import dagster as dg

from orchestrator.defs.assets.dc_board_silver import (
    silver_dc_daily,
    silver_dc_index,
    silver_dc_member,
)


silver_dc_index_update_job = dg.define_asset_job(
    name="silver_dc_index_update_job",
    selection=(
        dg.AssetSelection.assets(silver_dc_index)
        | dg.AssetSelection.checks_for_assets(silver_dc_index)
    ),
    description="按交易日生成 dc_index Silver，并执行其单分区核心 check。",
)

silver_dc_member_update_job = dg.define_asset_job(
    name="silver_dc_member_update_job",
    selection=(
        dg.AssetSelection.assets(silver_dc_member)
        | dg.AssetSelection.checks_for_assets(silver_dc_member)
    ),
    description="按交易日生成 dc_member Silver，并执行其单分区核心 check。",
)

silver_dc_daily_update_job = dg.define_asset_job(
    name="silver_dc_daily_update_job",
    selection=(
        dg.AssetSelection.assets(silver_dc_daily)
        | dg.AssetSelection.checks_for_assets(silver_dc_daily)
    ),
    description="按交易日生成 dc_daily Silver，并执行其单分区核心 check。",
)


__all__ = [
    "silver_dc_daily_update_job",
    "silver_dc_index_update_job",
    "silver_dc_member_update_job",
]
