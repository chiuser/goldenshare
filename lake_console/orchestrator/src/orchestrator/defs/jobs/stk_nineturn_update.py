"""Asset jobs for the daily stock nine-turn dataset."""

import dagster as dg

from orchestrator.defs.assets.stk_nineturn import raw_tushare_stk_nineturn


raw_stk_nineturn_update_job = dg.define_asset_job(
    name="raw_stk_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stk_nineturn)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stk_nineturn)
    ),
    description="从 Tushare 更新单个交易日的神奇九转 raw 分区并运行两个 blocking checks。",
)
