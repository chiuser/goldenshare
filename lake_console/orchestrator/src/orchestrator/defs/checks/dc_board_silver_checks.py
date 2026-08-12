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
from orchestrator.defs.asset_guards.dc_board_relations import audit_silver_board_relation
from orchestrator.defs.asset_guards.dc_board_silver_quality import (
    SILVER_DC_DAILY_QUALITY,
    SILVER_DC_INDEX_QUALITY,
    SILVER_DC_MEMBER_QUALITY,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.paths import silver_dc_index_path
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
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
    relation_mode: str | None = None,
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
        if relation_mode is not None:
            relation_failed_count, relation_samples = audit_silver_board_relation(
                connection,
                source_path=path,
                index_path=silver_dc_index_path(lake_root.root(), partition_key),
                mode=relation_mode,
            )
            if relation_failed_count:
                failed_rules.append("same_day_board_relation_integrity")
                failed_row_count += relation_failed_count
                samples.extend(relation_samples)

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


@dg.asset_check(
    asset=silver_dc_index,
    additional_deps=[raw_tushare_dc_index],
    name="silver_dc_index_core_check",
    partitions_def=cn_a_dc_index_trade_days,
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
        path_builder=SILVER_DC_INDEX_QUALITY.path_builder,
        schema=SILVER_DC_INDEX_QUALITY.schema,
        key_columns=SILVER_DC_INDEX_QUALITY.key_columns,
        identity_condition=SILVER_DC_INDEX_QUALITY.identity_condition,
        numeric_condition=SILVER_DC_INDEX_QUALITY.numeric_condition,
    )


@dg.asset_check(
    asset=silver_dc_member,
    additional_deps=[raw_tushare_dc_member, silver_dc_index],
    name="silver_dc_member_core_check",
    partitions_def=cn_a_dc_member_trade_days,
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
        path_builder=SILVER_DC_MEMBER_QUALITY.path_builder,
        schema=SILVER_DC_MEMBER_QUALITY.schema,
        key_columns=SILVER_DC_MEMBER_QUALITY.key_columns,
        identity_condition=SILVER_DC_MEMBER_QUALITY.identity_condition,
        numeric_condition=SILVER_DC_MEMBER_QUALITY.numeric_condition,
        relation_mode="member_subset_index",
    )


@dg.asset_check(
    asset=silver_dc_daily,
    additional_deps=[raw_tushare_dc_daily, silver_dc_index],
    name="silver_dc_daily_core_check",
    partitions_def=cn_a_dc_daily_trade_days,
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
        path_builder=SILVER_DC_DAILY_QUALITY.path_builder,
        schema=SILVER_DC_DAILY_QUALITY.schema,
        key_columns=SILVER_DC_DAILY_QUALITY.key_columns,
        identity_condition=SILVER_DC_DAILY_QUALITY.identity_condition,
        numeric_condition=SILVER_DC_DAILY_QUALITY.numeric_condition,
        relation_mode="index_subset_daily",
    )


__all__ = [
    "silver_dc_daily_core_check",
    "silver_dc_index_core_check",
    "silver_dc_member_core_check",
]
