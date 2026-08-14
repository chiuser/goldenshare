"""Partition jobs for major-index daily and minute nine-turn assets."""

import dagster as dg

from orchestrator.defs.assets.major_index_nineturn import (
    GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
    gold_major_index_daily_nineturn,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_DAILY_JOB_NAME,
    MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME,
)

gold_major_index_daily_nineturn_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_NINETURN_DAILY_JOB_NAME,
    selection=(
        dg.AssetSelection.assets(gold_major_index_daily_nineturn)
        | dg.AssetSelection.checks_for_assets(gold_major_index_daily_nineturn)
    ),
    description="生成单个交易日的主要指数日线九转并运行一个聚合 blocking check。",
)

_minute_selection = dg.AssetSelection.assets(*GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS)
gold_major_index_mins_nineturn_update_job = dg.define_asset_job(
    name=MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME,
    selection=(
        _minute_selection
        | dg.AssetSelection.checks_for_assets(*GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS)
    ),
    description="生成单个交易日的主要指数六频分钟九转并运行六个聚合 blocking check。",
)


__all__ = [
    "gold_major_index_daily_nineturn_update_job",
    "gold_major_index_mins_nineturn_update_job",
]
