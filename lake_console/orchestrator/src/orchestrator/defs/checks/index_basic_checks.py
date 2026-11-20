from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_basic import (
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    INDEX_BASIC_SILVER_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.io.index_basic_publication import (
    INDEX_BASIC_COVERAGE_METADATA_KEY,
)
from orchestrator.defs.io.index_basic_snapshot import (
    duplicate_codes_sql,
    invalid_raw_dates_sql,
    terminated_index_predicate,
)
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.paths import raw_index_basic_path, silver_index_basic_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_INDEX_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    READY_FOR_TRADE_DATE_METADATA_KEY,
    CheckScope,
    build_check_metadata,
)

INDEX_BASIC_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_BASIC_SCHEMA
}


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [row[0] for row in rows]


def _column_types(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {row[0]: str(row[1]).upper() for row in rows}


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
                "summary": "指数基础信息文件不存在，当前 check 无法继续验证。",
                "next_action": "先运行 index_basic_update_job 生成 raw 或 silver 文件。",
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
    coverage_metadata: dict | None = None,
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
                    "指数基础信息聚合检查通过。"
                    if not failed_rule_names
                    else "指数基础信息聚合检查失败，请先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，有效指数池可供下游消费。"
                    if not failed_rule_names
                    else "按 failed_rule_names 修复 raw/silver 指数基础信息后再重跑。"
                ),
                "rule_summary": [rule_name for rule_name, _ in rule_results],
                "rule_passed": {
                    rule_name: bool(result.passed) for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
                **(coverage_metadata or {}),
            },
        ),
    )


def _latest_snapshot(instance: dg.DagsterInstance, asset: str):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey(asset)),
        limit=1,
    ).records
    return records[0] if records else None


def _coverage_metadata(record, path: Path) -> dict:
    if record is None or record.asset_materialization is None or not path.is_file():
        return {}
    value = record.asset_materialization.metadata.get(INDEX_BASIC_COVERAGE_METADATA_KEY)
    evidence = getattr(value, "value", None)
    if not isinstance(evidence, dict) or evidence.get("file_version") != file_version(
        path
    ):
        return {}
    return {
        INDEX_BASIC_COVERAGE_METADATA_KEY: {
            **evidence,
            "materialization_id": record.storage_id,
            "materialization_run_id": record.run_id,
        }
    }


def raw_index_basic_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
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


def raw_index_basic_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(path, hive_partitioning=False)
            ).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "checked_row_count": row_count,
            },
        ),
    )


def raw_index_basic_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)

    missing_columns = [
        column for column in INDEX_BASIC_RAW_COLUMNS if column not in columns
    ]
    unexpected_columns = [
        column for column in columns if column not in INDEX_BASIC_RAW_COLUMNS
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns and not unexpected_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "observed_columns": columns,
                "required_columns": list(INDEX_BASIC_RAW_COLUMNS),
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
            },
        ),
    )


def raw_index_basic_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = duplicate_codes_sql(path)
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS missing_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                """
            ).fetchone()[0]
        )
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        duplicate_rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0 and duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "missing_ts_code_count": missing_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "row_count"], duplicate_rows
                ),
            },
        ),
    )


def raw_index_basic_date_strings_parseable(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    invalid_date_rows_sql = invalid_raw_dates_sql(path)
    with connect_configured_duckdb() as connection:
        invalid_date_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({invalid_date_rows_sql}) invalid_dates"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {invalid_date_rows_sql}
            ORDER BY ts_code, field_name
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_date_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            extra_metadata={
                "file_path": str(path),
                "invalid_date_count": invalid_date_count,
                "invalid_date_sample_rows": _sample_dicts(
                    ["ts_code", "field_name", "field_value"], rows
                ),
            },
        ),
    )


def silver_index_basic_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
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


def silver_index_basic_required_columns_and_types(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)
        column_types = _column_types(connection, path)

    missing_columns = [
        column for column in INDEX_BASIC_SILVER_COLUMNS if column not in columns
    ]
    unexpected_columns = [
        column for column in columns if column not in INDEX_BASIC_SILVER_COLUMNS
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in INDEX_BASIC_SILVER_COLUMN_TYPES.items()
        if column in column_types and column_types[column] != expected_type
    }
    return dg.AssetCheckResult(
        passed=not missing_columns and not unexpected_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "observed_columns": columns,
                "column_types": column_types,
                "required_columns": list(INDEX_BASIC_SILVER_COLUMNS),
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


def silver_index_basic_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(path, hive_partitioning=False)
            ).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "checked_row_count": row_count,
            },
        ),
    )


def silver_index_basic_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = duplicate_codes_sql(path)
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS missing_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                """
            ).fetchone()[0]
        )
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        duplicate_rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0 and duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "missing_ts_code_count": missing_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "row_count"], duplicate_rows
                ),
            },
        ),
    )


