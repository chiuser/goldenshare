"""Gold readiness wrapper for ordinary index minutes."""

from orchestrator.defs.asset_guards.cn_a_gold_minute_lake_readiness import (
    batch_canonical_gold_minute_lake_readiness,
)
from orchestrator.defs.paths import gold_index_mins_path, silver_index_mins_path
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_GOLD_CHECKS


def _source_path(root, target_freq: int, trade_date: str):
    source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]
    return silver_index_mins_path(root, f"{source_freq}min", trade_date)


def batch_gold_index_mins_lake_readiness(**kwargs):
    return batch_canonical_gold_minute_lake_readiness(
        **kwargs,
        target_path_builder=gold_index_mins_path,
        source_path_builder=_source_path,
        check_names=INDEX_MINS_GOLD_CHECKS,
        asset_family="index_mins",
    )


__all__ = ["batch_gold_index_mins_lake_readiness"]
