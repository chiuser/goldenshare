from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.adj_factor import ADJ_FACTOR_SILVER_COLUMN_TYPES
from orchestrator.defs.bootstrap.adj_factor_silver_history import (
    TRADE_DATE_PARTITION_PATTERN,
    discover_adj_factor_silver_partition_keys,
)
from orchestrator.defs.bootstrap.source_method import BootstrapSourceMethod
from orchestrator.defs.checks.adj_factor_checks import ADJ_FACTOR_MIN_TRADE_DATE
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    SILVER_ADJ_FACTOR_ASSET_KEY,
    SILVER_ADJ_FACTOR_BLOCKING_CHECKS,
    AssetReadinessSpec,
    asset_readiness_status,
)


@dataclass(frozen=True)
class AdjFactorSilverBootstrapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class AdjFactorSilverBootstrapPartitionAudit:
    partition_key: str
    silver_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[AdjFactorSilverBootstrapCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class AdjFactorSilverBootstrapEventPlan:
    selected_partition_keys: tuple[str, ...]
    silver_partition_count: int
    registered_partition_count: int
    silver_only_partition_keys: tuple[str, ...]
    partition_only_keys: tuple[str, ...]
    partition_audits: tuple[AdjFactorSilverBootstrapPartitionAudit, ...]

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)

    @property
    def planned_event_count(self) -> int:
        passed_count = len(self.partition_audits) - self.failed_partition_count
        return passed_count * (1 + len(SILVER_ADJ_FACTOR_BLOCKING_CHECKS))


@dataclass(frozen=True)
class AdjFactorSilverBootstrapEventReport:
    plan: AdjFactorSilverBootstrapEventPlan
    dry_run: bool
    reported_partition_keys: tuple[str, ...]
    skipped_ready_partition_keys: tuple[str, ...]
    reported_event_count: int


def plan_adj_factor_silver_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    strict_partition_alignment: bool = True,
    today: str | None = None,
) -> AdjFactorSilverBootstrapEventPlan:
    silver_partition_keys = set(discover_adj_factor_silver_partition_keys(lake_root))
    registered_partition_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
    )

    if partition_keys is None:
        selected_partition_keys = tuple(sorted(silver_partition_keys))
        silver_only_partition_keys = tuple(
            sorted(silver_partition_keys - registered_partition_keys)
        )
        partition_only_keys = tuple(
            sorted(registered_partition_keys - silver_partition_keys)
        )
    else:
        selected_partition_keys = tuple(sorted(set(partition_keys)))
        invalid_partition_keys = tuple(
            key
            for key in selected_partition_keys
            if not TRADE_DATE_PARTITION_PATTERN.match(key)
        )
        if invalid_partition_keys:
            raise ValueError(f"Invalid trade_date partition keys: {invalid_partition_keys}")
        silver_only_partition_keys = tuple(
            key for key in selected_partition_keys if key not in registered_partition_keys
        )
        partition_only_keys = tuple(
            key for key in selected_partition_keys if key not in silver_partition_keys
        )

    if strict_partition_alignment and (silver_only_partition_keys or partition_only_keys):
        raise ValueError(
            "silver adj_factor partitions and registered cn_a_stock_current_trade_days "
            "partitions are not aligned: "
            f"silver_only={silver_only_partition_keys[:10]}, "
            f"partition_only={partition_only_keys[:10]}"
        )

    effective_today = today or datetime.now(CN_A_SENSOR_TIMEZONE).date().isoformat()
    audits = tuple(
        audit_adj_factor_silver_bootstrap_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            partition_key=partition_key,
            registered_partition_keys=registered_partition_keys,
            today=effective_today,
        )
        for partition_key in selected_partition_keys
    )
    return AdjFactorSilverBootstrapEventPlan(
        selected_partition_keys=selected_partition_keys,
        silver_partition_count=len(silver_partition_keys),
        registered_partition_count=len(registered_partition_keys),
        silver_only_partition_keys=silver_only_partition_keys,
        partition_only_keys=partition_only_keys,
        partition_audits=audits,
    )


