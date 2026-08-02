"""Manual full-snapshot job for the Eastmoney industry hierarchy."""

import dagster as dg

from orchestrator.defs.assets.dc_industry_hierarchy import silver_dc_industry_hierarchy


silver_dc_industry_hierarchy_update_job = dg.define_asset_job(
    name="silver_dc_industry_hierarchy_update_job",
    selection=(
        dg.AssetSelection.assets(silver_dc_industry_hierarchy)
        | dg.AssetSelection.checks_for_assets(silver_dc_industry_hierarchy)
    ),
    description="按人工指定的 dc_index 参考交易日重建东方财富行业层级全量快照，并执行唯一核心 check。",
)


__all__ = ["silver_dc_industry_hierarchy_update_job"]
