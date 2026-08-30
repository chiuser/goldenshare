"""Jobs for ETF Basic immutable lake snapshots."""

import dagster as dg

from orchestrator.defs.assets.etf_basic import (
    raw_tushare_etf_basic,
    silver_etf_basic,
)

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

silver_etf_basic_update_job = dg.define_asset_job(
    name="silver_etf_basic_update_job",
    selection=(
        dg.AssetSelection.assets(silver_etf_basic)
        | dg.AssetSelection.checks_for_assets(silver_etf_basic)
    ),
    description=(
        "从已验收的指定 Basic Raw 版本生成沪深场内 Silver 快照；"
        "前置 Raw/reference 不一致时停止，修复后可重跑并等价复用。"
    ),
)
