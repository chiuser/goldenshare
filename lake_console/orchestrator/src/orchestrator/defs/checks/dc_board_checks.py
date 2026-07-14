"""Single, partition-attributable core checks for board Raw assets."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.dc_board_raw import (
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_index_path, raw_dc_member_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _single_partition(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _sample_rows(connection, query: str, columns: Sequence[str]) -> list[dict[str, Any]]:
    rows = connection.execute(query).fetchmany(5)
    return [
        {
            column: value.isoformat() if hasattr(value, "isoformat") else value
            for column, value in zip(columns, row, strict=True)
        }
        for row in rows
    ]


def _core_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    dataset: str,
    path_builder,
    schema,
    key_columns: Sequence[str],
    identity_predicate: str,
    identity_columns: Sequence[str],
) -> dg.AssetCheckResult:
    partition_keys = _single_partition(context)
    if len(partition_keys) != 1:
        metadata = build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "failed_rules": ["single_partition_execution"],
                "reason_code": "multiple_partition_execution",
                "partition_key": None,
                "file_path": None,
                "checked_row_count": 0,
                "failed_row_count": 0,
                "failure_samples": [],
            },
        )
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                extra_metadata={
                    "failed_rules": ["single_partition_execution"],
                    "reason_code": "multiple_partition_execution",
                    "partition_key": None,
                    "file_path": None,
                    "checked_row_count": 0,
                    "failed_row_count": 0,
                    "failure_samples": [],
                },
            ),
        )

    partition_key = partition_keys[0]
    path = path_builder(lake_root.root(), partition_key)
    expected_columns = tuple(column.name for column in schema)
    expected_types = {column.name: column.type.upper() for column in schema}
    failed_rules: list[str] = []
    samples: list[dict[str, Any]] = []
    checked_row_count = 0
    failed_row_count = 0

    with duckdb_resource.connect() as connection:
        if not path.exists():
            failed_rules.append("file_exists_and_row_count_positive")
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.FILE_EXISTS,
                    file_path=path,
                    checked_row_count=0,
                    failed_row_count=0,
                    extra_metadata={
                        "failed_rules": failed_rules,
                        "reason_code": "file_missing",
                        "partition_key": partition_key,
                        "failure_samples": [],
                    },
                ),
            )
        try:
            describe_rows = connection.execute(describe_parquet_query(path)).fetchall()
            observed_columns = tuple(str(row[0]) for row in describe_rows)
            observed_types = {str(row[0]): str(row[1]).upper() for row in describe_rows}
            if observed_columns != expected_columns or any(
                observed_types.get(name) != expected_types[name] for name in expected_columns
            ):
                failed_rules.append("schema_matches_contract")
            row_count = int(
                connection.execute(f"SELECT count(*) FROM {read_parquet(path)}").fetchone()[0]
            )
            checked_row_count = row_count
            if row_count <= 0:
                failed_rules.append("row_count_positive")

            key_null_condition = " OR ".join(
                f"{column} IS NULL OR trim(CAST({column} AS VARCHAR)) = ''"
                for column in key_columns
            )
            null_key_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(path)} WHERE {key_null_condition}"
                ).fetchone()[0]
            )
            if null_key_count:
                failed_rules.append("business_key_non_null")
                failed_row_count += null_key_count

            key_expr = ", ".join(key_columns)
            duplicate_key_count = int(
                connection.execute(
                    f"""
                    SELECT count(*) FROM (
                        SELECT {key_expr}
                        FROM {read_parquet(path)}
                        GROUP BY {key_expr}
                        HAVING count(*) > 1
                    )
                    """
                ).fetchone()[0]
            )
            if duplicate_key_count:
                failed_rules.append("business_key_unique")
                failed_row_count += duplicate_key_count

            raw_trade_date = partition_key.replace("-", "")
            date_mismatch_count = int(
                connection.execute(
                    f"""
                    SELECT count(*) FROM {read_parquet(path)}
                    WHERE trade_date IS NULL
                       OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> ?
                    """,
                    [raw_trade_date],
                ).fetchone()[0]
            )
            if date_mismatch_count:
                failed_rules.append("trade_date_matches_partition")
                failed_row_count += date_mismatch_count

            identity_failed_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(path)} WHERE NOT ({identity_predicate})"
                ).fetchone()[0]
            )
            if identity_failed_count:
                failed_rules.append("dataset_identity_fields_legal")
                failed_row_count += identity_failed_count

            if failed_rules:
                sample_query = (
                    f"SELECT {', '.join(identity_columns)} FROM {read_parquet(path)} "
                    f"WHERE NOT ({identity_predicate}) LIMIT 5"
                )
                samples = _sample_rows(connection, sample_query, identity_columns)
        except Exception as exc:
            failed_rules.append("duckdb_scan")
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.SCHEMA,
                    file_path=path,
                    checked_row_count=checked_row_count,
                    failed_row_count=failed_row_count,
                    extra_metadata={
                        "failed_rules": failed_rules,
                        "reason_code": "scan_error",
                        "partition_key": partition_key,
                        "failure_samples": [{"error": str(exc)[:500]}],
                    },
                ),
            )

    return dg.AssetCheckResult(
        passed=not failed_rules,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            file_path=path,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            extra_metadata={
                "failed_rules": failed_rules,
                "reason_code": "core_check_failed" if failed_rules else "ready",
                "partition_key": partition_key,
                "failure_samples": samples,
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_dc_index,
    name="raw_tushare_dc_index_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def raw_tushare_dc_index_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        dataset="dc_index",
        path_builder=raw_dc_index_path,
        schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_predicate=(
            "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
            "AND idx_type IN ('行业板块', '概念板块', '地域板块') "
            "AND name IS NOT NULL AND trim(CAST(name AS VARCHAR)) <> ''"
        ),
        identity_columns=("ts_code", "idx_type", "name"),
    )


@dg.asset_check(
    asset=raw_tushare_dc_member,
    name="raw_tushare_dc_member_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def raw_tushare_dc_member_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        dataset="dc_member",
        path_builder=raw_dc_member_path,
        schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        key_columns=("trade_date", "ts_code", "con_code"),
        identity_predicate=(
            "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
            "AND con_code IS NOT NULL AND regexp_full_match(trim(CAST(con_code AS VARCHAR)), '^[0-9]{6}\\.(SZ|SH|BJ)$') "
            "AND name IS NOT NULL AND trim(CAST(name AS VARCHAR)) <> ''"
        ),
        identity_columns=("ts_code", "con_code", "name"),
    )


@dg.asset_check(
    asset=raw_tushare_dc_daily,
    name="raw_tushare_dc_daily_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def raw_tushare_dc_daily_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        dataset="dc_daily",
        path_builder=raw_dc_daily_path,
        schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        key_columns=("ts_code", "trade_date", "category"),
        identity_predicate=(
            "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
            "AND category IN ('行业板块', '概念板块', '地域板块')"
        ),
        identity_columns=("ts_code", "category"),
    )


__all__ = [
    "raw_tushare_dc_daily_core_check",
    "raw_tushare_dc_index_core_check",
    "raw_tushare_dc_member_core_check",
]
