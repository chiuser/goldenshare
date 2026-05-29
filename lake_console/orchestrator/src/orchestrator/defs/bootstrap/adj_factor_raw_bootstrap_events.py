from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.adj_factor_silver_history import (
    TRADE_DATE_PARTITION_PATTERN,
    discover_adj_factor_raw_partition_keys,
)
from orchestrator.defs.bootstrap.source_method import BootstrapSourceMethod
from orchestrator.defs.checks.adj_factor_checks import ADJ_FACTOR_MIN_TRADE_DATE
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import raw_adj_factor_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    RAW_ADJ_FACTOR_ASSET_KEY,
    RAW_ADJ_FACTOR_CHECKS,
    AssetReadinessSpec,
    asset_readiness_status,
)


@dataclass(frozen=True)
class AdjFactorRawBootstrapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class AdjFactorRawBootstrapPartitionAudit:
    partition_key: str
    raw_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[AdjFactorRawBootstrapCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class AdjFactorRawBootstrapEventPlan:
    selected_partition_keys: tuple[str, ...]
    raw_partition_count: int
    registered_partition_count: int
    raw_only_partition_keys: tuple[str, ...]
    partition_only_keys: tuple[str, ...]
    partition_audits: tuple[AdjFactorRawBootstrapPartitionAudit, ...]

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)

    @property
    def planned_event_count(self) -> int:
        passed_count = len(self.partition_audits) - self.failed_partition_count
        return passed_count * (1 + len(RAW_ADJ_FACTOR_CHECKS))


@dataclass(frozen=True)
class AdjFactorRawBootstrapEventReport:
    plan: AdjFactorRawBootstrapEventPlan
    dry_run: bool
    reported_partition_keys: tuple[str, ...]
    skipped_ready_partition_keys: tuple[str, ...]
    reported_event_count: int


def plan_adj_factor_raw_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    strict_partition_alignment: bool = True,
    today: str | None = None,
) -> AdjFactorRawBootstrapEventPlan:
    raw_partition_keys = set(discover_adj_factor_raw_partition_keys(lake_root))
    registered_partition_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
    )

    if partition_keys is None:
        selected_partition_keys = tuple(sorted(raw_partition_keys))
        raw_only_partition_keys = tuple(sorted(raw_partition_keys - registered_partition_keys))
        partition_only_keys = tuple(sorted(registered_partition_keys - raw_partition_keys))
    else:
        selected_partition_keys = tuple(sorted(set(partition_keys)))
        invalid_partition_keys = tuple(
            key
            for key in selected_partition_keys
            if not TRADE_DATE_PARTITION_PATTERN.match(key)
        )
        if invalid_partition_keys:
            raise ValueError(f"Invalid trade_date partition keys: {invalid_partition_keys}")
        raw_only_partition_keys = tuple(
            key for key in selected_partition_keys if key not in registered_partition_keys
        )
        partition_only_keys = tuple(
            key for key in selected_partition_keys if key not in raw_partition_keys
        )

    if strict_partition_alignment and (raw_only_partition_keys or partition_only_keys):
        raise ValueError(
            "raw adj_factor partitions and registered cn_a_stock_current_trade_days "
            "partitions are not aligned: "
            f"raw_only={raw_only_partition_keys[:10]}, "
            f"partition_only={partition_only_keys[:10]}"
        )

    effective_today = today or datetime.now(CN_A_SENSOR_TIMEZONE).date().isoformat()
    audits = tuple(
        audit_adj_factor_raw_bootstrap_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            partition_key=partition_key,
            registered_partition_keys=registered_partition_keys,
            today=effective_today,
        )
        for partition_key in selected_partition_keys
    )
    return AdjFactorRawBootstrapEventPlan(
        selected_partition_keys=selected_partition_keys,
        raw_partition_count=len(raw_partition_keys),
        registered_partition_count=len(registered_partition_keys),
        raw_only_partition_keys=raw_only_partition_keys,
        partition_only_keys=partition_only_keys,
        partition_audits=audits,
    )