def report_adj_factor_silver_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    dry_run: bool = True,
    strict_partition_alignment: bool = True,
    skip_existing_ready: bool = True,
    today: str | None = None,
) -> AdjFactorSilverBootstrapEventReport:
    plan = plan_adj_factor_silver_bootstrap_events(
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
        raise ValueError(f"silver_adj_factor bootstrap audit failed: {samples}")

    if dry_run:
        return AdjFactorSilverBootstrapEventReport(
            plan=plan,
            dry_run=True,
            reported_partition_keys=(),
            skipped_ready_partition_keys=(),
            reported_event_count=0,
        )

    reported_partition_keys = []
    skipped_ready_partition_keys = []
    reported_event_count = 0
    silver_readiness_spec = AssetReadinessSpec(
        SILVER_ADJ_FACTOR_ASSET_KEY,
        SILVER_ADJ_FACTOR_BLOCKING_CHECKS,
    )
    for audit in plan.partition_audits:
        if skip_existing_ready:
            status = asset_readiness_status(
                instance,
                silver_readiness_spec,
                partition_key=audit.partition_key,
            )
            if status.ready:
                skipped_ready_partition_keys.append(audit.partition_key)
                continue

        reported_event_count += _report_partition_events(instance, audit, lake_root)
        reported_partition_keys.append(audit.partition_key)

    return AdjFactorSilverBootstrapEventReport(
        plan=plan,
        dry_run=False,
        reported_partition_keys=tuple(reported_partition_keys),
        skipped_ready_partition_keys=tuple(skipped_ready_partition_keys),
        reported_event_count=reported_event_count,
    )


def audit_adj_factor_silver_bootstrap_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    registered_partition_keys: set[str],
    today: str,
) -> AdjFactorSilverBootstrapPartitionAudit:
    silver_path = silver_adj_factor_path(lake_root, partition_key)
    checks = []
    exists = silver_path.exists()
    checks.append(
        _check_audit(
            "silver_adj_factor_file_exists",
            exists,
            build_check_metadata(
                check_scope=CheckScope.FILE_EXISTS,
                file_path=silver_path,
                missing_file_paths=() if exists else (silver_path,),
                extra_metadata={"partition_key": partition_key, "exists": exists},
            ),
        )
    )
    if not exists:
        return AdjFactorSilverBootstrapPartitionAudit(
            partition_key=partition_key,
            silver_file_path=silver_path,
            passed=False,
            row_count=None,
            observed_columns=(),
            checks=tuple(checks),
        )

    basic_path = silver_stock_basic_path(lake_root)
    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(silver_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        schema_rows = connection.execute(
            describe_parquet_query(silver_path, hive_partitioning=False)
        ).fetchall()
        observed_schema = {row[0]: row[1] for row in schema_rows}
        observed_columns = tuple(row[0] for row in schema_rows)

        checks.append(_row_count_check(silver_path, partition_key, row_count))
        checks.append(
            _schema_check(
                silver_path=silver_path,
                partition_key=partition_key,
                observed_schema=observed_schema,
                row_count=row_count,
            )
        )
        checks.append(
            _required_columns_check(
                silver_path=silver_path,
                partition_key=partition_key,
                observed_columns=observed_columns,
            )
        )

        if (
            not checks[-2].passed
            or not checks[-1].passed
            or not set(ADJ_FACTOR_SILVER_REQUIRED_COLUMNS).issubset(observed_columns)
        ):
            return _partition_audit(partition_key, silver_path, row_count, observed_columns, checks)

        checks.extend(
            _partition_level_checks(
                connection=connection,
                silver_path=silver_path,
                partition_key=partition_key,
            )
        )
        if not basic_path.exists():
            checks.extend(_missing_stock_basic_checks(partition_key, silver_path, basic_path))
        else:
            checks.extend(
                _stock_basic_dependent_checks(
                    connection=connection,
                    silver_path=silver_path,
                    basic_path=basic_path,
                    partition_key=partition_key,
                )
            )

    checks.append(
        _partition_key_allowed_check(
            partition_key=partition_key,
            registered_partition_keys=registered_partition_keys,
            today=today,
        )
    )
    return _partition_audit(partition_key, silver_path, row_count, observed_columns, checks)


def _row_count_check(
    silver_path: Path,
    partition_key: str,
    row_count: int,
) -> AdjFactorSilverBootstrapCheckAudit:
    return _check_audit(
        "silver_adj_factor_row_count_positive",
        row_count > 0,
        build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            checked_row_count=row_count,
            file_path=silver_path,
            extra_metadata={"partition_key": partition_key},
        ),
    )


