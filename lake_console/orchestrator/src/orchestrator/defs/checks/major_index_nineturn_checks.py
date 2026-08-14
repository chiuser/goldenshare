"""Seven aggregate blocking checks for major-index nine-turn assets."""

import dagster as dg

from orchestrator.defs.assets.major_index_nineturn import (
    GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
    gold_major_index_daily_nineturn,
)
from orchestrator.defs.major_index_nineturn_integrity import (
    MAJOR_INDEX_NINETURN_INTEGRITY_RULE_NAMES,
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import (
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
    gold_major_index_mins_path,
    gold_market_major_indices_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
    MAJOR_INDEX_NINETURN_VERSION,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _result(diagnostics, *, target_path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=diagnostics.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=diagnostics.checked_row_count,
            failed_row_count=diagnostics.failed_row_count,
            file_path=target_path,
            extra_metadata={
                "summary": (
                    "主要指数九转分区完整性检查通过。"
                    if diagnostics.passed
                    else "主要指数九转分区完整性检查失败。"
                ),
                "next_action": (
                    "无需处理。"
                    if diagnostics.passed
                    else "修复同频 Gold K 线或目标九转分区后重新运行。"
                ),
                "rules": list(MAJOR_INDEX_NINETURN_INTEGRITY_RULE_NAMES),
                "formula_version": MAJOR_INDEX_NINETURN_VERSION,
                "source_row_count": diagnostics.source_row_count,
                "duplicate_key_count": diagnostics.duplicate_key_count,
                "null_key_count": diagnostics.null_key_count,
                "invalid_value_count": diagnostics.invalid_value_count,
                "missing_source_key_count": diagnostics.missing_source_key_count,
                "extra_output_key_count": diagnostics.extra_output_key_count,
                "source_value_mismatch_count": diagnostics.source_value_mismatch_count,
                "failed_rule_names": list(diagnostics.failed_rule_names),
            },
        ),
    )


@dg.asset_check(
    asset=gold_major_index_daily_nineturn,
    name="gold_major_index_daily_nineturn_integrity_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def gold_major_index_daily_nineturn_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    target = gold_major_index_daily_nineturn_path(
        lake_root.root(), context.partition_key
    )
    with duckdb.connect() as connection:
        diagnostics = audit_major_index_nineturn_integrity(
            connection,
            target_path=target,
            source_paths=(
                gold_market_major_indices_daily_path(
                    lake_root.root(), context.partition_key
                ),
            ),
            partition_key=context.partition_key,
            freq=None,
        )
    return _result(diagnostics, target_path=target)


def _build_minute_check(*, asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=f"gold_major_index_mins_nineturn_{freq}m_integrity_check",
        partitions_def=cn_major_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        target = gold_major_index_mins_nineturn_path(
            lake_root.root(), freq, context.partition_key
        )
        with duckdb.connect() as connection:
            diagnostics = audit_major_index_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(
                    gold_major_index_mins_path(
                        lake_root.root(), freq, context.partition_key
                    ),
                ),
                partition_key=context.partition_key,
                freq=freq,
            )
        return _result(diagnostics, target_path=target)

    return check


GOLD_MAJOR_INDEX_MINS_NINETURN_CHECKS = tuple(
    _build_minute_check(asset=asset, freq=freq)
    for asset, freq in zip(
        GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
        MAJOR_INDEX_NINETURN_MINUTE_FREQS,
        strict=True,
    )
)

(
    gold_major_index_mins_nineturn_5m_integrity_check,
    gold_major_index_mins_nineturn_15m_integrity_check,
    gold_major_index_mins_nineturn_30m_integrity_check,
    gold_major_index_mins_nineturn_60m_integrity_check,
    gold_major_index_mins_nineturn_90m_integrity_check,
    gold_major_index_mins_nineturn_120m_integrity_check,
) = GOLD_MAJOR_INDEX_MINS_NINETURN_CHECKS

GOLD_MAJOR_INDEX_NINETURN_CHECKS = (
    gold_major_index_daily_nineturn_integrity_check,
    *GOLD_MAJOR_INDEX_MINS_NINETURN_CHECKS,
)


__all__ = [
    "GOLD_MAJOR_INDEX_NINETURN_CHECKS",
    "gold_major_index_daily_nineturn_integrity_check",
    "gold_major_index_mins_nineturn_5m_integrity_check",
    "gold_major_index_mins_nineturn_15m_integrity_check",
    "gold_major_index_mins_nineturn_30m_integrity_check",
    "gold_major_index_mins_nineturn_60m_integrity_check",
    "gold_major_index_mins_nineturn_90m_integrity_check",
    "gold_major_index_mins_nineturn_120m_integrity_check",
]
