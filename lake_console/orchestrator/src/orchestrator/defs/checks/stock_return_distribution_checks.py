from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_return_distribution import (
    STOCK_RETURN_DISTRIBUTION_COLUMNS,
    gold_stock_return_distribution,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    read_parquet,
    stock_return_distribution_select,
)
from orchestrator.defs.paths import (
    gold_stock_return_distribution_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


RETURN_BUCKET_COLUMNS = (
    "down_gt_10_count",
    "down_7_10_count",
    "down_5_7_count",
    "down_3_5_count",
    "down_0_3_count",
    "flat_count",
    "up_0_3_count",
    "up_3_5_count",
    "up_5_7_count",
    "up_7_10_count",
    "up_gt_10_count",
)


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "summary": "收益率分布 gold 检查失败：必需文件不存在。",
                "next_action": "先补跑对应分区的 gold_stock_return_distribution 或上游 silver_stock_daily。",
                "rule_summary": {
                    "missing_file_count": 1,
                    "failed_rule_names": ["file_exists"],
                },
                "file_path": str(path),
                "missing_file": True,
            },
        ),
    )


def _combined_next_action(failed_rule_names: Sequence[str]) -> str:
    if not failed_rule_names:
        return "无需处理，等待 ClickHouse serving 消费。"
    if "row_count_is_one" in failed_rule_names:
        return "重跑 gold_stock_return_distribution，目标分区必须恰好一行。"
    if "partition_date_matches" in failed_rule_names:
        return "检查 gold 分区目录和文件内 trade_date 是否一致。"
    if "total_count_matches_silver" in failed_rule_names:
        return "先检查同日 silver_stock_daily 行数，再重跑收益率分布 gold。"
    if "recomputed_from_silver" in failed_rule_names:
        return "检查收益率分桶口径是否仍与 silver_stock_daily 重算结果一致。"
    return "按 failed_rule_names 指向的规则修复收益率分布 gold 输出。"


def _combined_check_result(
    *,
    rule_results: Sequence[tuple[str, dg.AssetCheckResult]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    failed_rule_names = [
        rule_name for rule_name, result in rule_results if not bool(result.passed)
    ]
    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=check_scope,
            extra_metadata={
                "summary": (
                    "收益率分布 gold 聚合检查通过。"
                    if not failed_rule_names
                    else "收益率分布 gold 聚合检查失败，先看 failed_rule_names 指向的规则。"
                ),
                "next_action": _combined_next_action(failed_rule_names),
                "rule_summary": [
                    {"rule_name": rule_name, "passed": bool(result.passed)}
                    for rule_name, result in rule_results
                ],
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def _distribution_row(connection, path: Path) -> dict[str, Any] | None:
    row = connection.execute(
        f"""
        SELECT {", ".join(STOCK_RETURN_DISTRIBUTION_COLUMNS)}
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    result = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
    }
    for column, value in zip(
        STOCK_RETURN_DISTRIBUTION_COLUMNS[1:], row[1:], strict=True
    ):
        result[column] = int(value)
    return result


def _recomputed_row(
    connection, silver_path: Path, partition_key: str
) -> dict[str, Any] | None:
    row = connection.execute(
        stock_return_distribution_select(silver_path, partition_key)
    ).fetchone()
    if row is None:
        return None
    result = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
    }
    for column, value in zip(
        STOCK_RETURN_DISTRIBUTION_COLUMNS[1:], row[1:], strict=True
    ):
        result[column] = int(value)
    return result


def gold_stock_return_distribution_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count == 1,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "checked_row_count": int(row_count),
            },
        ),
    )


def gold_stock_return_distribution_counts_add_up(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    bucket_sum_expression = " + ".join(RETURN_BUCKET_COLUMNS)
    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {bucket_sum_expression} != total_count
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT {", ".join(STOCK_RETURN_DISTRIBUTION_COLUMNS)}
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {bucket_sum_expression} != total_count
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "summary": (
                    "收益率分布十一段桶合计检查通过。"
                    if mismatch_count == 0
                    else "收益率分布十一段桶合计检查失败，桶合计必须等于 total_count。"
                ),
                "next_action": (
                    "无需处理，等待后续检查。"
                    if mismatch_count == 0
                    else "检查 pct_chg 分桶 SQL 和 total_count 生成逻辑，再重跑 gold_stock_return_distribution。"
                ),
                "rule_summary": {
                    "bucket_count": len(RETURN_BUCKET_COLUMNS),
                    "mismatch_count": int(mismatch_count),
                },
                "file_path": str(path),
                "partition_key": partition_key,
                "mismatch_count": int(mismatch_count),
                "mismatch_sample_rows": _sample_dicts(
                    STOCK_RETURN_DISTRIBUTION_COLUMNS, rows
                ),
            },
        ),
    )


def gold_stock_return_distribution_total_count_matches_silver(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with connect_configured_duckdb() as connection:
        gold_total_count = connection.execute(
            f"""
            SELECT total_count
            FROM {read_parquet(gold_path, hive_partitioning=False)}
            LIMIT 1
            """
        ).fetchone()[0]
        silver_row_count = connection.execute(
            count_parquet_query(silver_path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=int(gold_total_count) == int(silver_row_count),
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "gold_file_path": str(gold_path),
                "silver_file_path": str(silver_path),
                "partition_key": partition_key,
                "gold_total_count": int(gold_total_count),
                "silver_row_count": int(silver_row_count),
            },
        ),
    )


def gold_stock_return_distribution_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL
               OR CAST(trade_date AS DATE) != DATE '{partition_key}'
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=not rows,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "invalid_row_count": len(rows),
                "invalid_sample_rows": _sample_dicts(["trade_date"], rows),
            },
        ),
    )


def gold_stock_return_distribution_recomputed_from_silver(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_stock_return_distribution_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with connect_configured_duckdb() as connection:
        gold_row = _distribution_row(connection, gold_path)
        recomputed_row = _recomputed_row(connection, silver_path, partition_key)

    return dg.AssetCheckResult(
        passed=gold_row == recomputed_row,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "gold_file_path": str(gold_path),
                "silver_file_path": str(silver_path),
                "partition_key": partition_key,
                "gold_row": gold_row,
                "recomputed_row": recomputed_row,
            },
        ),
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "row_count_is_one",
                gold_stock_return_distribution_row_count_is_one(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "partition_date_matches",
                gold_stock_return_distribution_partition_date_matches(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
        ),
        check_scope=CheckScope.ROW_COUNT,
    )


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_value_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return gold_stock_return_distribution_counts_add_up(context, lake_root, duckdb)


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_silver_reconciliation_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "total_count_matches_silver",
                gold_stock_return_distribution_total_count_matches_silver(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "recomputed_from_silver",
                gold_stock_return_distribution_recomputed_from_silver(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
        ),
        check_scope=CheckScope.RECONCILIATION,
    )