def _schema_check(
    *,
    silver_path: Path,
    partition_key: str,
    observed_schema: Mapping[str, str],
    row_count: int,
) -> AdjFactorSilverBootstrapCheckAudit:
    mismatched_columns = {
        column: {
            "expected": expected_type,
            "observed": observed_schema.get(column),
        }
        for column, expected_type in ADJ_FACTOR_SILVER_COLUMN_TYPES.items()
        if observed_schema.get(column) != expected_type
    }
    return _check_audit(
        "silver_adj_factor_schema_matches_contract",
        not mismatched_columns,
        build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            file_path=silver_path,
            extra_metadata={
                "partition_key": partition_key,
                "observed_columns": list(observed_schema.keys()),
                "expected_schema": ADJ_FACTOR_SILVER_COLUMN_TYPES,
                "observed_schema": dict(observed_schema),
                "mismatched_columns": mismatched_columns,
            },
        ),
    )


def _required_columns_check(
    *,
    silver_path: Path,
    partition_key: str,
    observed_columns: tuple[str, ...],
) -> AdjFactorSilverBootstrapCheckAudit:
    missing_columns = [
        column
        for column in ADJ_FACTOR_SILVER_REQUIRED_COLUMNS
        if column not in observed_columns
    ]
    return _check_audit(
        "silver_adj_factor_required_columns",
        not missing_columns,
        build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=silver_path,
            extra_metadata={
                "partition_key": partition_key,
                "observed_columns": list(observed_columns),
                "required_columns": list(ADJ_FACTOR_SILVER_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


def _partition_level_checks(
    *,
    connection,
    silver_path: Path,
    partition_key: str,
) -> tuple[AdjFactorSilverBootstrapCheckAudit, ...]:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(silver_path, hive_partitioning=False)}
            WHERE trade_date IS NULL OR trade_date != {partition_date}
            """
        ).fetchone()[0]
    )
    mismatch_rows = connection.execute(
        f"""
        SELECT ts_code, trade_date, adj_factor
        FROM {read_parquet(silver_path, hive_partitioning=False)}
        WHERE trade_date IS NULL OR trade_date != {partition_date}
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS duplicate_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(silver_path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    duplicate_rows = connection.execute(
        f"""
        SELECT ts_code, trade_date, count(*) AS duplicate_count
        FROM {read_parquet(silver_path, hive_partitioning=False)}
        GROUP BY ts_code, trade_date
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    invalid_factor_count = int(
        connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(silver_path, hive_partitioning=False)}
            WHERE adj_factor IS NULL OR adj_factor <= 0
            """
        ).fetchone()[0]
    )
    invalid_factor_rows = connection.execute(
        f"""
        SELECT ts_code, trade_date, adj_factor
        FROM {read_parquet(silver_path, hive_partitioning=False)}
        WHERE adj_factor IS NULL OR adj_factor <= 0
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return (
        _check_audit(
            "silver_adj_factor_partition_date_matches",
            mismatch_count == 0,
            build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                failed_row_count=mismatch_count,
                file_path=silver_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "mismatch_sample_rows": _sample_dicts(
                        ["ts_code", "trade_date", "adj_factor"], mismatch_rows
                    ),
                },
            ),
        ),
        _check_audit(
            "silver_adj_factor_unique_ts_code_trade_date",
            duplicate_count == 0,
            build_check_metadata(
                check_scope=CheckScope.KEY_UNIQUENESS,
                failed_row_count=duplicate_count,
                file_path=silver_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "duplicate_sample_keys": _sample_dicts(
                        ["ts_code", "trade_date", "duplicate_count"], duplicate_rows
                    ),
                },
            ),
        ),
        _check_audit(
            "silver_adj_factor_positive_factor",
            invalid_factor_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=invalid_factor_count,
                file_path=silver_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "invalid_sample_rows": _sample_dicts(
                        ["ts_code", "trade_date", "adj_factor"], invalid_factor_rows
                    ),
                },
            ),
        ),
    )


def _stock_basic_dependent_checks(
    *,
    connection,
    silver_path: Path,
    basic_path: Path,
    partition_key: str,
) -> tuple[AdjFactorSilverBootstrapCheckAudit, ...]:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    invalid_listed_count = int(
        connection.execute(
            f"""
            WITH current_listed AS (
              SELECT DISTINCT ts_code, list_date
              FROM {read_parquet(basic_path, hive_partitioning=False)}
              WHERE list_status = 'L'
            )
            SELECT count(*) AS invalid_count
            FROM {read_parquet(silver_path, hive_partitioning=False)} adj
            LEFT JOIN current_listed
              ON adj.ts_code = current_listed.ts_code
            WHERE current_listed.ts_code IS NULL
               OR adj.trade_date < current_listed.list_date
            """
        ).fetchone()[0]
    )
    invalid_listed_rows = connection.execute(
        f"""
        WITH current_listed AS (
          SELECT DISTINCT ts_code, list_date
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
        )
        SELECT adj.ts_code, adj.trade_date, current_listed.list_date, adj.adj_factor
        FROM {read_parquet(silver_path, hive_partitioning=False)} adj
        LEFT JOIN current_listed
          ON adj.ts_code = current_listed.ts_code
        WHERE current_listed.ts_code IS NULL
           OR adj.trade_date < current_listed.list_date
        ORDER BY adj.ts_code, adj.trade_date
        LIMIT 10
        """
    ).fetchall()
    summary = connection.execute(
        f"""
        WITH expected AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
            AND list_date <= {partition_date}
        ),
        actual AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(silver_path, hive_partitioning=False)}
          WHERE trade_date = {partition_date}
        ),
        missing AS (
          SELECT expected.ts_code
          FROM expected
          LEFT JOIN actual USING (ts_code)
          WHERE actual.ts_code IS NULL
        ),
        unexpected AS (
          SELECT actual.ts_code
          FROM actual
          LEFT JOIN expected USING (ts_code)
          WHERE expected.ts_code IS NULL
        )
        SELECT
          (SELECT count(*) FROM expected) AS expected_code_count,
          (SELECT count(*) FROM actual) AS actual_code_count,
          (SELECT count(*) FROM missing) AS missing_code_count,
          (SELECT count(*) FROM unexpected) AS unexpected_code_count
        """
    ).fetchone()
    missing_rows = connection.execute(
        f"""
        WITH expected AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
            AND list_date <= {partition_date}
        ),
        actual AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(silver_path, hive_partitioning=False)}
          WHERE trade_date = {partition_date}
        )
        SELECT expected.ts_code
        FROM expected
        LEFT JOIN actual USING (ts_code)
        WHERE actual.ts_code IS NULL
        ORDER BY expected.ts_code
        LIMIT 10
        """
    ).fetchall()
    unexpected_rows = connection.execute(
        f"""
        WITH expected AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
            AND list_date <= {partition_date}
        ),
        actual AS (
          SELECT DISTINCT ts_code
          FROM {read_parquet(silver_path, hive_partitioning=False)}
          WHERE trade_date = {partition_date}
        )
        SELECT actual.ts_code
        FROM actual
        LEFT JOIN expected USING (ts_code)
        WHERE expected.ts_code IS NULL
        ORDER BY actual.ts_code
        LIMIT 10
        """
    ).fetchall()
    missing_count = int(summary[2])
    unexpected_count = int(summary[3])
    return (
        _check_audit(
            "silver_adj_factor_listed_stock_only",
            invalid_listed_count == 0,
            build_check_metadata(
                check_scope=CheckScope.REFERENTIAL_INTEGRITY,
                failed_row_count=invalid_listed_count,
                input_file_paths=[silver_path, basic_path],
                extra_metadata={
                    "partition_key": partition_key,
                    "invalid_sample_rows": _sample_dicts(
                        ["ts_code", "trade_date", "list_date", "adj_factor"],
                        invalid_listed_rows,
                    ),
                },
            ),
        ),
        _check_audit(
            "silver_adj_factor_coverage_complete",
            missing_count == 0 and unexpected_count == 0,
            build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                failed_row_count=missing_count + unexpected_count,
                input_file_paths=[silver_path, basic_path],
                extra_metadata={
                    "partition_key": partition_key,
                    "expected_code_count": int(summary[0]),
                    "actual_code_count": int(summary[1]),
                    "missing_code_count": missing_count,
                    "unexpected_code_count": unexpected_count,
                    "missing_code_samples": [row[0] for row in missing_rows],
                    "unexpected_code_samples": [row[0] for row in unexpected_rows],
                },
            ),
        ),
    )


def _missing_stock_basic_checks(
    partition_key: str,
    silver_path: Path,
    basic_path: Path,
) -> tuple[AdjFactorSilverBootstrapCheckAudit, ...]:
    metadata = build_check_metadata(
        check_scope=CheckScope.FILE_EXISTS,
        input_file_paths=[silver_path],
        missing_file_paths=[basic_path],
        extra_metadata={
            "partition_key": partition_key,
            "missing_input_file": True,
        },
    )
    return (
        _check_audit("silver_adj_factor_listed_stock_only", False, metadata),
        _check_audit("silver_adj_factor_coverage_complete", False, metadata),
    )


def _partition_key_allowed_check(
    *,
    partition_key: str,
    registered_partition_keys: set[str],
    today: str,
) -> AdjFactorSilverBootstrapCheckAudit:
    is_registered = partition_key in registered_partition_keys
    is_not_before_start = partition_key >= ADJ_FACTOR_MIN_TRADE_DATE
    is_not_future = partition_key <= today
    return _check_audit(
        "silver_adj_factor_stock_current_partition_key_allowed",
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
    audit: AdjFactorSilverBootstrapPartitionAudit,
    lake_root: Path,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=SILVER_ADJ_FACTOR_ASSET_KEY,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.silver_file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value,
                    "bootstrap_event_backfill": True,
                    "partition_key": audit.partition_key,
                    "raw_file_path": str(raw_adj_factor_path(lake_root, audit.partition_key)),
                    "stock_basic_file_path": str(silver_stock_basic_path(lake_root)),
                },
            ),
        )
    )
    materialization = _latest_silver_materialization(instance, audit.partition_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=SILVER_ADJ_FACTOR_ASSET_KEY,
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


def _latest_silver_materialization(
    instance: dg.DagsterInstance,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=SILVER_ADJ_FACTOR_ASSET_KEY,
            asset_partitions=[partition_key],
        ),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(
            "Expected silver_adj_factor materialization after runless report."
        )
    return result.records[0]


def _partition_audit(
    partition_key: str,
    silver_path: Path,
    row_count: int,
    observed_columns: tuple[str, ...],
    checks: Sequence[AdjFactorSilverBootstrapCheckAudit],
) -> AdjFactorSilverBootstrapPartitionAudit:
    checks_tuple = tuple(checks)
    return AdjFactorSilverBootstrapPartitionAudit(
        partition_key=partition_key,
        silver_file_path=silver_path,
        passed=all(check.passed for check in checks_tuple),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=checks_tuple,
    )


def _check_audit(
    check_name: str,
    passed: bool,
    metadata: Mapping[str, Any],
) -> AdjFactorSilverBootstrapCheckAudit:
    return AdjFactorSilverBootstrapCheckAudit(
        check_name=check_name,
        passed=passed,
        metadata=metadata,
    )


def _sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples
