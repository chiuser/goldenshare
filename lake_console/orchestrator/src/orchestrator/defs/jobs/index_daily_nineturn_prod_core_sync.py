"""Independent serving publication job for index daily nine-turn."""

import dagster as dg

from orchestrator.defs.assets.index_daily_nineturn_prod_core import (
    prod_core_index_daily_nineturn,
)

prod_core_index_daily_nineturn_sync_job = dg.define_asset_job(
    name="prod_core_index_daily_nineturn_sync_job",
    selection=(
        dg.AssetSelection.assets(prod_core_index_daily_nineturn)
        | dg.AssetSelection.checks_for_assets(prod_core_index_daily_nineturn)
    ),
    description="主要指数日线九转 Gold 和 blocking check 就绪后发布同分区 serving。",
)
