"""Single, partition-attributable core checks for board Silver assets."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.dc_board_silver import (
    silver_dc_daily,
    silver_dc_index,
    silver_dc_member,
)
from orchestrator.defs.assets.dc_board_raw import (
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import silver_dc_daily_path, silver_dc_index_path, silver_dc_member_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_DC_DAILY_SCHEMA,
    SILVER_DC_INDEX_SCHEMA,
    SILVER_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import DC_DAILY_CATEGORIES, DC_INDEX_TYPES
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _selected_partition(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _result(
    *,
    passed: bool,
    check_scope: CheckScope,
    partition_key: str | None,
    file_path: Path | None,
    checked_row_count: int,
    failed_row_count: int,
    failed_rules: Sequence[str],
    reason_code: str,
    failure_samples: Sequence[dict[str, Any]] = (),
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=check_scope,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=file_path,
            extra_metadata={
                "partition_key": partition_key,
                "failed_rules": list(failed_rules),
                "reason_code": reason_code,
                "failure_samples": list(failure_samples)[:5],
            },
        ),
    )


def _sample_rows(connection, relation: str, columns: Sequence[str], condition: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM {relation} WHERE {condition} LIMIT 5"
    ).fetchmany(5)
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
    path_builder,
    schema,
    key_columns: Sequence[str],
    identity_condition: str,
    numeric_condition: str,
) -> dg.AssetCheckResult:
    partition_key = _selected_partition(context)
    if partition_key is None:
        return _result(
            passed=False,
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            partition_key=None,
            file_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
        )

    path = path_builder(lake_root.root(), partition_key)
    if not path.exists():
        return _result(
            passed=False,
            check_scope=CheckScope.FILE_EXISTS,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("file_exists_and_row_count_positive",),
            reason_code="file_missing",
        )

    expected_columns = tuple(column.name for column in schema)
    expected_types = {column.name: str(column.type).upper() for column in schema}
    failed_rules: list[str] = []
    failed_row_count = 0
    samples: list[dict[str, Any]] = []

    with duckdb_resource.connect() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        describe_rows = connection.execute(describe_parquet_query(path)).fetchall()
        observed_columns = tuple(str(row[0]) for row in describe_rows)
        observed_types = {str(row[0]): str(row[1]).upper() for row in describe_rows}
        if observed_columns != expected_columns or any(
            observed_types.get(column) != expected_types[column]
            for column in expected_columns
        ):
            failed_rules.append("schema_matches_contract")
            samples.extend(
                _sample_rows(connection, relation, expected_columns[:3], "TRUE")
            )

        checked_row_count = int(connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0])
        if checked_row_count <= 0:
            failed_rules.append("row_count_positive")

        key_null_condition = " OR ".join(
            f"{column} IS NULL OR trim(CAST({column} AS VARCHAR)) = ''"
            for column in key_columns
        )
        null_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM {relation} WHERE {key_null_condition}"
            ).fetchone()[0]
        )
        if null_key_count:
            failed_rules.append("business_key_non_null")
            failed_row_count += null_key_count
            samples.extend(_sample_rows(connection, relation, key_columns, key_null_condition))

        key_expr = ", ".join(key_columns)
        duplicate_group_count = int(
            connection.execute(
                f"""
                SELECT count(*) FROM (
                    SELECT {key_expr}
                    FROM {relation}
                    GROUP BY {key_expr}
                    HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        )
        if duplicate_group_count:
            failed_rules.append("business_key_unique")
            failed_row_count += duplicate_group_count
            samples.extend(
                _sample_rows(
                    connection,
                    relation,
                    key_columns,
                    f"({key_expr}) IN (SELECT {key_expr} FROM {relation} GROUP BY {key_expr} HAVING count(*) > 1)",
                )
            )

        date_mismatch_condition = (
            f"trade_date IS NULL OR trade_date <> CAST('{partition_key}' AS DATE)"
        )
        date_mismatch_count = int(
            connection.execute(
                f"SELECT count(*) FROM {relation} WHERE {date_mismatch_condition}"
            ).fetchone()[0]
        )
        if date_mismatch_count:
            failed_rules.append("trade_date_matches_partition")
            failed_row_count += date_mismatch_count
            samples.extend(_sample_rows(connection, relation, ("trade_date",), date_mismatch_condition))

        identity_failed_count = int(
            connection.execute(
                f"SELECT count(*) FROM {relation} WHERE NOT ({identity_condition})"
            ).fetchone()[0]
        )
        if identity_failed_count:
            failed_rules.append("dataset_identity_fields_legal")
            failed_row_count += identity_failed_count
            samples.extend(_sample_rows(connection, relation, key_columns, f"NOT ({identity_condition})"))

        numeric_failed_count = int(
            connection.execute(
                f"SELECT count(*) FROM {relation} WHERE {numeric_condition}"
            ).fetchone()[0]
        )
        if numeric_failed_count:
            failed_rules.append("numeric_value_domain_legal")
            failed_row_count += numeric_failed_count
            samples.extend(_sample_rows(connection, relation, expected_columns[:5], numeric_condition))

    return _result(
        passed=not failed_rules,
        check_scope=CheckScope.VALUE_SANITY,
        partition_key=partition_key,
        file_path=path,
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
        failed_rules=failed_rules,
        reason_code="ready" if not failed_rules else "silver_core_check_failed",
        failure_samples=samples,
    )