def silver_index_basic_required_fields_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    required_non_null_columns = ("ts_code", "name", "market")
    with connect_configured_duckdb() as connection:
        null_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS null_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL
                   OR trim(ts_code) = ''
                   OR name IS NULL
                   OR trim(name) = ''
                   OR market IS NULL
                   OR trim(market) = ''
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, market
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR name IS NULL
               OR trim(name) = ''
               OR market IS NULL
               OR trim(market) = ''
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "required_non_null_columns": list(required_non_null_columns),
                "null_row_count": null_count,
                "null_sample_rows": _sample_dicts(["ts_code", "name", "market"], rows),
            },
        ),
    )


def silver_index_basic_no_terminated_indexes(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    snapshot = _latest_snapshot(context.instance, "silver_index_basic")
    materialization = snapshot.asset_materialization if snapshot is not None else None
    date_metadata = (
        materialization.metadata.get(READY_FOR_TRADE_DATE_METADATA_KEY)
        if materialization
        else None
    )
    ready_for_trade_date = getattr(date_metadata, "value", None)
    if not ready_for_trade_date:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                extra_metadata={
                    "file_path": str(path),
                    "missing_ready_for_trade_date_metadata": True,
                },
            ),
        )

    ready_for_trade_date = str(ready_for_trade_date)
    predicate = terminated_index_predicate(ready_for_trade_date)
    with connect_configured_duckdb() as connection:
        terminated_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS terminated_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE {predicate}
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, exp_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {predicate}
            ORDER BY exp_date, ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=terminated_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "ready_for_trade_date": ready_for_trade_date,
                "terminated_count": terminated_count,
                "terminated_sample_rows": _sample_dicts(
                    ["ts_code", "name", "exp_date"], rows
                ),
                **_coverage_metadata(snapshot, path),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            ("file_exists", raw_index_basic_file_exists(lake_root)),
            (
                "row_count_positive",
                raw_index_basic_row_count_positive(lake_root, duckdb),
            ),
            ("required_columns", raw_index_basic_required_columns(lake_root, duckdb)),
        ),
        check_scope=CheckScope.SCHEMA,
        coverage_metadata=_coverage_metadata(
            _latest_snapshot(context.instance, "raw_tushare_index_basic"),
            raw_index_basic_path(lake_root.root()),
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_key_integrity_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return raw_index_basic_unique_ts_code(lake_root, duckdb)


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_date_domain_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return raw_index_basic_date_strings_parseable(lake_root, duckdb)


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_contract_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            ("file_exists", silver_index_basic_file_exists(lake_root)),
            (
                "required_columns_and_types",
                silver_index_basic_required_columns_and_types(lake_root, duckdb),
            ),
            (
                "row_count_positive",
                silver_index_basic_row_count_positive(lake_root, duckdb),
            ),
            (
                "required_fields_non_null",
                silver_index_basic_required_fields_non_null(lake_root, duckdb),
            ),
        ),
        check_scope=CheckScope.SCHEMA,
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_key_integrity_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return silver_index_basic_unique_ts_code(lake_root, duckdb)


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_lifecycle_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return silver_index_basic_no_terminated_indexes(context, lake_root, duckdb)
