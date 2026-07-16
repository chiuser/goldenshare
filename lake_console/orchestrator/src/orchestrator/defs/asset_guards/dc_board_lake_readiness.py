"""Bounded DuckDB readiness for the board Raw partitions.

This module deliberately has no Dagster instance access.  A sensor can scan a
small date window with one DuckDB connection and classify missing files apart
from materialized-but-invalid files.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.asset_guards.dc_board_relations import audit_raw_board_relation
from orchestrator.defs.asset_guards.dc_board_raw_quality import RAW_DC_QUALITY_SPECS, RawQualitySpec
from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_index_path, raw_dc_member_path


@dataclass(frozen=True)
class _ReadinessSpec:
    dataset: str
    check_name: str
    path_builder: object
    schema: Sequence[object]
    key_columns: tuple[str, ...]
    identity_predicate: str
    numeric_predicate: str
    coverage_column: str | None
    coverage_values: tuple[str, ...]


_SPECS = {
    "dc_index": _ReadinessSpec(
        dataset="dc_index",
        check_name=RAW_DC_QUALITY_SPECS["dc_index"].check_name,
        path_builder=raw_dc_index_path,
        schema=RAW_DC_QUALITY_SPECS["dc_index"].schema,
        key_columns=("ts_code", "trade_date"),
        identity_predicate=RAW_DC_QUALITY_SPECS["dc_index"].identity_condition,
        numeric_predicate=RAW_DC_QUALITY_SPECS["dc_index"].numeric_condition,
        coverage_column=RAW_DC_QUALITY_SPECS["dc_index"].coverage_column,
        coverage_values=RAW_DC_QUALITY_SPECS["dc_index"].coverage_values,
    ),
    "dc_member": _ReadinessSpec(
        dataset="dc_member",
        check_name=RAW_DC_QUALITY_SPECS["dc_member"].check_name,
        path_builder=raw_dc_member_path,
        schema=RAW_DC_QUALITY_SPECS["dc_member"].schema,
        key_columns=("trade_date", "ts_code", "con_code"),
        identity_predicate=RAW_DC_QUALITY_SPECS["dc_member"].identity_condition,
        numeric_predicate=RAW_DC_QUALITY_SPECS["dc_member"].numeric_condition,
        coverage_column=RAW_DC_QUALITY_SPECS["dc_member"].coverage_column,
        coverage_values=RAW_DC_QUALITY_SPECS["dc_member"].coverage_values,
    ),
    "dc_daily": _ReadinessSpec(
        dataset="dc_daily",
        check_name=RAW_DC_QUALITY_SPECS["dc_daily"].check_name,
        path_builder=raw_dc_daily_path,
        schema=RAW_DC_QUALITY_SPECS["dc_daily"].schema,
        key_columns=("ts_code", "trade_date", "category"),
        identity_predicate=RAW_DC_QUALITY_SPECS["dc_daily"].identity_condition,
        numeric_predicate=RAW_DC_QUALITY_SPECS["dc_daily"].numeric_condition,
        coverage_column=RAW_DC_QUALITY_SPECS["dc_daily"].coverage_column,
        coverage_values=RAW_DC_QUALITY_SPECS["dc_daily"].coverage_values,
    ),
}


def _path_list(paths: Sequence[Path]) -> str:
    return ", ".join(duckdb_string(path) for path in paths)


def _missing_status(spec: _ReadinessSpec, trade_date: str, path: Path) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=f"{spec.dataset} file is missing for {trade_date}",
        missing_check_names=(spec.check_name,),
        missing_file_paths=(str(path),),
        summary={"dataset": spec.dataset, "materialized": False},
    )


def _scan_existing(
    *,
    connection,
    spec: _ReadinessSpec,
    existing: Mapping[str, Path],
) -> dict[str, ContinuityDateReadiness]:
    if not existing:
        return {}
    paths = tuple(existing.values())
    expected_columns = tuple(column.name for column in spec.schema)
    expected_types = {column.name: column.type.upper() for column in spec.schema}
    relation = f"read_parquet([{_path_list(paths)}], hive_partitioning=false, filename=true)"
    null_key_predicate = " OR ".join(
        f"{column} IS NULL OR trim(CAST({column} AS VARCHAR)) = ''"
        for column in spec.key_columns
    )
    try:
        describe_rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet([{_path_list(paths)}], hive_partitioning=false)"
        ).fetchall()
        observed_columns = tuple(str(row[0]) for row in describe_rows)
        observed_types = {str(row[0]): str(row[1]).upper() for row in describe_rows}
        schema_error = observed_columns != expected_columns or any(
            observed_types.get(column) != expected_types[column] for column in expected_columns
        )
        key_expr = ", ".join(spec.key_columns)
        stats_rows = connection.execute(
            f"""
            WITH source AS (
                SELECT *, regexp_extract(filename, 'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})', 1) AS source_trade_date
                FROM {relation}
            ),
            aggregate AS (
                SELECT
                    source_trade_date,
                    count(*) AS row_count,
                    sum(CASE WHEN trade_date IS NULL OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> replace(source_trade_date, '-', '') THEN 1 ELSE 0 END) AS date_mismatch_count,
                    sum(CASE WHEN NOT ({spec.identity_predicate}) THEN 1 ELSE 0 END) AS identity_failed_count,
                    sum(CASE WHEN {spec.numeric_predicate} THEN 1 ELSE 0 END) AS numeric_failed_count,
                    {(
                        f"CASE WHEN count(DISTINCT {spec.coverage_column}) < {len(spec.coverage_values)} THEN 1 ELSE 0 END"
                        if spec.coverage_column and spec.coverage_values
                        else "0"
                    )} AS coverage_failed_count,
                    sum(CASE WHEN {null_key_predicate} THEN 1 ELSE 0 END) AS null_key_count
                FROM source
                GROUP BY source_trade_date
            ),
            duplicates AS (
                SELECT source_trade_date, count(*) AS duplicate_key_count
                FROM (
                    SELECT source_trade_date, {key_expr}
                    FROM source
                    GROUP BY source_trade_date, {key_expr}
                    HAVING count(*) > 1
                )
                GROUP BY source_trade_date
            )
            SELECT
                aggregate.source_trade_date,
                aggregate.row_count,
                aggregate.date_mismatch_count,
                aggregate.identity_failed_count,
                aggregate.null_key_count,
                aggregate.numeric_failed_count,
                aggregate.coverage_failed_count,
                coalesce(duplicates.duplicate_key_count, 0) AS duplicate_key_count
            FROM aggregate
            LEFT JOIN duplicates USING (source_trade_date)
            """
        ).fetchall()
        stats_by_date = {str(row[0]): row[1:] for row in stats_rows}
    except Exception as exc:
        return {
            trade_date: ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"{spec.dataset} readiness scan failed for {trade_date}",
                failed_check_names=(spec.check_name,),
                summary={"dataset": spec.dataset, "scan_error": str(exc)[:500]},
            )
            for trade_date in existing
        }

    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in existing:
        row = stats_by_date.get(trade_date)
        if row is None:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"{spec.dataset} partition date is missing from scan for {trade_date}",
                failed_check_names=(spec.check_name,),
                summary={"dataset": spec.dataset, "scan_error": "partition_not_observed"},
            )
            continue
        row_count, date_mismatch, identity_failed, null_key, numeric_failed, coverage_failed, duplicate_key = (
            int(value or 0) for value in row
        )
        failed_rules = []
        if row_count <= 0:
            failed_rules.append("row_count_positive")
        if schema_error:
            failed_rules.append("schema_matches_contract")
        if date_mismatch:
            failed_rules.append("trade_date_matches_partition")
        if null_key:
            failed_rules.append("business_key_non_null")
        if duplicate_key:
            failed_rules.append("business_key_unique")
        if identity_failed:
            failed_rules.append("dataset_identity_fields_legal")
        if numeric_failed:
            failed_rules.append("numeric_value_domain_legal")
        if coverage_failed:
            failed_rules.append("category_coverage_complete")
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=not failed_rules,
            materialized=True,
            checks_passed=not failed_rules,
            reason=(
                f"{spec.dataset} ready for {trade_date}"
                if not failed_rules
                else f"{spec.dataset} core checks failed for {trade_date}"
            ),
            failed_check_names=(spec.check_name,) if failed_rules else (),
            summary={
                "dataset": spec.dataset,
                "checked_row_count": row_count,
                "failed_row_count": (
                    date_mismatch
                    + identity_failed
                    + null_key
                    + numeric_failed
                    + coverage_failed
                    + duplicate_key
                ),
                "failed_rules": failed_rules,
                "schema_error": schema_error,
            },
        )
    return statuses


def batch_dc_board_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    dataset: str,
) -> ContinuityBatchReadiness:
    """Scan one board Raw dataset for a bounded date window with one connection."""

    started_at = perf_counter()
    spec = _SPECS[dataset]
    expected = tuple(str(value) for value in expected_trade_dates)
    registered = set(str(value) for value in registered_trade_days)
    statuses: dict[str, ContinuityDateReadiness] = {}
    existing: dict[str, Path] = {}
    for trade_date in expected:
        path = spec.path_builder(lake_root, trade_date)
        if trade_date not in registered or not path.exists():
            statuses[trade_date] = _missing_status(spec, trade_date, path)
        else:
            existing[trade_date] = path
    statuses.update(_scan_existing(connection=connection, spec=spec, existing=existing))
    relation_mode = {
        "dc_member": "member_subset_index",
        "dc_daily": "daily_equals_index",
    }.get(dataset)
    if relation_mode is not None:
        for trade_date, source_path in existing.items():
            status = statuses[trade_date]
            if not status.ready:
                continue
            relation_failed_count, relation_samples = audit_raw_board_relation(
                connection,
                source_path=source_path,
                index_path=raw_dc_index_path(lake_root, trade_date),
                mode=relation_mode,
            )
            if relation_failed_count:
                statuses[trade_date] = replace(
                    status,
                    ready=False,
                    checks_passed=False,
                    reason=f"{dataset} same-day board relation check failed for {trade_date}",
                    failed_check_names=tuple(
                        dict.fromkeys((*status.failed_check_names, spec.check_name))
                    ),
                    summary={
                        **status.summary,
                        "failed_rules": [
                            *list(status.summary.get("failed_rules", ())),
                            "same_day_board_relation_integrity",
                        ],
                        "reason_code": "cross_dataset_code_set_mismatch",
                        "relation_failure_count": relation_failed_count,
                        "relation_failure_samples": list(relation_samples),
                    },
                )
    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=len(existing),
    )


def batch_raw_dc_index_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_dc_board_lake_readiness(dataset="dc_index", **kwargs)


def batch_raw_dc_member_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_dc_board_lake_readiness(dataset="dc_member", **kwargs)


def batch_raw_dc_daily_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_dc_board_lake_readiness(dataset="dc_daily", **kwargs)


__all__ = [
    "batch_dc_board_lake_readiness",
    "batch_raw_dc_daily_lake_readiness",
    "batch_raw_dc_index_lake_readiness",
    "batch_raw_dc_member_lake_readiness",
]
