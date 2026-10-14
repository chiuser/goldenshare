from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_COLUMNS,
)
from orchestrator.defs.stock_factor_price_checks import (
    daily_qfq_column_names,
    daily_qfq_contract_failure_samples,
    daily_qfq_contract_rule_counts,
    daily_qfq_row_count,
)

GOLD_STOCK_DAILY_QFQ_CHECK_NAMES = (
    "gold_stock_daily_qfq_contract_check",
)




def _missing_file_result(path: Path, *, check_scope: CheckScope) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "summary": "股票日线前复权检查失败：必需文件不存在。",
                "next_action": "先生成缺失文件，再重新运行 gold_stock_daily_qfq 或对应 check。",
                "failed_rule_names": ["file_exists"],
            },
        ),
    )










@dg.asset_check(
    asset=gold_stock_daily_qfq,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def gold_stock_daily_qfq_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_daily_qfq_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path, check_scope=CheckScope.FILE_EXISTS)

    expected_columns = tuple(GOLD_STOCK_DAILY_QFQ_COLUMNS)
    connect_duckdb = duckdb.connect
    connection_context = connect_duckdb()
    with connection_context as connection:
        observed_columns = tuple(daily_qfq_column_names(connection, path))
        row_count = daily_qfq_row_count(connection, path)
        failed_rule_names = []
        if row_count <= 0:
            failed_rule_names.append("row_count_positive")
        if observed_columns != expected_columns:
            failed_rule_names.append("schema_matches_contract")
            rule_counts = {
                "partition_date_mismatch_count": 0,
                "null_key_count": 0,
                "duplicate_key_count": 0,
            }
            samples: list[dict[str, Any]] = []
        else:
            rule_counts = daily_qfq_contract_rule_counts(connection, path, partition_key)
            if rule_counts["partition_date_mismatch_count"]:
                failed_rule_names.append("partition_date_matches")
            if rule_counts["null_key_count"]:
                failed_rule_names.append("key_columns_non_null")
            if rule_counts["duplicate_key_count"]:
                failed_rule_names.append("unique_ts_code_trade_date")
            samples = daily_qfq_contract_failure_samples(connection, path, partition_key)

    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            failed_row_count=(
                rule_counts["partition_date_mismatch_count"]
                + rule_counts["null_key_count"]
                + rule_counts["duplicate_key_count"]
            ),
            file_path=path,
            extra_metadata={
                "summary": (
                    "股票日线前复权 contract check 通过。"
                    if not failed_rule_names
                    else "股票日线前复权 contract check 失败，先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，等待下游日常链路或 repair 链路消费。"
                    if not failed_rule_names
                    else "检查目标 Parquet 的 schema、partition date 和主键唯一性，再重跑 asset/check。"
                ),
                "partition_key": partition_key,
                "observed_columns": list(observed_columns),
                "expected_columns": list(expected_columns),
                "failed_rule_names": failed_rule_names,
                **rule_counts,
                "sample_rows": samples,
            },
        ),
    )
