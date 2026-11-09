"""Blocking checks for the single-day quantitative structure result."""

from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.major_index_quantitative_structure import (
    gold_major_index_quantitative_structure,
)
from orchestrator.defs.io.major_index_quantitative_structure import (
    structure_result_contract_error,
)
from orchestrator.defs.partitions import (
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.paths import gold_major_index_quantitative_structure_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_COMPLETION_CHECK,
    STRUCTURE_RESULT_CHECK,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def structure_check_metadata(
    path: Path, partition_key: str, *, scope: CheckScope, error: str | None = None,
) -> dict:
    return build_check_metadata(
        check_scope=scope, checked_row_count=int(path.is_file()),
        failed_row_count=int(error is not None), file_path=path,
        extra_metadata={
            "partition_key": partition_key,
            "summary": error or "量化结构分区检查通过。",
            "next_action": "查看当日作业日志并重跑分区。" if error else "无需处理。",
            "failed_rule_names": [scope.value] if error else [],
            "failure_samples": [{"trade_date": partition_key, "reason": error}] if error else [],
        },
    )


@dg.asset_check(
    name=STRUCTURE_RESULT_CHECK, asset=gold_major_index_quantitative_structure,
    partitions_def=cn_major_index_quantitative_structure_trade_days, blocking=True,
    description="检查量化结构文件字段、交易日、单日一行和事件取值。",
)
def gold_major_index_quantitative_structure_result_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    day = context.partition_key
    path = gold_major_index_quantitative_structure_path(lake_root.root(), day)
    with duckdb.connect() as connection:
        error = structure_result_contract_error(connection, path, date.fromisoformat(day))
    return dg.AssetCheckResult(
        passed=error is None, severity=dg.AssetCheckSeverity.ERROR,
        metadata=structure_check_metadata(path, day, scope=CheckScope.SCHEMA, error=error),
    )


@dg.asset_check(
    name=STRUCTURE_COMPLETION_CHECK, asset=gold_major_index_quantitative_structure,
    partitions_def=cn_major_index_quantitative_structure_trade_days, blocking=True,
    description="检查该交易日的量化结构已成功计算。",
)
def gold_major_index_quantitative_structure_completion_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    day = context.partition_key
    path = gold_major_index_quantitative_structure_path(lake_root.root(), day)
    error = "结果文件不存在"
    if path.is_file():
        with duckdb.connect() as connection:
            rows = connection.execute(
                "SELECT success FROM read_parquet(?, hive_partitioning=false) LIMIT 2", [str(path)],
            ).fetchall()
        error = None if rows == [(True,)] else "该日量化结构计算未完成"
    return dg.AssetCheckResult(
        passed=error is None, severity=dg.AssetCheckSeverity.ERROR,
        metadata=structure_check_metadata(path, day, scope=CheckScope.VALUE_SANITY, error=error),
    )
