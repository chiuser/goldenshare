"""Blocking checks for stock nine-turn raw and silver assets."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.assets.stk_nineturn import raw_tushare_stk_nineturn
from orchestrator.defs.duckdb_sql import count_parquet_query
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import raw_stk_nineturn_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_EXPECTED_SCHEMA,
    build_stk_nineturn_path_plan,
    describe_stk_nineturn_parquet_schema,
    load_raw_stk_nineturn_failure_samples,
    load_raw_stk_nineturn_metrics,
    raw_stk_nineturn_failed_row_count,
    raw_stk_nineturn_failed_rule_names,
)


STK_NINETURN_HISTORY_START_DATE = "2023-01-03"
STK_NINETURN_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _schema_metadata(
    schema: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [{"name": name, "type": column_type} for name, column_type in schema]


def _missing_file_result(
    *,
    path: Path,
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "summary": "神奇九转 raw 分区文件不存在。",
                "next_action": "先运行 raw_stk_nineturn_update_job 生成该交易日分区。",
                "failed_rule_names": ["file_exists"],
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_stk_nineturn,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def raw_tushare_stk_nineturn_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    raw_path = raw_stk_nineturn_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        return _missing_file_result(path=raw_path, check_scope=CheckScope.SCHEMA)

    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        observed_schema = describe_stk_nineturn_parquet_schema(connection, raw_path)
        row_count = int(
            connection.execute(count_parquet_query(raw_path)).fetchone()[0]
        )
    registered_trade_days = set(
        context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    )
    is_registered = partition_key in registered_trade_days
    is_not_before_start = partition_key >= STK_NINETURN_HISTORY_START_DATE
    is_not_future = (
        partition_key <= datetime.now(STK_NINETURN_TIMEZONE).date().isoformat()
    )
    schema_matches = observed_schema == RAW_STK_NINETURN_EXPECTED_SCHEMA

    failed_rule_names = []
    if row_count <= 0:
        failed_rule_names.append("row_count_positive")
    if not schema_matches:
        failed_rule_names.append("schema_matches_contract")
    if not is_registered:
        failed_rule_names.append("partition_is_registered")
    if not is_not_before_start:
        failed_rule_names.append("partition_not_before_history_start")
    if not is_not_future:
        failed_rule_names.append("partition_not_future")

    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            failed_row_count=len(failed_rule_names),
            file_path=raw_path,
            extra_metadata={
                "summary": (
                    "神奇九转 raw 文件、schema、分区日期边界和注册状态已检查。"
                ),
                "next_action": (
                    "通过后继续检查业务键、行情、计数和九转信号内容。"
                    if not failed_rule_names
                    else "按 failed_rule_names 修复 raw 分区后重新运行。"
                ),
                "partition_key": partition_key,
                "partition_set_name": cn_a_stock_trade_days.name,
                "is_registered": is_registered,
                "is_not_before_start": is_not_before_start,
                "is_not_future": is_not_future,
                "observed_schema": _schema_metadata(observed_schema),
                "expected_schema": _schema_metadata(
                    RAW_STK_NINETURN_EXPECTED_SCHEMA
                ),
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_stk_nineturn,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def raw_tushare_stk_nineturn_content_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    raw_path = raw_stk_nineturn_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        return _missing_file_result(
            path=raw_path,
            check_scope=CheckScope.VALUE_SANITY,
        )

    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        observed_schema = describe_stk_nineturn_parquet_schema(connection, raw_path)
        if observed_schema != RAW_STK_NINETURN_EXPECTED_SCHEMA:
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.VALUE_SANITY,
                    file_path=raw_path,
                    extra_metadata={
                        "summary": "神奇九转 raw schema 不匹配，内容语义未执行。",
                        "next_action": "先修复 raw contract check 再检查内容。",
                        "observed_schema": _schema_metadata(observed_schema),
                        "expected_schema": _schema_metadata(
                            RAW_STK_NINETURN_EXPECTED_SCHEMA
                        ),
                        "failed_rule_names": ["schema_matches_contract"],
                    },
                ),
            )

        metrics = load_raw_stk_nineturn_metrics(
            connection,
            path_plans=[
                build_stk_nineturn_path_plan(
                    trade_date=partition_key,
                    path=raw_path,
                )
            ],
        ).get(partition_key)
        if metrics is None:
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.VALUE_SANITY,
                    checked_row_count=0,
                    failed_row_count=1,
                    file_path=raw_path,
                    extra_metadata={
                        "summary": "神奇九转 raw 文件存在但没有可检查行。",
                        "next_action": "审计空分区来源，不要自动覆盖。",
                        "failed_rule_names": ["row_count_positive"],
                    },
                ),
            )
        failed_rule_names = raw_stk_nineturn_failed_rule_names(metrics)
        failure_samples = (
            load_raw_stk_nineturn_failure_samples(
                connection,
                path=raw_path,
                expected_trade_date=partition_key,
            )
            if failed_rule_names
            else ()
        )

    metric_summary = {
        "null_key_count": metrics.null_key_count,
        "duplicate_key_count": metrics.duplicate_key_count,
        "partition_date_mismatch_count": metrics.partition_date_mismatch_count,
        "non_daily_freq_count": metrics.non_daily_freq_count,
        "invalid_price_count": metrics.invalid_price_count,
        "negative_volume_amount_count": metrics.negative_volume_amount_count,
        "invalid_count_count": metrics.invalid_count_count,
        "simultaneous_direction_count": metrics.simultaneous_direction_count,
        "invalid_marker_count": metrics.invalid_marker_count,
        "marker_count_mismatch_count": metrics.marker_count_mismatch_count,
        "simultaneous_marker_count": metrics.simultaneous_marker_count,
    }
    return dg.AssetCheckResult(
        passed=metrics.row_count > 0 and not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            checked_row_count=metrics.row_count,
            failed_row_count=raw_stk_nineturn_failed_row_count(metrics),
            file_path=raw_path,
            extra_metadata={
                "summary": "神奇九转 raw 业务键、行情、计数和信号内容已检查。",
                "next_action": (
                    "内容完整性通过，可供 Silver 消费。"
                    if not failed_rule_names
                    else "按 failed_rule_names 和 failure_samples 修复 raw 分区。"
                ),
                "partition_key": partition_key,
                "failed_rule_names": list(failed_rule_names),
                "rule_summary": metric_summary,
                "failure_samples": list(failure_samples),
            },
        ),
    )
