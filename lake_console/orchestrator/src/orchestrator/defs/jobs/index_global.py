"""Single-partition Dagster jobs for the international index assets."""

import dagster as dg

from orchestrator.defs.assets.index_global_raw import raw_index_global
from orchestrator.defs.assets.index_global_silver import silver_index_global
from orchestrator.defs.checks.index_global_checks import (
    raw_index_global_core_check,
    silver_index_global_core_check,
)
from orchestrator.defs.partitions import cn_global_index_trade_days


raw_index_global_update_job = dg.define_asset_job(
    name="raw_index_global_update_job",
    selection=(
        dg.AssetSelection.assets(raw_index_global)
        | dg.AssetSelection.checks_for_assets(raw_index_global)
    ),
    partitions_def=cn_global_index_trade_days,
    description="按自然日和 phase 更新国际指数 Raw，并执行单分区核心 check。",
)


silver_index_global_update_job = dg.define_asset_job(
    name="silver_index_global_update_job",
    selection=(
        dg.AssetSelection.assets(silver_index_global)
        | dg.AssetSelection.checks_for_assets(silver_index_global)
    ),
    partitions_def=cn_global_index_trade_days,
    description="基于同日国际指数 Raw 生成 Silver，并执行单分区核心 check。",
)


__all__ = ["raw_index_global_update_job", "silver_index_global_update_job"]
