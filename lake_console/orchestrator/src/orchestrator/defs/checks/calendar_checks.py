from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import raw_trade_calendar_path, silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


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
                "summary": "交易日历文件不存在，当前 check 无法继续验证。",
                "next_action": "先运行 calendar_update_job 生成 raw/silver 交易日历文件。",
                "rule_summary": ["file_exists"],
                "file_path": str(path),
                "missing_file": True,
            },
        ),
    )


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
                    "交易日历聚合检查通过。"
                    if not failed_rule_names
                    else "交易日历聚合检查失败，请先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，等待下游消费。"
                    if not failed_rule_names
                    else "按 failed_rule_names 修复交易日历文件或重新运行 calendar_update_job。"
                ),
                "rule_summary": [rule_name for rule_name, _ in rule_results],
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def raw_trade_calendar_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "exists": path.exists(),
            },
        ),
    )


def raw_trade_calendar_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)

    missing_columns = [
        column
        for column in TRADE_CALENDAR_RAW_REQUIRED_COLUMNS
        if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "observed_columns": columns,
                "required_columns": list(TRADE_CALENDAR_RAW_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


def raw_trade_calendar_contains_required_exchange(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            f"""
            SELECT count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
            """
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "required_exchange": "SSE",
                "checked_row_count": int(row_count),
            },
        ),
    )


@dg.asset_check(asset="raw_tushare_trade_calendar", blocking=True)
def raw_trade_calendar_contract_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            ("file_exists", raw_trade_calendar_file_exists(lake_root)),
            (
                "required_columns",
                raw_trade_calendar_required_columns(lake_root, duckdb),
            ),
            (
                "contains_required_exchange",
                raw_trade_calendar_contains_required_exchange(lake_root, duckdb),
            ),
        ),
        check_scope=CheckScope.SCHEMA,
    )


@dg.asset_check(asset="silver_trade_calendar", blocking=True)
def silver_trade_calendar_unique_exchange_trade_date(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT exchange, trade_date, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY exchange, trade_date
            HAVING count(*) > 1
            ORDER BY exchange, trade_date
            LIMIT 10
            """
        ).fetchall()

    duplicate_count = len(rows)
    return dg.AssetCheckResult(
        passed=duplicate_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "duplicate_key_count": duplicate_count,
                "duplicate_sample_keys": _sample_dicts(
                    ["exchange", "trade_date", "row_count"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset="silver_trade_calendar", blocking=True)
def silver_trade_calendar_required_columns_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        null_count = connection.execute(
            f"""
            SELECT count(*) AS null_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange IS NULL
               OR trade_date IS NULL
               OR is_open IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT exchange, trade_date, is_open
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange IS NULL
               OR trade_date IS NULL
               OR is_open IS NULL
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "null_row_count": int(null_count),
                "null_sample_rows": _sample_dicts(
                    ["exchange", "trade_date", "is_open"], rows
                ),
            },
        ),
    )
