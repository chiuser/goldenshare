"""Blocking checks for stock nine-turn raw and silver assets."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.assets.stock_identity_map import silver_stock_identity_map
from orchestrator.defs.assets.stk_nineturn import (
    raw_tushare_stk_nineturn,
    silver_stock_nineturn_daily,
)
from orchestrator.defs.duckdb_sql import count_parquet_query
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_EXPECTED_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA,
    build_stk_nineturn_path_plan,
    describe_stk_nineturn_parquet_schema,
    load_raw_stk_nineturn_failure_samples,
    load_raw_stk_nineturn_metrics,
    load_silver_stock_nineturn_daily_metrics,
    load_silver_stock_nineturn_mapping_failure_samples,
    raw_stk_nineturn_failed_row_count,
    raw_stk_nineturn_failed_rule_names,
    silver_stock_nineturn_daily_failed_rule_names,
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


def _missing_silver_input_result(
    *,
    target_path: Path,
    missing_paths: list[Path],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            file_path=target_path,
            missing_file_paths=missing_paths,
            extra_metadata={
                "summary": "神奇九转 Silver 目标或 canonical 输入文件不存在。",
                "next_action": (
                    "先确认 Raw 分区和 silver_stock_identity_map ready，再运行 "
                    "silver_stock_nineturn_daily_update_job。"
                ),
                "failed_rule_names": ["required_files_exist"],
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
        schema_matches = observed_schema == RAW_STK_NINETURN_EXPECTED_SCHEMA
        metrics = (
            load_raw_stk_nineturn_metrics(
                connection,
                path_plans=[
                    build_stk_nineturn_path_plan(
                        trade_date=partition_key,
                        path=raw_path,
                    )
                ],
            ).get(partition_key)
            if schema_matches
            else None
        )
    registered_trade_days = set(
        context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    )
    is_registered = partition_key in registered_trade_days
    is_not_before_start = partition_key >= STK_NINETURN_HISTORY_START_DATE
    is_not_future = (
        partition_key <= datetime.now(STK_NINETURN_TIMEZONE).date().isoformat()
    )
    failed_rule_names = []
    if row_count <= 0:
        failed_rule_names.append("row_count_positive")
    if not schema_matches:
        failed_rule_names.append("schema_matches_contract")
    if metrics is not None and metrics.partition_date_mismatch_count:
        failed_rule_names.append("partition_date_matches")
    if metrics is not None and metrics.non_daily_freq_count:
        failed_rule_names.append("freq_is_daily")
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
                "partition_date_mismatch_count": (
                    metrics.partition_date_mismatch_count
                    if metrics is not None
                    else None
                ),
                "non_daily_freq_count": (
                    metrics.non_daily_freq_count if metrics is not None else None
                ),
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


@dg.asset_check(
    asset=silver_stock_nineturn_daily,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def silver_stock_nineturn_daily_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    target_path = silver_stock_nineturn_daily_path(
        lake_root.root(),
        partition_key,
    )
    if not target_path.exists():
        return _missing_silver_input_result(
            target_path=target_path,
            missing_paths=[target_path],
            check_scope=CheckScope.SCHEMA,
        )

    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        observed_schema = describe_stk_nineturn_parquet_schema(
            connection,
            target_path,
        )
        metrics = (
            load_raw_stk_nineturn_metrics(
                connection,
                path_plans=[
                    build_stk_nineturn_path_plan(
                        trade_date=partition_key,
                        path=target_path,
                    )
                ],
            ).get(partition_key)
            if observed_schema == SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA
            else None
        )
    registered_trade_days = set(
        context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    )
    failed_rule_names = []
    if observed_schema != SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA:
        failed_rule_names.append("schema_matches_contract")
    if metrics is None or metrics.row_count <= 0:
        failed_rule_names.append("row_count_positive")
    if metrics is not None:
        if metrics.null_key_count:
            failed_rule_names.append("key_columns_non_null")
        if metrics.duplicate_key_count:
            failed_rule_names.append("canonical_key_unique")
        if metrics.partition_date_mismatch_count:
            failed_rule_names.append("partition_date_matches")
        if metrics.non_daily_freq_count:
            failed_rule_names.append("freq_is_daily")
    if partition_key not in registered_trade_days:
        failed_rule_names.append("partition_is_registered")

    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=metrics.row_count if metrics is not None else 0,
            failed_row_count=len(failed_rule_names),
            file_path=target_path,
            extra_metadata={
                "summary": "神奇九转 Silver 文件、schema、标准键和分区已检查。",
                "next_action": (
                    "contract 通过后继续执行 canonical integrity check。"
                    if not failed_rule_names
                    else "按 failed_rule_names 修复 Silver 分区后重新运行。"
                ),
                "partition_key": partition_key,
                "partition_set_name": cn_a_stock_trade_days.name,
                "observed_schema": _schema_metadata(observed_schema),
                "expected_schema": _schema_metadata(
                    SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA
                ),
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


@dg.asset_check(
    asset=silver_stock_nineturn_daily,
    additional_deps=[raw_tushare_stk_nineturn, silver_stock_identity_map],
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def silver_stock_nineturn_daily_canonical_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    raw_path = raw_stk_nineturn_path(lake_root.root(), partition_key)
    identity_map_path = silver_stock_identity_map_path(lake_root.root())
    target_path = silver_stock_nineturn_daily_path(
        lake_root.root(),
        partition_key,
    )
    missing_paths = [
        path
        for path in (raw_path, identity_map_path, target_path)
        if not path.exists()
    ]
    if missing_paths:
        return _missing_silver_input_result(
            target_path=target_path,
            missing_paths=missing_paths,
            check_scope=CheckScope.RECONCILIATION,
        )

    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        observed_schema = describe_stk_nineturn_parquet_schema(
            connection,
            target_path,
        )
        if observed_schema != SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA:
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.RECONCILIATION,
                    file_path=target_path,
                    input_file_paths=[raw_path, identity_map_path],
                    extra_metadata={
                        "summary": "神奇九转 Silver schema 不匹配，canonical 语义未执行。",
                        "next_action": "先修复 Silver contract check 再检查映射语义。",
                        "failed_rule_names": ["schema_matches_contract"],
                    },
                ),
            )
        metrics = load_silver_stock_nineturn_daily_metrics(
            connection,
            raw_path_plans=[
                build_stk_nineturn_path_plan(
                    trade_date=partition_key,
                    path=raw_path,
                )
            ],
            silver_path_plans=[
                build_stk_nineturn_path_plan(
                    trade_date=partition_key,
                    path=target_path,
                )
            ],
            identity_map_path=identity_map_path,
        ).get(partition_key)
        failed_rule_names = (
            silver_stock_nineturn_daily_failed_rule_names(metrics)
            if metrics is not None
            else ("metrics_available",)
        )
        mapping_samples = (
            load_silver_stock_nineturn_mapping_failure_samples(
                connection,
                raw_path=raw_path,
                identity_map_path=identity_map_path,
                trade_date=partition_key,
            )
            if metrics is not None
            and (
                metrics.unmapped_source_code_count
                or metrics.market_value_conflict_key_count
                or metrics.unresolved_count_signal_conflict_key_count
            )
            else ()
        )
        content_samples = (
            load_raw_stk_nineturn_failure_samples(
                connection,
                path=target_path,
                expected_trade_date=partition_key,
            )
            if metrics is not None
            and raw_stk_nineturn_failed_rule_names(metrics)
            else ()
        )

    metric_summary = (
        {
            "source_row_count": metrics.source_row_count,
            "mapped_row_count": metrics.mapped_row_count,
            "expected_output_row_count": metrics.expected_output_row_count,
            "output_row_count": metrics.row_count,
            "alias_duplicate_key_count": metrics.alias_duplicate_key_count,
            "count_signal_conflict_key_count": (
                metrics.count_signal_conflict_key_count
            ),
            "unresolved_count_signal_conflict_key_count": (
                metrics.unresolved_count_signal_conflict_key_count
            ),
            "market_value_conflict_key_count": (
                metrics.market_value_conflict_key_count
            ),
            "unmapped_source_code_count": metrics.unmapped_source_code_count,
            "canonical_selection_mismatch_count": (
                metrics.canonical_selection_mismatch_count
            ),
        }
        if metrics is not None
        else {}
    )
    return dg.AssetCheckResult(
        passed=metrics is not None and not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=metrics.row_count if metrics is not None else 0,
            failed_row_count=len(failed_rule_names),
            file_path=target_path,
            input_file_paths=[raw_path, identity_map_path],
            extra_metadata={
                "summary": (
                    "神奇九转 Silver 代码映射、冲突和规范来源选择已检查。"
                ),
                "next_action": (
                    "canonical 语义通过，Silver 分区可供下游消费。"
                    if not failed_rule_names
                    else "按 failed_rule_names 和样本审计 Raw/identity/Silver。"
                ),
                "partition_key": partition_key,
                "failed_rule_names": list(failed_rule_names),
                "rule_summary": metric_summary,
                "mapping_failure_samples": list(mapping_samples),
                "content_failure_samples": list(content_samples),
            },
        ),
    )
