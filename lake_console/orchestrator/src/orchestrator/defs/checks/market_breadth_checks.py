from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    market_breadth_daily_select,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


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
                "summary": "市场宽度 gold 检查失败：必需文件不存在。",
                "next_action": "先补跑对应分区的 gold_market_breadth_daily 或上游 silver_stock_daily。",
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
    if "total_count_matches_silver" in failed_rule_names:
        return "先检查同日 silver_stock_daily 行数，再重跑 gold_market_breadth_daily。"
    if "matches_silver_recompute" in failed_rule_names:
        return "检查市场宽度计算公式是否仍与 silver_stock_daily 重算结果一致。"
    if any("red_rate" in rule_name for rule_name in failed_rule_names):
        return "检查 red_rate 是否按 up_count / total_count * 100 计算并落在 0 到 100。"
    return "按 failed_rule_names 指向的规则修复市场宽度 gold 输出。"


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
                    "市场宽度 gold 聚合检查通过。"
                    if not failed_rule_names
                    else "市场宽度 gold 聚合检查失败，先看 failed_rule_names 指向的规则。"
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


def _gold_row(connection, path: Path) -> dict[str, Any] | None:
    row = connection.execute(
        f"""
        SELECT
          trade_date,
          up_count,
          down_count,
          flat_count,
          total_count,
          red_rate
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
        "up_count": int(row[1]),
        "down_count": int(row[2]),
        "flat_count": int(row[3]),
        "total_count": int(row[4]),
        "red_rate": float(row[5]),
    }


def _recomputed_row(
    connection, silver_path: Path, partition_key: str
) -> dict[str, Any] | None:
    row = connection.execute(
        market_breadth_daily_select(silver_path, partition_key)
    ).fetchone()
    if row is None:
        return None
    return {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
        "up_count": int(row[1]),
        "down_count": int(row[2]),
        "flat_count": int(row[3]),
        "total_count": int(row[4]),
        "red_rate": float(row[5]),
    }


def gold_market_breadth_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
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
                "summary": (
                    "市场宽度 gold 行数检查通过。"
                    if row_count == 1
                    else "市场宽度 gold 行数检查失败，目标分区必须恰好一行。"
                ),
                "next_action": (
                    "无需处理，等待后续检查。"
                    if row_count == 1
                    else "重跑 gold_market_breadth_daily；若仍异常，检查写入是否产生重复或空结果。"
                ),
                "rule_summary": {
                    "expected_row_count": 1,
                    "actual_row_count": int(row_count),
                },
                "file_path": str(path),
                "partition_key": partition_key,
                "checked_row_count": int(row_count),
            },
        ),
    )


def gold_market_breadth_counts_add_up(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE up_count + down_count + flat_count != total_count
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT trade_date, up_count, down_count, flat_count, total_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE up_count + down_count + flat_count != total_count
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "mismatch_count": int(mismatch_count),
                "mismatch_sample_rows": _sample_dicts(
                    [
                        "trade_date",
                        "up_count",
                        "down_count",
                        "flat_count",
                        "total_count",
                    ],
                    rows,
                ),
            },
        ),
    )


def gold_market_breadth_total_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date, total_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE total_count <= 0
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
                "invalid_sample_rows": _sample_dicts(
                    ["trade_date", "total_count"], rows
                ),
            },
        ),
    )


def gold_market_breadth_total_count_matches_silver(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
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


def gold_market_breadth_red_rate_range(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT trade_date, red_rate
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE red_rate < 0 OR red_rate > 100
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
                "invalid_sample_rows": _sample_dicts(["trade_date", "red_rate"], rows),
            },
        ),
    )


def gold_market_breadth_red_rate_formula(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT
              trade_date,
              up_count,
              total_count,
              red_rate,
              CASE
                WHEN total_count = 0 THEN 0.0
                ELSE ROUND(up_count * 100.0 / total_count, 2)
              END AS expected_red_rate
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ABS(
              red_rate - CASE
                WHEN total_count = 0 THEN 0.0
                ELSE ROUND(up_count * 100.0 / total_count, 2)
              END
            ) > 0.000001
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
                "invalid_sample_rows": _sample_dicts(
                    [
                        "trade_date",
                        "up_count",
                        "total_count",
                        "red_rate",
                        "expected_red_rate",
                    ],
                    rows,
                ),
            },
        ),
    )


def gold_market_breadth_matches_silver_recompute(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    gold_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not gold_path.exists():
        return _missing_file_result(gold_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with connect_configured_duckdb() as connection:
        gold_row = _gold_row(connection, gold_path)
        recomputed_row = _recomputed_row(connection, silver_path, partition_key)

    passed = gold_row == recomputed_row
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "gold_file_path": str(gold_path),
                "silver_file_path": str(silver_path),
                "partition_key": partition_key,
                "gold_row": gold_row or {},
                "recomputed_row": recomputed_row or {},
            },
        ),
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return gold_market_breadth_row_count_is_one(context, lake_root, duckdb)


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_value_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "counts_add_up",
                gold_market_breadth_counts_add_up(context, lake_root, duckdb),
            ),
            (
                "total_count_positive",
                gold_market_breadth_total_count_positive(context, lake_root, duckdb),
            ),
            (
                "red_rate_range",
                gold_market_breadth_red_rate_range(context, lake_root, duckdb),
            ),
            (
                "red_rate_formula",
                gold_market_breadth_red_rate_formula(context, lake_root, duckdb),
            ),
        ),
        check_scope=CheckScope.VALUE_SANITY,
    )


@dg.asset_check(
    asset=gold_market_breadth_daily,
    blocking=True,
)
def gold_market_breadth_silver_reconciliation_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "total_count_matches_silver",
                gold_market_breadth_total_count_matches_silver(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "matches_silver_recompute",
                gold_market_breadth_matches_silver_recompute(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
        ),
        check_scope=CheckScope.RECONCILIATION,
    )
