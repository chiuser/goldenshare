"""Blocking checks for stock daily trend-channel result and state assets."""

from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.partitions import cn_a_stock_daily_trend_channel_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    StockDailyTrendChannelAudit,
    StockDailyTrendChannelCoverageAudit,
    audit_stock_daily_trend_channel_result,
    audit_stock_daily_trend_channel_state,
    audit_stock_daily_trend_channel_state_coverage,
)


@dg.asset_check(
    asset="gold_stock_daily_trend_channel",
    name="gold_stock_daily_trend_channel_contract_check",
    blocking=True,
    partitions_def=cn_a_stock_daily_trend_channel_trade_days,
    additional_deps=[
        dg.AssetDep(
            gold_stock_daily_qfq,
            partition_mapping=dg.IdentityPartitionMapping(),
        )
    ],
)
def gold_stock_daily_trend_channel_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    result_path = gold_stock_daily_trend_channel_path(root, partition_key)
    qfq_path = gold_stock_daily_qfq_path(root, partition_key)
    with duckdb.connect() as connection:
        audit = audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=result_path,
            qfq_source_path=qfq_path,
            trade_date=partition_key,
        )
    return _ordinary_audit_result(
        audit=audit,
        file_path=result_path,
        input_file_paths=(qfq_path,),
        success_summary="股票日线趋势通道 result contract check 通过。",
        failure_summary="股票日线趋势通道 result contract check 失败。",
        success_next_action="无需处理，等待下游消费。",
        failure_next_action="检查 result schema、值域和 qfq code/date 对账后重建该分区。",
    )


@dg.asset_check(
    asset="gold_stock_daily_trend_channel_state",
    name="gold_stock_daily_trend_channel_state_contract_check",
    blocking=True,
    partitions_def=cn_a_stock_daily_trend_channel_trade_days,
    additional_deps=["silver_stock_lifecycle"],
)
def gold_stock_daily_trend_channel_state_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    state_path = gold_stock_daily_trend_channel_state_path(root, partition_key)
    lifecycle_path = silver_stock_lifecycle_path(root)
    with duckdb.connect() as connection:
        audit = audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=state_path,
            stock_lifecycle_path=lifecycle_path,
            trade_date=partition_key,
        )
    return _ordinary_audit_result(
        audit=audit,
        file_path=state_path,
        input_file_paths=(lifecycle_path,),
        success_summary="股票日线趋势通道 state contract check 通过。",
        failure_summary="股票日线趋势通道 state contract check 失败。",
        success_next_action="无需处理，下一 expected 交易日可以承接该状态。",
        failure_next_action="检查 state schema、递推值、版本和生命周期边界后重建。",
    )


@dg.asset_check(
    asset="gold_stock_daily_trend_channel",
    name="gold_stock_daily_trend_channel_input_coverage_check",
    blocking=True,
    partitions_def=cn_a_stock_daily_trend_channel_trade_days,
    additional_deps=[
        dg.AssetDep(
            gold_stock_daily_qfq,
            partition_mapping=dg.IdentityPartitionMapping(),
        ),
        "gold_stock_daily_trend_channel_state",
        "silver_stock_lifecycle",
        "silver_trade_calendar",
    ],
)
def gold_stock_daily_trend_channel_input_coverage_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    state_path = gold_stock_daily_trend_channel_state_path(root, partition_key)
    qfq_path = gold_stock_daily_qfq_path(root, partition_key)
    lifecycle_path = silver_stock_lifecycle_path(root)
    calendar_path = silver_trade_calendar_path(root)
    if not calendar_path.exists():
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=0,
                failed_row_count=1,
                file_path=state_path,
                missing_file_paths=(calendar_path,),
                extra_metadata={
                    "summary": "股票日线趋势通道 coverage check 失败：交易日历缺失。",
                    "next_action": "先恢复 silver_trade_calendar，再重跑检查。",
                    "failure_rule_counts": {"required_file_exists": 1},
                    "failure_samples": {
                        "required_file_exists": [{"path": str(calendar_path)}]
                    },
                    "source_row_count": 0,
                    "output_row_count": 0,
                    "formula_version": FORMULA_VERSION,
                },
            ),
        )
    with duckdb.connect() as connection:
        previous_trade_date = _load_previous_expected_trade_date(
            connection=connection,
            calendar_path=calendar_path,
            trade_date=partition_key,
        )
        previous_state_path = (
            gold_stock_daily_trend_channel_state_path(root, previous_trade_date)
            if previous_trade_date is not None
            else None
        )
        audit = audit_stock_daily_trend_channel_state_coverage(
            connection=connection,
            state_path=state_path,
            qfq_source_path=qfq_path,
            stock_lifecycle_path=lifecycle_path,
            previous_state_path=previous_state_path,
            trade_date=partition_key,
        )
    return _coverage_audit_result(
        audit=audit,
        state_path=state_path,
        qfq_path=qfq_path,
        lifecycle_path=lifecycle_path,
        previous_state_path=previous_state_path,
    )