_INDEX_IDENTITY = (
    f"ts_code IS NOT NULL AND regexp_full_match(ts_code, '^BK[0-9]{{4}}\\.DC$') "
    f"AND name IS NOT NULL AND trim(name) <> '' "
    f"AND idx_type IN ({', '.join(repr(value) for value in DC_INDEX_TYPES)}) "
    "AND (leading_code IS NULL OR regexp_full_match(leading_code, '^[0-9]{6}\\.(SZ|SH|BJ)$'))"
)
_INDEX_NUMERIC = (
    "(pct_change IS NOT NULL AND NOT isfinite(pct_change)) "
    "OR (leading_pct IS NOT NULL AND NOT isfinite(leading_pct)) "
    "OR (total_mv IS NOT NULL AND (NOT isfinite(total_mv) OR total_mv < 0)) "
    "OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0)) "
    "OR (up_num IS NOT NULL AND up_num < 0) OR (down_num IS NOT NULL AND down_num < 0)"
)
_MEMBER_IDENTITY = (
    "ts_code IS NOT NULL AND regexp_full_match(ts_code, '^BK[0-9]{4}\\.DC$') "
    "AND con_code IS NOT NULL AND regexp_full_match(con_code, '^[0-9]{6}\\.(SZ|SH|BJ)$') "
    "AND name IS NOT NULL AND trim(name) <> ''"
)
_DAILY_IDENTITY = (
    f"ts_code IS NOT NULL AND regexp_full_match(ts_code, '^BK[0-9]{{4}}\\.DC$') "
    f"AND category IN ({', '.join(repr(value) for value in DC_DAILY_CATEGORIES)})"
)
_DAILY_NUMERIC = (
    "(close IS NOT NULL AND (NOT isfinite(close) OR close < 0)) "
    "OR (open IS NOT NULL AND (NOT isfinite(open) OR open < 0)) "
    "OR (high IS NOT NULL AND (NOT isfinite(high) OR high < 0)) "
    "OR (low IS NOT NULL AND (NOT isfinite(low) OR low < 0)) "
    "OR (vol IS NOT NULL AND (NOT isfinite(vol) OR vol < 0)) "
    "OR (amount IS NOT NULL AND (NOT isfinite(amount) OR amount < 0)) "
    "OR (swing IS NOT NULL AND (NOT isfinite(swing) OR swing < 0)) "
    "OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0)) "
    "OR (change IS NOT NULL AND NOT isfinite(change)) "
    "OR (pct_change IS NOT NULL AND NOT isfinite(pct_change))"
)


@dg.asset_check(
    asset=silver_dc_index,
    additional_deps=[raw_tushare_dc_index],
    name="silver_dc_index_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def silver_dc_index_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        path_builder=silver_dc_index_path,
        schema=SILVER_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_condition=_INDEX_IDENTITY,
        numeric_condition=_INDEX_NUMERIC,
    )


@dg.asset_check(
    asset=silver_dc_member,
    additional_deps=[raw_tushare_dc_member],
    name="silver_dc_member_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def silver_dc_member_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        path_builder=silver_dc_member_path,
        schema=SILVER_DC_MEMBER_SCHEMA,
        key_columns=("trade_date", "ts_code", "con_code"),
        identity_condition=_MEMBER_IDENTITY,
        numeric_condition="FALSE",
    )


@dg.asset_check(
    asset=silver_dc_daily,
    additional_deps=[raw_tushare_dc_daily],
    name="silver_dc_daily_core_check",
    partitions_def=cn_a_index_trade_days,
    blocking=True,
)
def silver_dc_daily_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        path_builder=silver_dc_daily_path,
        schema=SILVER_DC_DAILY_SCHEMA,
        key_columns=("ts_code", "trade_date", "category"),
        identity_condition=_DAILY_IDENTITY,
        numeric_condition=_DAILY_NUMERIC,
    )


__all__ = [
    "silver_dc_daily_core_check",
    "silver_dc_index_core_check",
    "silver_dc_member_core_check",
]
