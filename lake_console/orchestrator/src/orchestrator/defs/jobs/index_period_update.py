"""主要指数周期 Raw 更新入口，只选择本资产及随写入执行的 check。"""

import dagster as dg

from orchestrator.defs.assets.index_period import (
    raw_index_monthly,
    raw_index_weekly,
    silver_index_monthly,
    silver_index_weekly,
)

raw_index_weekly_update_job = dg.define_asset_job(
    name="raw_index_weekly_update_job",
    selection=dg.AssetSelection.assets(raw_index_weekly)
    | dg.AssetSelection.checks_for_assets(raw_index_weekly),
    description="更新所选周的主要指数原始行情。",
)
raw_index_monthly_update_job = dg.define_asset_job(
    name="raw_index_monthly_update_job",
    selection=dg.AssetSelection.assets(raw_index_monthly)
    | dg.AssetSelection.checks_for_assets(raw_index_monthly),
    description="更新所选月份的主要指数原始行情。",
)

silver_index_weekly_update_job = dg.define_asset_job(
    name="silver_index_weekly_update_job",
    selection=dg.AssetSelection.assets(silver_index_weekly)
    | dg.AssetSelection.checks_for_assets(silver_index_weekly),
    description="更新所选周的主要指数行情，支持当期日更和期末覆盖。",
)
silver_index_monthly_update_job = dg.define_asset_job(
    name="silver_index_monthly_update_job",
    selection=dg.AssetSelection.assets(silver_index_monthly)
    | dg.AssetSelection.checks_for_assets(silver_index_monthly),
    description="更新所选月份的主要指数行情，支持当期日更和期末覆盖。",
)
