"""Bounded DuckDB readiness for the board Silver partitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_quality import (
    SILVER_DC_QUALITY_SPECS,
    SilverQualitySpec,
)
from orchestrator.defs.asset_guards.dc_board_relations import audit_silver_board_relation
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import silver_dc_index_path


def _path_list(paths: Sequence[Path]) -> str:
    return ", ".join(duckdb_string(path) for path in paths)


def _missing_status(
    *,
    spec: SilverQualitySpec,
    trade_date: str,
    path: Path,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=f"silver {spec.dataset} file is missing for {trade_date}",
        missing_check_names=(spec.check_name,),
        missing_file_paths=(str(path),),
        summary={
            "dataset": spec.dataset,
            "file_path": str(path),
            "materialized": False,
        },
    )


def _scan_row_counts(connection, paths: Sequence[Path]) -> dict[str, int]:
    relation = (
        f"read_parquet([{_path_list(paths)}], "
        "hive_partitioning=false, filename=true)"
    )
    rows = connection.execute(
        f"""
        SELECT
            regexp_extract(filename, 'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})', 1),
            count(*)
        FROM {relation}
        GROUP BY 1
        """
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _schema_error(connection, paths: Sequence[Path], spec: SilverQualitySpec) -> tuple[bool, dict[str, object]]:
    relation = f"read_parquet([{_path_list(paths)}], hive_partitioning=false)"
    observed_rows = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    observed_columns = tuple(str(row[0]) for row in observed_rows)
    observed_types = {str(row[0]): str(row[1]).upper() for row in observed_rows}
    expected_columns = tuple(str(column.name) for column in spec.schema)
    expected_types = {str(column.name): str(column.type).upper() for column in spec.schema}
    type_mismatches = {
        column: {
            "expected": expected_types[column],
            "observed": observed_types.get(column),
        }
        for column in expected_columns
        if observed_types.get(column) != expected_types[column]
    }
    return (
        observed_columns != expected_columns or bool(type_mismatches),
        {
            "expected_columns": list(expected_columns),
            "observed_columns": list(observed_columns),
            "type_mismatches": type_mismatches,
        },
    )


def _scan_existing(
    *,
    connection,
    spec: SilverQualitySpec,
    existing: Mapping[str, Path],
) -> dict[str, ContinuityDateReadiness]:
    if not existing:
        return {}

    paths = tuple(existing.values())
    relation = (
        f"read_parquet([{_path_list(paths)}], "
        "hive_partitioning=false, filename=true)"
    )
    schema_failed, schema_summary = _schema_error(connection, paths, spec)
    row_counts = _scan_row_counts(connection, paths)
    expected_columns = tuple(str(column.name) for column in spec.schema)
    if any(
        column not in expected_columns
        for column in schema_summary["observed_columns"]
    ) or any(
        column not in schema_summary["observed_columns"]
        for column in expected_columns
    ):
        return {
            trade_date: ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"silver {spec.dataset} core checks failed for {trade_date}",
                failed_check_names=(spec.check_name,),
                summary={
                    "dataset": spec.dataset,
                    "file_path": str(path),
                    "checked_row_count": row_counts.get(trade_date, 0),
                    "failed_row_count": row_counts.get(trade_date, 0),
                    "failed_rules": ["schema_matches_contract"],
                    "schema": schema_summary,
                },
            )
            for trade_date, path in existing.items()
        }

    key_null_condition = " OR ".join(
        f"{column} IS NULL OR trim(CAST({column} AS VARCHAR)) = ''"
        for column in spec.key_columns
    )
    key_expr = ", ".join(spec.key_columns)
    stats_rows = connection.execute(
        f"""
        WITH source AS (
            SELECT *,
                regexp_extract(
                    filename,
                    'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})',
                    1
                ) AS source_trade_date
            FROM {relation}
        ),
        aggregate AS (
            SELECT
                source_trade_date,
                count(*) AS row_count,
                sum(CASE
                    WHEN trade_date IS NULL
                      OR CAST(trade_date AS DATE) <> try_cast(source_trade_date AS DATE)
                    THEN 1 ELSE 0 END
                ) AS date_mismatch_count,
                sum(CASE WHEN {key_null_condition} THEN 1 ELSE 0 END) AS null_key_count,
                sum(CASE WHEN NOT ({spec.identity_condition}) THEN 1 ELSE 0 END) AS identity_failed_count,
                sum(CASE WHEN {spec.numeric_condition} THEN 1 ELSE 0 END) AS numeric_failed_count
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
            ) duplicate_groups
            GROUP BY source_trade_date
        )
        SELECT
            aggregate.source_trade_date,
            aggregate.row_count,
            aggregate.date_mismatch_count,
            aggregate.null_key_count,
            coalesce(duplicates.duplicate_key_count, 0),
            aggregate.identity_failed_count,
            aggregate.numeric_failed_count
        FROM aggregate
        LEFT JOIN duplicates USING (source_trade_date)
        """
    ).fetchall()
    stats_by_date = {str(row[0]): tuple(int(value or 0) for value in row[1:]) for row in stats_rows}

    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date, path in existing.items():
        row = stats_by_date.get(trade_date)
        if row is None:
            row_count = row_counts.get(trade_date, 0)
            failed_rules = ["row_count_positive"] if row_count <= 0 else []
            if schema_failed:
                failed_rules.append("schema_matches_contract")
            if not failed_rules:
                failed_rules.append("partition_scan_observed")
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=f"silver {spec.dataset} core checks failed for {trade_date}",
                failed_check_names=(spec.check_name,),
                summary={
                    "dataset": spec.dataset,
                    "file_path": str(path),
                    "checked_row_count": row_count,
                    "failed_row_count": row_count,
                    "failed_rules": failed_rules,
                    "schema": schema_summary if schema_failed else None,
                },
            )
            continue

        (
            row_count,
            date_mismatch_count,
            null_key_count,
            duplicate_key_count,
            identity_failed_count,
            numeric_failed_count,
        ) = row
        failed_rules: list[str] = []
        if row_count <= 0:
            failed_rules.append("row_count_positive")
        if schema_failed:
            failed_rules.append("schema_matches_contract")
        if date_mismatch_count:
            failed_rules.append("trade_date_matches_partition")
        if null_key_count:
            failed_rules.append("business_key_non_null")
        if duplicate_key_count:
            failed_rules.append("business_key_unique")
        if identity_failed_count:
            failed_rules.append("dataset_identity_fields_legal")
        if numeric_failed_count:
            failed_rules.append("numeric_value_domain_legal")
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=not failed_rules,
            materialized=True,
            checks_passed=not failed_rules,
            reason=(
                f"silver {spec.dataset} ready for {trade_date}"
                if not failed_rules
                else f"silver {spec.dataset} core checks failed for {trade_date}"
            ),
            failed_check_names=(spec.check_name,) if failed_rules else (),
            summary={
                "dataset": spec.dataset,
                "file_path": str(path),
                "checked_row_count": row_count,
                "failed_row_count": (
                    date_mismatch_count
                    + null_key_count
                    + duplicate_key_count
                    + identity_failed_count
                    + numeric_failed_count
                ),
                "failed_rules": failed_rules,
                "schema": schema_summary if schema_failed else None,
            },
        )
    return statuses


def batch_silver_dc_board_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    dataset: str,
) -> ContinuityBatchReadiness:
    """Scan one Silver dataset over a bounded date window."""

    started_at = perf_counter()
    spec = SILVER_DC_QUALITY_SPECS[dataset]
    expected = tuple(str(value) for value in expected_trade_dates)
    registered = {str(value) for value in registered_trade_days}
    statuses: dict[str, ContinuityDateReadiness] = {}
    existing: dict[str, Path] = {}
    for trade_date in expected:
        path = spec.path_builder(lake_root, trade_date)
        if trade_date not in registered or not path.exists():
            statuses[trade_date] = _missing_status(
                spec=spec,
                trade_date=trade_date,
                path=path,
            )
        else:
            existing[trade_date] = path
    if existing:
        try:
            statuses.update(
                _scan_existing(connection=connection, spec=spec, existing=existing)
            )
            relation_mode = {
                "dc_member": "member_subset_index",
                "dc_daily": "index_subset_daily",
            }.get(dataset)
            if relation_mode is not None:
                for trade_date, source_path in existing.items():
                    status = statuses[trade_date]
                    if not status.ready:
                        continue
                    relation_failed_count, relation_samples = audit_silver_board_relation(
                        connection,
                        source_path=source_path,
                        index_path=silver_dc_index_path(lake_root, trade_date),
                        mode=relation_mode,
                    )
                    if relation_failed_count:
                        statuses[trade_date] = replace(
                            status,
                            ready=False,
                            checks_passed=False,
                            reason=f"silver {dataset} same-day board relation check failed for {trade_date}",
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
        except Exception as exc:
            for trade_date, path in existing.items():
                statuses[trade_date] = ContinuityDateReadiness(
                    trade_date=trade_date,
                    ready=False,
                    materialized=True,
                    checks_passed=False,
                    reason=f"silver {spec.dataset} readiness scan failed for {trade_date}",
                    failed_check_names=(spec.check_name,),
                    summary={
                        "dataset": spec.dataset,
                        "file_path": str(path),
                        "scan_error": str(exc)[:500],
                    },
                )
    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=len(existing),
    )


def batch_silver_dc_index_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_silver_dc_board_lake_readiness(dataset="dc_index", **kwargs)


def batch_silver_dc_member_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_silver_dc_board_lake_readiness(dataset="dc_member", **kwargs)


def batch_silver_dc_daily_lake_readiness(**kwargs) -> ContinuityBatchReadiness:
    return batch_silver_dc_board_lake_readiness(dataset="dc_daily", **kwargs)


__all__ = [
    "batch_silver_dc_board_lake_readiness",
    "batch_silver_dc_daily_lake_readiness",
    "batch_silver_dc_index_lake_readiness",
    "batch_silver_dc_member_lake_readiness",
]
