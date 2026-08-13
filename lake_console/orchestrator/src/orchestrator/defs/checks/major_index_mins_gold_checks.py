"""Partitioned blocking checks for major-index Gold minute bars."""

import dagster as dg

from orchestrator.defs.assets.major_index_mins_gold import GOLD_MAJOR_INDEX_MINS_ASSETS
from orchestrator.defs.checks.cn_a_gold_minute_checks import (
    canonical_gold_minute_check_failure,
    evaluate_canonical_gold_minute_core_check,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_CHECKS,
    effective_silver_codes_for_date,
)


def _build_check(*, asset, check_name: str, target_freq: int):
    @dg.asset_check(
        asset=asset,
        name=check_name,
        partitions_def=cn_major_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        partition_keys = tuple(sorted(set(context.partition_keys)))
        if len(partition_keys) != 1:
            return canonical_gold_minute_check_failure(
                reason_code="multiple_partition_execution",
                failed_rule_names=("single_partition_execution",),
            )
        partition_key = partition_keys[0]
        source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]
        duckdb_resource = duckdb
        with duckdb_resource.connect() as connection:
            return evaluate_canonical_gold_minute_core_check(
                connection=connection,
                target_path=gold_major_index_mins_path(
                    lake_root.root(), target_freq, partition_key
                ),
                source_path=silver_major_index_mins_path(
                    lake_root.root(), f"{source_freq}min", partition_key
                ),
                target_freq=target_freq,
                partition_key=partition_key,
                expected_codes=effective_silver_codes_for_date(partition_key),
            )

    return check


GOLD_MAJOR_INDEX_MINS_CHECK_DEFS = tuple(
    _build_check(asset=asset, check_name=check_name, target_freq=target_freq)
    for asset, check_name, target_freq in zip(
        GOLD_MAJOR_INDEX_MINS_ASSETS,
        MAJOR_INDEX_MINS_GOLD_CHECKS,
        CN_A_GOLD_MINUTE_FREQS,
        strict=True,
    )
)

(
    gold_major_index_mins_1m_core_check,
    gold_major_index_mins_5m_core_check,
    gold_major_index_mins_15m_core_check,
    gold_major_index_mins_30m_core_check,
    gold_major_index_mins_60m_core_check,
    gold_major_index_mins_90m_core_check,
    gold_major_index_mins_120m_core_check,
) = GOLD_MAJOR_INDEX_MINS_CHECK_DEFS

__all__ = ["GOLD_MAJOR_INDEX_MINS_CHECK_DEFS"]
