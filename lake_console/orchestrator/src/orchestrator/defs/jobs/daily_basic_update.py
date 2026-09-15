"""One-date raw-only daily-basic job."""

import dagster as dg

from orchestrator.defs.assets.daily_basic import raw_tushare_daily_basic
from orchestrator.defs.daily_basic_contract import DAILY_BASIC_JOB

raw_tushare_daily_basic_update_job = dg.define_asset_job(
    name=DAILY_BASIC_JOB,
    selection=dg.AssetSelection.assets(raw_tushare_daily_basic)
    | dg.AssetSelection.checks_for_assets(raw_tushare_daily_basic),
    description="更新单日股票每日指标并执行两项检查，不重跑上游股票日线。",
)