def _ordinary_audit_result(
    *,
    audit: StockDailyTrendChannelAudit,
    file_path: Path,
    input_file_paths: tuple[Path, ...],
    success_summary: str,
    failure_summary: str,
    success_next_action: str,
    failure_next_action: str,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=audit.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=audit.checked_row_count,
            failed_row_count=audit.failed_row_count,
            file_path=file_path,
            input_file_paths=input_file_paths,
            extra_metadata={
                "summary": success_summary if audit.passed else failure_summary,
                "next_action": (
                    success_next_action if audit.passed else failure_next_action
                ),
                "failure_rule_counts": dict(audit.failure_rule_counts),
                "failure_samples": _metadata_failure_samples(
                    audit.failure_samples
                ),
                "source_row_count": audit.source_row_count,
                "output_row_count": audit.output_row_count,
                "formula_version": FORMULA_VERSION,
                "observed_columns": list(audit.observed_columns),
            },
        ),
    )


def _coverage_audit_result(
    *,
    audit: StockDailyTrendChannelCoverageAudit,
    state_path: Path,
    qfq_path: Path,
    lifecycle_path: Path,
    previous_state_path: Path | None,
) -> dg.AssetCheckResult:
    input_paths = (
        (qfq_path, lifecycle_path, previous_state_path)
        if previous_state_path is not None
        else (qfq_path, lifecycle_path)
    )
    return dg.AssetCheckResult(
        passed=audit.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=audit.checked_row_count,
            failed_row_count=audit.failed_row_count,
            file_path=state_path,
            input_file_paths=input_paths,
            extra_metadata={
                "summary": (
                    "股票日线趋势通道 input coverage check 通过。"
                    if audit.passed
                    else "股票日线趋势通道 input coverage check 失败。"
                ),
                "next_action": (
                    "无需处理，observed、carry 和 uninitialized 对账一致。"
                    if audit.passed
                    else "检查 qfq、previous state 与 lifecycle 集合后重建该分区。"
                ),
                "failure_rule_counts": dict(audit.failure_rule_counts),
                "failure_samples": _metadata_failure_samples(
                    audit.failure_samples
                ),
                "source_row_count": audit.qfq_observed_count,
                "output_row_count": audit.checked_row_count,
                "formula_version": FORMULA_VERSION,
                "expected_lifecycle_count": audit.expected_lifecycle_count,
                "qfq_observed_count": audit.qfq_observed_count,
                "previous_initialized_count": audit.previous_initialized_count,
                "expected_carry_count": audit.expected_carry_count,
                "actual_observed_state_count": (
                    audit.actual_observed_state_count
                ),
                "actual_carry_state_count": audit.actual_carry_state_count,
                "uninitialized_count": audit.uninitialized_count,
                "missing_state_count": audit.missing_state_count,
                "unexpected_state_count": audit.unexpected_state_count,
            },
        ),
    )


def _metadata_failure_samples(
    samples: Any,
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(rule_name): [dict(sample) for sample in rule_samples]
        for rule_name, rule_samples in samples.items()
    }


def _load_previous_expected_trade_date(
    *,
    connection: Any,
    calendar_path: Path,
    trade_date: str,
) -> str | None:
    date_sql = duckdb_string(trade_date)
    row = connection.execute(
        f"""
        WITH target AS (
          SELECT count(*) AS target_count
          FROM {read_parquet(calendar_path, hive_partitioning=False)}
          WHERE CAST(exchange AS VARCHAR) = 'SSE'
            AND CAST(is_open AS BOOLEAN)
            AND CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        previous AS (
          SELECT strftime(max(CAST(trade_date AS DATE)), '%Y-%m-%d') AS trade_date
          FROM {read_parquet(calendar_path, hive_partitioning=False)}
          WHERE CAST(exchange AS VARCHAR) = 'SSE'
            AND CAST(is_open AS BOOLEAN)
            AND CAST(trade_date AS DATE) < DATE {date_sql}
        )
        SELECT target.target_count, previous.trade_date
        FROM target CROSS JOIN previous
        """
    ).fetchone()
    if int(row[0]) != 1:
        raise ValueError(
            "Stock daily trend-channel check partition must be one SSE open date: "
            f"{trade_date}."
        )
    return str(row[1]) if row[1] is not None else None