def report_adj_factor_raw_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    dry_run: bool = True,
    strict_partition_alignment: bool = True,
    skip_existing_ready: bool = True,
    today: str | None = None,
) -> AdjFactorRawBootstrapEventReport:
    plan = plan_adj_factor_raw_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        duckdb=duckdb,
        partition_keys=partition_keys,
        strict_partition_alignment=strict_partition_alignment,
        today=today,
    )
    failed_audits = tuple(audit for audit in plan.partition_audits if not audit.passed)
    if failed_audits:
        samples = {
            audit.partition_key: audit.failed_check_names for audit in failed_audits[:10]
        }
        raise ValueError(f"raw_tushare_adj_factor bootstrap audit failed: {samples}")

    if dry_run:
        return AdjFactorRawBootstrapEventReport(
            plan=plan,
            dry_run=True,
            reported_partition_keys=(),
            skipped_ready_partition_keys=(),
            reported_event_count=0,
        )

    reported_partition_keys = []
    skipped_ready_partition_keys = []
    reported_event_count = 0
    raw_readiness_spec = AssetReadinessSpec(
        RAW_ADJ_FACTOR_ASSET_KEY,
        RAW_ADJ_FACTOR_CHECKS,
    )
    for audit in plan.partition_audits:
        if skip_existing_ready:
            status = asset_readiness_status(
                instance,
                raw_readiness_spec,
                partition_key=audit.partition_key,
            )
            if status.ready:
                skipped_ready_partition_keys.append(audit.partition_key)
                continue

        reported_event_count += _report_partition_events(instance, audit)
        reported_partition_keys.append(audit.partition_key)

    return AdjFactorRawBootstrapEventReport(
        plan=plan,
        dry_run=False,
        reported_partition_keys=tuple(reported_partition_keys),
        skipped_ready_partition_keys=tuple(skipped_ready_partition_keys),
        reported_event_count=reported_event_count,
    )


def audit_adj_factor_raw_bootstrap_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    registered_partition_keys: set[str],
    today: str,
) -> AdjFactorRawBootstrapPartitionAudit:
    raw_path = raw_adj_factor_path(lake_root, partition_key)
    checks = []
    exists = raw_path.exists()
    checks.append(
        _check_audit(
            "raw_adj_factor_file_exists",
            exists,
            build_check_metadata(
                check_scope=CheckScope.FILE_EXISTS,
                file_path=raw_path,
                missing_file_paths=() if exists else (raw_path,),
                extra_metadata={"partition_key": partition_key, "exists": exists},
            ),
        )
    )
    if not exists:
        return AdjFactorRawBootstrapPartitionAudit(
            partition_key=partition_key,
            raw_file_path=raw_path,
            passed=False,
            row_count=None,
            observed_columns=(),
            checks=tuple(checks),
        )

    with duckdb.connect() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(raw_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        schema_rows = connection.execute(
            describe_parquet_query(raw_path, hive_partitioning=False)
        ).fetchall()
        observed_schema = {row[0]: row[1] for row in schema_rows}
        observed_columns = tuple(row[0] for row in schema_rows)

        checks.extend(
            _row_count_and_schema_checks(
                partition_key=partition_key,
                raw_path=raw_path,
                row_count=row_count,
                observed_schema=observed_schema,
                observed_columns=observed_columns,
            )
        )
        required_columns_present = all(
            column in observed_columns for column in ADJ_FACTOR_RAW_REQUIRED_COLUMNS
        )
        if required_columns_present:
            checks.extend(
                _content_checks(
                    connection=connection,
                    partition_key=partition_key,
                    raw_path=raw_path,
                )
            )
        else:
            checks.extend(
                _skipped_column_dependent_checks(
                    partition_key=partition_key,
                    raw_path=raw_path,
                )
            )

    checks.append(
        _partition_key_allowed_check(
            partition_key=partition_key,
            registered_partition_keys=registered_partition_keys,
            today=today,
        )
    )
    return AdjFactorRawBootstrapPartitionAudit(
        partition_key=partition_key,
        raw_file_path=raw_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=tuple(checks),
    )


def _row_count_and_schema_checks(
    *,
    partition_key: str,
    raw_path: Path,
    row_count: int,
    observed_schema: Mapping[str, str],
    observed_columns: tuple[str, ...],
) -> tuple[AdjFactorRawBootstrapCheckAudit, ...]:
    missing_columns = tuple(
        column for column in ADJ_FACTOR_RAW_REQUIRED_COLUMNS if column not in observed_columns
    )
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": observed_schema.get(column),
        }
        for column, expected_type in _expected_raw_schema().items()
        if observed_schema.get(column) != expected_type
    }
    return (
        _check_audit(
            "raw_adj_factor_row_count_positive",
            row_count > 0,
            build_check_metadata(
                check_scope=CheckScope.ROW_COUNT,
                checked_row_count=row_count,
                file_path=raw_path,
                extra_metadata={"partition_key": partition_key},
            ),
        ),
        _check_audit(
            "raw_adj_factor_schema_matches_tushare_contract",
            not missing_columns and not type_mismatches,
            build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                checked_row_count=row_count,
                file_path=raw_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "observed_schema": dict(observed_schema),
                    "expected_schema": _expected_raw_schema(),
                    "missing_columns": list(missing_columns),
                    "type_mismatches": type_mismatches,
                },
            ),
        ),
        _check_audit(
            "raw_adj_factor_required_columns",
            not missing_columns,
            build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                file_path=raw_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "observed_columns": list(observed_columns),
                    "required_columns": list(ADJ_FACTOR_RAW_REQUIRED_COLUMNS),
                    "missing_columns": list(missing_columns),
                },
            ),
        ),
    )


