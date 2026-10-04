"""Announcement update selects only its Raw asset and blocking checks."""

import dagster as dg

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, ANNOUNCEMENT_JOB

raw_anns_d_update_job = dg.define_asset_job(
    ANNOUNCEMENT_JOB,
    selection=dg.AssetSelection.assets(ANNOUNCEMENT_ASSET)
    | dg.AssetSelection.checks_for_assets(ANNOUNCEMENT_ASSET),
    description="按公告自然日更新六字段Raw并核对文件与本次交付。",
)
