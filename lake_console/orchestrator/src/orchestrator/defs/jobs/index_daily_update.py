import dagster as dg

from orchestrator.defs.assets.index_daily import (
    raw_index_daily,
)


raw_index_daily_update_job = dg.define_asset_job(
    name="raw_index_daily_update_job",
    selection=(
        dg.AssetSelection.assets(raw_index_daily)
        | dg.AssetSelection.checks_for_assets(raw_index_daily)
    ),
    description="按交易日从 prod core DB 只读同步指数日线 raw by-date 分区。",
)