def _content_checks(
    *,
    connection,
    partition_key: str,
    raw_path: Path,
) -> tuple[AdjFactorRawBootstrapCheckAudit, ...]:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    trade_date_expression = (
        "CAST(try_strptime(trim(CAST(trade_date AS VARCHAR)), '%Y%m%d') AS DATE)"
    )
    mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(raw_path, hive_partitioning=False)}
            WHERE {trade_date_expression} IS NULL
               OR {trade_date_expression} != {partition_date}
            """
        ).fetchone()[0]
    )
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS duplicate_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(raw_path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    invalid_factor_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(raw_path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            """
        ).fetchone()[0]
    )
    return (
        _check_audit(
            "raw_adj_factor_partition_date_matches",
            mismatch_count == 0,
            build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                failed_row_count=mismatch_count,
                file_path=raw_path,
                extra_metadata={"partition_key": partition_key},
            ),
        ),
        _check_audit(
            "raw_adj_factor_unique_ts_code_trade_date",
            duplicate_count == 0,
            build_check_metadata(
                check_scope=CheckScope.KEY_UNIQUENESS,
                failed_row_count=duplicate_count,
                file_path=raw_path,
                extra_metadata={"partition_key": partition_key},
            ),
        ),
        _check_audit(
            "raw_adj_factor_positive_factor",
            invalid_factor_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=invalid_factor_count,
                file_path=raw_path,
                extra_metadata={"partition_key": partition_key},
            ),
        ),
    )


def _skipped_column_dependent_checks(
    *,
    partition_key: str,
    raw_path: Path,
) -> tuple[AdjFactorRawBootstrapCheckAudit, ...]:
    metadata = build_check_metadata(
        check_scope=CheckScope.SCHEMA,
        file_path=raw_path,
        extra_metadata={
            "partition_key": partition_key,
            "not_evaluated_reason": "required_columns_missing",
        },
    )
    return (
        _check_audit("raw_adj_factor_partition_date_matches", False, metadata),
        _check_audit("raw_adj_factor_unique_ts_code_trade_date", False, metadata),
        _check_audit("raw_adj_factor_positive_factor", False, metadata),
    )


def _partition_key_allowed_check(
    *,
    partition_key: str,
    registered_partition_keys: set[str],
    today: str,
) -> AdjFactorRawBootstrapCheckAudit:
    is_registered = partition_key in registered_partition_keys
    is_not_before_start = partition_key >= ADJ_FACTOR_MIN_TRADE_DATE
    is_not_future = partition_key <= today
    return _check_audit(
        "raw_adj_factor_stock_current_partition_key_allowed",
        is_registered and is_not_before_start and is_not_future,
        build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "partition_key": partition_key,
                "partition_set": cn_a_stock_current_trade_days.name,
                "is_registered": is_registered,
                "min_trade_date": ADJ_FACTOR_MIN_TRADE_DATE,
                "is_not_before_start": is_not_before_start,
                "today": today,
                "is_not_future": is_not_future,
            },
        ),
    )


def _report_partition_events(
    instance: dg.DagsterInstance,
    audit: AdjFactorRawBootstrapPartitionAudit,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=RAW_ADJ_FACTOR_ASSET_KEY,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.raw_file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value,
                    "bootstrap_event_backfill": True,
                    "partition_key": audit.partition_key,
                },
            ),
        )
    )
    materialization = _latest_raw_materialization(instance, audit.partition_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=RAW_ADJ_FACTOR_ASSET_KEY,
                check_name=check.check_name,
                passed=check.passed,
                metadata=check.metadata,
                blocking=True,
                partition=audit.partition_key,
                target_materialization_data=target,
            )
        )
        event_count += 1
    return event_count


def _latest_raw_materialization(
    instance: dg.DagsterInstance,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=RAW_ADJ_FACTOR_ASSET_KEY,
            asset_partitions=[partition_key],
        ),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(
            "Expected raw_tushare_adj_factor materialization after runless report."
        )
    return result.records[0]


def _check_audit(
    check_name: str,
    passed: bool,
    metadata: Mapping[str, Any],
) -> AdjFactorRawBootstrapCheckAudit:
    return AdjFactorRawBootstrapCheckAudit(
        check_name=check_name,
        passed=passed,
        metadata=metadata,
    )


def _expected_raw_schema() -> dict[str, str]:
    return {
        "ts_code": "VARCHAR",
        "trade_date": "VARCHAR",
        "adj_factor": "DOUBLE",
    }
