"""Aggregate blocking checks for QFQ nine-turn Gold assets."""

import dagster as dg

from orchestrator.defs.assets.qfq_nineturn import (
    gold_stk_mins_qfq_nineturn_30m,
    gold_stk_mins_qfq_nineturn_60m,
    gold_stk_mins_qfq_nineturn_90m,
    gold_stk_mins_qfq_nineturn_120m,
    gold_stock_daily_qfq_nineturn,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn_integrity import (
    QFQ_NINETURN_INTEGRITY_RULE_NAMES,
    QfqNineturnIntegrityDiagnostics,
    audit_qfq_nineturn_integrity,
    qfq_nineturn_source_paths_for_partition,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _check_result(
    diagnostics: QfqNineturnIntegrityDiagnostics,
    *,
    target_path,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=diagnostics.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=diagnostics.checked_row_count,
            failed_row_count=diagnostics.failed_row_count,
            file_path=target_path,
            extra_metadata={
                "summary": (
                    "前复权九转分区完整性检查通过。"
                    if diagnostics.passed
                    else "前复权九转分区完整性检查失败，先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，等待下游每日扫描。"
                    if diagnostics.passed
                    else "先修复目标文件或同频度 QFQ 上游，再重新运行该九转分区。"
                ),
                "rule_summary": {
                    "rules": list(QFQ_NINETURN_INTEGRITY_RULE_NAMES),
                    "checked_row_count": diagnostics.checked_row_count,
                    "source_row_count": diagnostics.source_row_count,
                    "duplicate_key_count": diagnostics.duplicate_key_count,
                    "null_key_count": diagnostics.null_key_count,
                    "invalid_value_count": diagnostics.invalid_value_count,
                    "missing_source_key_count": diagnostics.missing_source_key_count,
                    "extra_output_key_count": diagnostics.extra_output_key_count,
                },
                "failed_rule_names": list(diagnostics.failed_rule_names),
                "failure_samples": list(diagnostics.failure_samples),
                "diagnostic_ref": "完整诊断看本 check metadata 和对应 run stdout。",
            },
        ),
    )


@dg.asset_check(
    asset=gold_stock_daily_qfq_nineturn,
    name="gold_stock_daily_qfq_nineturn_integrity_check",
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def gold_stock_daily_qfq_nineturn_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    target_path = gold_stock_daily_qfq_nineturn_path(root, partition_key)
    source_paths = qfq_nineturn_source_paths_for_partition(
        lake_root=root,
        partition_key=partition_key,
        freq=None,
    )
    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        diagnostics = audit_qfq_nineturn_integrity(
            connection,
            target_path=target_path,
            source_paths=source_paths,
            partition_key=partition_key,
            freq=None,
        )
    return _check_result(diagnostics, target_path=target_path)


def _build_minute_check(*, asset, freq: int):
    check_name = f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check"

    @dg.asset_check(
        asset=asset,
        name=check_name,
        partitions_def=cn_a_stock_mins_silver_trade_days,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        partition_key = context.partition_key
        root = lake_root.root()
        target_path = gold_stk_mins_qfq_nineturn_path(root, freq, partition_key)
        source_paths = qfq_nineturn_source_paths_for_partition(
            lake_root=root,
            partition_key=partition_key,
            freq=freq,
        )
        connect_duckdb = duckdb.connect
        with connect_duckdb() as connection:
            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target_path,
                source_paths=source_paths,
                partition_key=partition_key,
                freq=freq,
            )
        return _check_result(diagnostics, target_path=target_path)

    return _check


gold_stk_mins_qfq_nineturn_30m_integrity_check = _build_minute_check(
    asset=gold_stk_mins_qfq_nineturn_30m,
    freq=30,
)
gold_stk_mins_qfq_nineturn_60m_integrity_check = _build_minute_check(
    asset=gold_stk_mins_qfq_nineturn_60m,
    freq=60,
)
gold_stk_mins_qfq_nineturn_90m_integrity_check = _build_minute_check(
    asset=gold_stk_mins_qfq_nineturn_90m,
    freq=90,
)
gold_stk_mins_qfq_nineturn_120m_integrity_check = _build_minute_check(
    asset=gold_stk_mins_qfq_nineturn_120m,
    freq=120,
)

GOLD_QFQ_NINETURN_CHECKS = (
    gold_stock_daily_qfq_nineturn_integrity_check,
    gold_stk_mins_qfq_nineturn_30m_integrity_check,
    gold_stk_mins_qfq_nineturn_60m_integrity_check,
    gold_stk_mins_qfq_nineturn_90m_integrity_check,
    gold_stk_mins_qfq_nineturn_120m_integrity_check,
)
