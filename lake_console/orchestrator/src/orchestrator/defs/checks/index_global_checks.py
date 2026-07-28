"""Partition-attributable core checks for the international index assets."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_global_raw import raw_index_global
from orchestrator.defs.assets.index_global_silver import silver_index_global
from orchestrator.defs.duckdb_sql import describe_parquet_query, duckdb_string, read_parquet
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.index_global import INDEX_GLOBAL_EXPECTED_CODES
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _single_partition(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _sample_rows(connection: Any, path: Path, *, predicate: str) -> list[dict[str, object]]:
    rows = connection.execute(
        f"SELECT * FROM {read_parquet(path)} WHERE {predicate} LIMIT 3"
    ).fetchall()
    columns = [row[0] for row in connection.execute(describe_parquet_query(path)).fetchall()]
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
    path: Path,
    schema: Sequence[object],
) -> dg.AssetCheckResult:
    partition_key = _single_partition(context)
    if partition_key is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                extra_metadata={
                    "failed_rule_names": ["single_partition_execution"],
                    "reason_code": "multiple_partition_execution",
                    "partition_key": None,
                    "rule_results": {},
                    "failure_samples": [],
                },
            ),
        )

    expected_columns = tuple(column.name for column in schema)
    expected_types = {column.name: column.type.upper() for column in schema}
    if not path.exists():
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.FILE_EXISTS,
                file_path=path,
                checked_row_count=0,
                failed_row_count=0,
                missing_file_paths=(path,),
                extra_metadata={
                    "failed_rule_names": ["file_exists"],
                    "reason_code": "file_missing",
                    "partition_key": partition_key,
                    "rule_results": {"file_exists": False},
                    "failure_samples": [],
                },
            ),
        )

    failed_rules: list[str] = []
    rule_results: dict[str, object] = {}
    failure_samples: list[dict[str, object]] = []
    with duckdb_resource.connect() as connection:
        describe_rows = connection.execute(describe_parquet_query(path)).fetchall()
        observed_columns = tuple(str(row[0]) for row in describe_rows)
        observed_types = {str(row[0]): str(row[1]).upper() for row in describe_rows}
        schema_ok = observed_columns == expected_columns and all(
            observed_types.get(name) == expected_types[name] for name in expected_columns
        )
        rule_results["schema_exact"] = schema_ok
        row_count = int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(path)}"
            ).fetchone()[0]
        )
        if not schema_ok:
            failed_rules.append("schema_exact")
        else:
            raw_date = partition_key.replace("-", "")
            date_mismatch_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(path)} "
                    "WHERE trade_date IS NULL OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> ?",
                    [raw_date],
                ).fetchone()[0]
            )
            null_identity_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(path)} "
                    "WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = '' "
                    f"OR trim(CAST(ts_code AS VARCHAR)) NOT IN "
                    f"({', '.join(duckdb_string(code) for code in INDEX_GLOBAL_EXPECTED_CODES)})",
                ).fetchone()[0]
            )
            duplicate_count = int(
                connection.execute(
                    f"SELECT count(*) - count(DISTINCT (ts_code, trade_date)) "
                    f"FROM {read_parquet(path)}"
                ).fetchone()[0]
            )
            numeric_predicate = " OR ".join(
                f'("{field}" IS NOT NULL AND NOT isfinite("{field}"))'
                for field in expected_columns[2:]
            )
            non_finite_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(path)} "
                    f"WHERE {numeric_predicate}"
                ).fetchone()[0]
            )
            rule_results.update(
                {
                    "partition_trade_date_match": date_mismatch_count == 0,
                    "ts_code_non_null_and_known": null_identity_count == 0,
                    "unique_ts_code_trade_date": duplicate_count == 0,
                    "numeric_values_finite": non_finite_count == 0,
                    "partition_trade_date_mismatch_count": date_mismatch_count,
                    "ts_code_non_null_and_known_count": null_identity_count,
                    "duplicate_key_count": duplicate_count,
                    "numeric_not_finite_count": non_finite_count,
                }
            )
            if date_mismatch_count:
                failed_rules.append("partition_trade_date_match")
            if null_identity_count:
                failed_rules.append("ts_code_non_null_and_known")
            if duplicate_count:
                failed_rules.append("unique_ts_code_trade_date")
            if non_finite_count:
                failed_rules.append("numeric_values_finite")
            if failed_rules:
                failure_samples = _sample_rows(
                    connection,
                    path,
                    predicate=(
                        f"replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> {duckdb_string(raw_date)} "
                        "OR ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''"
                    ),
                )
        failed_row_count = sum(
            int(value)
            for value in (
                rule_results.get("partition_trade_date_mismatch_count", 0),
                rule_results.get("ts_code_non_null_and_known_count", 0),
                rule_results.get("duplicate_key_count", 0),
                rule_results.get("numeric_not_finite_count", 0),
            )
        )

    return dg.AssetCheckResult(
        passed=not failed_rules,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            checked_row_count=row_count,
            failed_row_count=failed_row_count,
            extra_metadata={
                "failed_rule_names": failed_rules,
                "reason_code": "ok" if not failed_rules else "core_contract_failed",
                "partition_key": partition_key,
                "observed_columns": list(observed_columns),
                "expected_columns": list(expected_columns),
                "rule_results": rule_results,
                "failure_samples": failure_samples[:3],
            },
        ),
    )


@dg.asset_check(
    asset=raw_index_global,
    name="raw_index_global_core_check",
    partitions_def=cn_global_index_trade_days,
    blocking=True,
)
def raw_index_global_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        path=raw_index_global_path(lake_root.root(), context.partition_key),
        schema=RAW_INDEX_GLOBAL_SCHEMA,
    )


@dg.asset_check(
    asset=silver_index_global,
    name="silver_index_global_core_check",
    partitions_def=cn_global_index_trade_days,
    blocking=True,
)
def silver_index_global_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb,
        path=silver_index_global_path(lake_root.root(), context.partition_key),
        schema=SILVER_INDEX_GLOBAL_SCHEMA,
    )


__all__ = ["raw_index_global_core_check", "silver_index_global_core_check"]
