"""Jobs for ETF Basic immutable lake snapshots."""

import dagster as dg

from orchestrator.defs.assets.etf_basic import raw_tushare_etf_basic

raw_etf_basic_update_job = dg.define_asset_job(
    name="raw_etf_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_etf_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_etf_basic)
    ),
    description=(
        "获取并验收当天 ETF Basic 完整源快照；相同内容复用，不同内容新建版本，"
        "失败不会覆盖旧版本，可在修复源/合同后重跑。"
    ),
)
