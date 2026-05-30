from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.source_method import BootstrapSourceMethod
from orchestrator.defs.bootstrap.specs.stk_mins import (
    BACKUP_STK_MINS_ROOT,
    STK_MINS_BOOTSTRAP_DATASET_KEYS,
    bootstrap_stk_mins_partition_to_raw,
    resolve_stk_mins_backup_partition_path,
    stk_mins_bootstrap_spec,
)
from orchestrator.defs.bootstrap.specs.stock_identity_map import (
    OLD_TUSHARE_LAKE_ROOT,
    bootstrap_stock_identity_map_to_silver,
    stock_identity_map_bootstrap_spec,
)
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STK_MINS_RAW_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_MINS_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


SAMPLE_PARTITION_KEYS = ("2009-01-05", "2017-08-29", "2026-05-07")
RAW_STK_MINS_ASSET_KEYS = {
    freq: dg.AssetKey(dataset_key)
    for freq, dataset_key in STK_MINS_BOOTSTRAP_DATASET_KEYS.items()
}
SILVER_STOCK_IDENTITY_MAP_ASSET_KEY = dg.AssetKey("silver_stock_identity_map")

RAW_STK_MINS_CHECKS = (
    "raw_stk_mins_file_exists_and_row_count_positive",
    "raw_stk_mins_schema_matches_contract",
    "raw_stk_mins_freq_matches_asset",
    "raw_stk_mins_partition_date_matches",
    "raw_stk_mins_unique_ts_code_trade_time",
    "raw_stk_mins_price_volume_sanity",
    "raw_stk_mins_stock_mins_partition_key_registered",
)

SILVER_STOCK_IDENTITY_MAP_CHECKS = (
    "silver_stock_identity_map_file_exists_and_row_count_positive",
    "silver_stock_identity_map_schema_matches_contract",
    "silver_stock_identity_map_source_ts_code_present",
    "silver_stock_identity_map_source_ts_code_unique",
    "silver_stock_identity_map_latest_ts_code_present",
    "silver_stock_identity_map_known_identity_source",
    "silver_stock_identity_map_known_confidence",
    "silver_stock_identity_map_date_ranges_valid",
    "silver_stock_identity_map_conflicting_mapping_absent",
)

KNOWN_IDENTITY_SOURCES = ("stock_basic", "bse_mapping", "namechange")
KNOWN_IDENTITY_CONFIDENCE = ("confirmed", "inferred")


@dataclass(frozen=True)
class StkMinsMigrationPlan:
    partition_keys: tuple[str, ...]
    backup_partition_counts: Mapping[int, int]
    target_existing_counts: Mapping[int, int]
    backup_file_size_bytes: int
    target_filesystem_free_bytes: int
    planned_raw_file_count: int
    planned_raw_event_count: int
    identity_map_source_exists: bool
    identity_map_target_exists: bool


@dataclass(frozen=True)
class StkMinsRawMigrationReport:
    partition_keys: tuple[str, ...]
    written_files: tuple[Path, ...]
    skipped_existing_files: tuple[Path, ...]


@dataclass(frozen=True)
class StockMinsPartitionRegistrationReport:
    requested_partition_keys: tuple[str, ...]
    existing_partition_keys: tuple[str, ...]
    registered_partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsRawCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class StkMinsRawPartitionAudit:
    freq: int
    partition_key: str
    raw_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[StkMinsRawCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class StkMinsRawEventReport:
    dry_run: bool
    selected_partition_keys: tuple[str, ...]
    partition_audits: tuple[StkMinsRawPartitionAudit, ...]
    reported_asset_partitions: tuple[tuple[int, str], ...]
    skipped_ready_asset_partitions: tuple[tuple[int, str], ...]
    reported_event_count: int

    @property
    def failed_audit_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)


@dataclass(frozen=True)
class StockIdentityMapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class StockIdentityMapAudit:
    file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[StockIdentityMapCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class StockIdentityMapEventReport:
    dry_run: bool
    audit: StockIdentityMapAudit
    reported_event_count: int
    skipped_ready: bool


@dataclass(frozen=True)
class StkMinsFinalAuditReport:
    backup_partition_counts: Mapping[int, int]
    raw_partition_counts: Mapping[int, int]
    registered_partition_count: int
    raw_materialized_partition_counts: Mapping[int, int]
    raw_check_success_counts: Mapping[str, int]
    identity_map_materialized: bool
    identity_map_check_success_counts: Mapping[str, int]


def plan_stk_mins_migration(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    backup_root: Path = BACKUP_STK_MINS_ROOT,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
    partition_keys: Sequence[str] | None = None,
) -> StkMinsMigrationPlan:
    backup_by_freq = discover_backup_stk_mins_partitions(backup_root)
    _validate_backup_partition_alignment(backup_by_freq)

    selected_keys = _select_partition_keys(backup_by_freq, partition_keys)
    target_existing_counts = {
        freq: sum(
            1
            for partition_key in selected_keys
            if raw_stk_mins_path(lake_root, freq, partition_key).exists()
        )
        for freq in STK_MINS_FREQS
    }
    total_existing = sum(target_existing_counts.values())
    planned_raw_file_count = len(selected_keys) * len(STK_MINS_FREQS) - total_existing
    backup_size_bytes = _selected_backup_file_size_bytes(
        backup_root,
        selected_keys,
    )
    identity_spec = stock_identity_map_bootstrap_spec(
        lake_root=lake_root,
        old_lake_root=old_lake_root,
    )
    return StkMinsMigrationPlan(
        partition_keys=selected_keys,
        backup_partition_counts={
            freq: len(partitions) for freq, partitions in backup_by_freq.items()
        },
        target_existing_counts=target_existing_counts,
        backup_file_size_bytes=backup_size_bytes,
        target_filesystem_free_bytes=shutil.disk_usage(_disk_usage_path(lake_root)).free,
        planned_raw_file_count=planned_raw_file_count,
        planned_raw_event_count=len(selected_keys) * len(STK_MINS_FREQS) * (
            1 + len(RAW_STK_MINS_CHECKS)
        ),
        identity_map_source_exists=identity_spec.source_path.exists(),
        identity_map_target_exists=identity_spec.target_path.exists(),
    )


def discover_backup_stk_mins_partitions(
    backup_root: Path = BACKUP_STK_MINS_ROOT,
) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        freq_root = Path(backup_root) / f"freq={freq}"
        partition_keys = sorted(
            path.name.removeprefix("trade_date=")
            for path in freq_root.glob("trade_date=*")
            if path.is_dir()
        )
        partitions_by_freq[freq] = tuple(partition_keys)
    return partitions_by_freq


def discover_raw_stk_mins_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        raw_root = Path(lake_root) / "raw" / "tushare" / "stk_mins" / f"freq={freq}"
        partition_keys = sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in raw_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
        partitions_by_freq[freq] = tuple(partition_keys)
    return partitions_by_freq


def migrate_stk_mins_raw_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    backup_root: Path = BACKUP_STK_MINS_ROOT,
    partition_keys: Sequence[str],
    duckdb: DuckDBResource,
    skip_existing: bool = False,
    overwrite: bool = False,
) -> StkMinsRawMigrationReport:
    written_files: list[Path] = []
    skipped_existing_files: list[Path] = []
    for freq in STK_MINS_FREQS:
        spec = stk_mins_bootstrap_spec(
            freq,
            lake_root=lake_root,
            backup_root=backup_root,
        )
        for partition_key in partition_keys:
            target_path = spec.target_path(partition_key)
            if target_path.exists() and skip_existing:
                skipped_existing_files.append(target_path)
                continue
            bootstrap_stk_mins_partition_to_raw(
                spec,
                partition_key,
                duckdb,
                overwrite=overwrite,
            )
            written_files.append(target_path)
    return StkMinsRawMigrationReport(
        partition_keys=tuple(partition_keys),
        written_files=tuple(written_files),
        skipped_existing_files=tuple(skipped_existing_files),
    )


def migrate_stock_identity_map_snapshot(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
    duckdb: DuckDBResource,
    overwrite: bool = False,
) -> dict[str, Any]:
    spec = stock_identity_map_bootstrap_spec(
        lake_root=lake_root,
        old_lake_root=old_lake_root,
    )
    return bootstrap_stock_identity_map_to_silver(
        spec,
        duckdb,
        overwrite=overwrite,
    )


def register_stock_mins_partitions(
    *,
    instance: dg.DagsterInstance,
    partition_keys: Sequence[str],
) -> StockMinsPartitionRegistrationReport:
    requested_keys = tuple(sorted(set(partition_keys)))
    existing_keys = set(instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name))
    missing_keys = tuple(key for key in requested_keys if key not in existing_keys)
    if missing_keys:
        instance.add_dynamic_partitions(cn_a_stock_mins_trade_days.name, list(missing_keys))
    return StockMinsPartitionRegistrationReport(
        requested_partition_keys=requested_keys,
        existing_partition_keys=tuple(key for key in requested_keys if key in existing_keys),
        registered_partition_keys=missing_keys,
    )


def report_stk_mins_raw_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str],
    dry_run: bool = True,
    skip_existing_ready: bool = True,
) -> StkMinsRawEventReport:
    registered_keys = set(instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name))
    selected_keys = tuple(sorted(set(partition_keys)))
    audits = tuple(
        audit_stk_mins_raw_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
            partition_key=partition_key,
            registered_partition_keys=registered_keys,
        )
        for freq in STK_MINS_FREQS
        for partition_key in selected_keys
    )
    failed_audits = tuple(audit for audit in audits if not audit.passed)
    if failed_audits:
        samples = {
            f"{audit.freq}:{audit.partition_key}": audit.failed_check_names
            for audit in failed_audits[:10]
        }
        raise ValueError(f"stk_mins raw bootstrap audit failed: {samples}")

    if dry_run:
        return StkMinsRawEventReport(
            dry_run=True,
            selected_partition_keys=selected_keys,
            partition_audits=audits,
            reported_asset_partitions=(),
            skipped_ready_asset_partitions=(),
            reported_event_count=0,
        )

    materialized_sets = {
        freq: set(instance.get_materialized_partitions(asset_key))
        for freq, asset_key in RAW_STK_MINS_ASSET_KEYS.items()
    }
    reported: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    event_count = 0
    for audit in audits:
        if skip_existing_ready and audit.partition_key in materialized_sets[audit.freq]:
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    RAW_STK_MINS_ASSET_KEYS[audit.freq],
                    RAW_STK_MINS_CHECKS,
                ),
                partition_key=audit.partition_key,
            )
            if readiness.ready:
                skipped.append((audit.freq, audit.partition_key))
                continue

        event_count += _report_stk_mins_raw_partition_events(instance, audit)
        reported.append((audit.freq, audit.partition_key))

    return StkMinsRawEventReport(
        dry_run=False,
        selected_partition_keys=selected_keys,
        partition_audits=audits,
        reported_asset_partitions=tuple(reported),
        skipped_ready_asset_partitions=tuple(skipped),
        reported_event_count=event_count,
    )


def report_stock_identity_map_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    dry_run: bool = True,
    skip_existing_ready: bool = True,
) -> StockIdentityMapEventReport:
    audit = audit_stock_identity_map(lake_root=lake_root, duckdb=duckdb)
    if not audit.passed:
        raise ValueError(
            "silver_stock_identity_map bootstrap audit failed: "
            f"{audit.failed_check_names}"
        )
    if dry_run:
        return StockIdentityMapEventReport(
            dry_run=True,
            audit=audit,
            reported_event_count=0,
            skipped_ready=False,
        )
    if skip_existing_ready:
        readiness = asset_readiness_status(
            instance,
            AssetReadinessSpec(
                SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
                SILVER_STOCK_IDENTITY_MAP_CHECKS,
            ),
        )
        if readiness.ready:
            return StockIdentityMapEventReport(
                dry_run=False,
                audit=audit,
                reported_event_count=0,
                skipped_ready=True,
            )
    event_count = _report_stock_identity_map_events(instance, audit)
    return StockIdentityMapEventReport(
        dry_run=False,
        audit=audit,
        reported_event_count=event_count,
        skipped_ready=False,
    )


def audit_stk_mins_raw_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    freq: int,
    partition_key: str,
    registered_partition_keys: set[str],
) -> StkMinsRawPartitionAudit:
    normalized_freq = normalize_stk_mins_freq(freq)
    raw_path = raw_stk_mins_path(lake_root, normalized_freq, partition_key)
    checks: list[StkMinsRawCheckAudit] = []
    exists = raw_path.exists()
    if not exists:
        checks.append(
            _raw_check(
                "raw_stk_mins_file_exists_and_row_count_positive",
                False,
                build_check_metadata(
                    check_scope=CheckScope.FILE_EXISTS,
                    file_path=raw_path,
                    missing_file_paths=[raw_path],
                    extra_metadata={
                        "freq": normalized_freq,
                        "partition_key": partition_key,
                    },
                ),
            )
        )
        return StkMinsRawPartitionAudit(
            freq=normalized_freq,
            partition_key=partition_key,
            raw_file_path=raw_path,
            passed=False,
            row_count=None,
            observed_columns=(),
            checks=tuple(checks),
        )

    with duckdb.connect() as connection:
        row_count = int(
            connection.execute(count_parquet_query(raw_path, hive_partitioning=False)).fetchone()[0]
        )
        schema_rows = connection.execute(
            describe_parquet_query(raw_path, hive_partitioning=False)
        ).fetchall()
        observed_schema = {row[0]: row[1] for row in schema_rows}
        observed_columns = tuple(row[0] for row in schema_rows)
        checks.append(
            _raw_check(
                "raw_stk_mins_file_exists_and_row_count_positive",
                row_count > 0,
                build_check_metadata(
                    check_scope=CheckScope.ROW_COUNT,
                    checked_row_count=row_count,
                    file_path=raw_path,
                    extra_metadata={
                        "freq": normalized_freq,
                        "partition_key": partition_key,
                    },
                ),
            )
        )
        checks.append(
            _raw_schema_check(
                raw_path=raw_path,
                freq=normalized_freq,
                partition_key=partition_key,
                row_count=row_count,
                observed_schema=observed_schema,
            )
        )
        if set(STK_MINS_RAW_REQUIRED_COLUMNS).issubset(observed_columns):
            checks.extend(
                _raw_content_checks(
                    connection=connection,
                    raw_path=raw_path,
                    freq=normalized_freq,
                    partition_key=partition_key,
                )
            )
        else:
            checks.extend(_skipped_raw_content_checks(raw_path, normalized_freq, partition_key))

    checks.append(
        _raw_check(
            "raw_stk_mins_stock_mins_partition_key_registered",
            partition_key in registered_partition_keys,
            build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                file_path=raw_path,
                extra_metadata={
                    "freq": normalized_freq,
                    "partition_key": partition_key,
                    "partition_set": cn_a_stock_mins_trade_days.name,
                    "is_registered": partition_key in registered_partition_keys,
                },
            ),
        )
    )
    return StkMinsRawPartitionAudit(
        freq=normalized_freq,
        partition_key=partition_key,
        raw_file_path=raw_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=tuple(checks),
    )


def audit_stock_identity_map(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
) -> StockIdentityMapAudit:
    spec = stock_identity_map_bootstrap_spec(lake_root=lake_root)
    target_path = spec.target_path
    checks: list[StockIdentityMapCheckAudit] = []
    exists = target_path.exists()
    if not exists:
        checks.append(
            _identity_check(
                "silver_stock_identity_map_file_exists_and_row_count_positive",
                False,
                build_check_metadata(
                    check_scope=CheckScope.FILE_EXISTS,
                    file_path=target_path,
                    missing_file_paths=[target_path],
                ),
            )
        )
        return StockIdentityMapAudit(
            file_path=target_path,
            passed=False,
            row_count=None,
            observed_columns=(),
            checks=tuple(checks),
        )

    with duckdb.connect() as connection:
        row_count = int(
            connection.execute(count_parquet_query(target_path, hive_partitioning=False)).fetchone()[0]
        )
        schema_rows = connection.execute(
            describe_parquet_query(target_path, hive_partitioning=False)
        ).fetchall()
        observed_schema = {row[0]: row[1] for row in schema_rows}
        observed_columns = tuple(row[0] for row in schema_rows)
        checks.append(
            _identity_check(
                "silver_stock_identity_map_file_exists_and_row_count_positive",
                row_count > 0,
                build_check_metadata(
                    check_scope=CheckScope.ROW_COUNT,
                    checked_row_count=row_count,
                    file_path=target_path,
                ),
            )
        )
        checks.append(
            _identity_schema_check(
                target_path=target_path,
                row_count=row_count,
                observed_schema=observed_schema,
            )
        )
        if set(SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS).issubset(observed_columns):
            checks.extend(
                _identity_content_checks(
                    connection=connection,
                    target_path=target_path,
                )
            )
        else:
            checks.extend(_skipped_identity_content_checks(target_path))

    return StockIdentityMapAudit(
        file_path=target_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=tuple(checks),
    )


def audit_stk_mins_final_state(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    backup_root: Path,
) -> StkMinsFinalAuditReport:
    backup_partitions = discover_backup_stk_mins_partitions(backup_root)
    raw_partitions = discover_raw_stk_mins_partitions(lake_root)
    registered_partitions = instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name)
    raw_materialized_counts = {
        freq: len(instance.get_materialized_partitions(asset_key))
        for freq, asset_key in RAW_STK_MINS_ASSET_KEYS.items()
    }
    raw_check_success_counts: dict[str, int] = {}
    for freq, asset_key in RAW_STK_MINS_ASSET_KEYS.items():
        for check_name in RAW_STK_MINS_CHECKS:
            key = f"{asset_key.to_user_string()}:{check_name}"
            raw_check_success_counts[key] = _check_success_count(
                instance,
                dg.AssetCheckKey(asset_key, check_name),
            )
    identity_materialized = bool(
        instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=SILVER_STOCK_IDENTITY_MAP_ASSET_KEY),
            limit=1,
        ).records
    )
    identity_check_success_counts = {
        check_name: _check_success_count(
            instance,
            dg.AssetCheckKey(SILVER_STOCK_IDENTITY_MAP_ASSET_KEY, check_name),
        )
        for check_name in SILVER_STOCK_IDENTITY_MAP_CHECKS
    }
    return StkMinsFinalAuditReport(
        backup_partition_counts={
            freq: len(partitions) for freq, partitions in backup_partitions.items()
        },
        raw_partition_counts={
            freq: len(partitions) for freq, partitions in raw_partitions.items()
        },
        registered_partition_count=len(registered_partitions),
        raw_materialized_partition_counts=raw_materialized_counts,
        raw_check_success_counts=raw_check_success_counts,
        identity_map_materialized=identity_materialized,
        identity_map_check_success_counts=identity_check_success_counts,
    )


def all_backup_partition_keys(backup_root: Path = BACKUP_STK_MINS_ROOT) -> tuple[str, ...]:
    backup_by_freq = discover_backup_stk_mins_partitions(backup_root)
    _validate_backup_partition_alignment(backup_by_freq)
    return backup_by_freq[STK_MINS_FREQS[0]]


def all_raw_partition_keys(lake_root: Path = Path(DEFAULT_LAKE_ROOT)) -> tuple[str, ...]:
    raw_by_freq = discover_raw_stk_mins_partitions(lake_root)
    _validate_backup_partition_alignment(raw_by_freq)
    return raw_by_freq[STK_MINS_FREQS[0]]


def _validate_backup_partition_alignment(partitions_by_freq: Mapping[int, tuple[str, ...]]) -> None:
    expected = set(partitions_by_freq[STK_MINS_FREQS[0]])
    mismatches = {
        freq: {
            "missing_from_freq": sorted(expected - set(partitions)),
            "extra_in_freq": sorted(set(partitions) - expected),
        }
        for freq, partitions in partitions_by_freq.items()
        if set(partitions) != expected
    }
    if mismatches:
        raise ValueError(f"stk_mins partition sets are not aligned by freq: {mismatches}")


def _select_partition_keys(
    backup_by_freq: Mapping[int, tuple[str, ...]],
    partition_keys: Sequence[str] | None,
) -> tuple[str, ...]:
    all_keys = tuple(backup_by_freq[STK_MINS_FREQS[0]])
    if partition_keys is None:
        return all_keys
    requested = tuple(sorted(set(partition_keys)))
    missing = tuple(key for key in requested if key not in set(all_keys))
    if missing:
        raise ValueError(f"Requested stk_mins partitions are missing from backup: {missing}")
    return requested


def _selected_backup_file_size_bytes(
    backup_root: Path,
    partition_keys: Sequence[str],
) -> int:
    total_size = 0
    for freq in STK_MINS_FREQS:
        spec = stk_mins_bootstrap_spec(freq, backup_root=backup_root)
        for partition_key in partition_keys:
            total_size += resolve_stk_mins_backup_partition_path(
                spec,
                partition_key,
            ).stat().st_size
    return total_size


def _disk_usage_path(path: Path) -> Path:
    current = Path(path)
    while not current.exists():
        parent = current.parent
        if parent == current:
            return Path("/")
        current = parent
    return current


def _raw_schema_check(
    *,
    raw_path: Path,
    freq: int,
    partition_key: str,
    row_count: int,
    observed_schema: Mapping[str, str],
) -> StkMinsRawCheckAudit:
    expected_schema = _expected_schema(RAW_STK_MINS_SCHEMA)
    mismatches = {
        column: {"expected": expected_type, "observed": observed_schema.get(column)}
        for column, expected_type in expected_schema.items()
        if observed_schema.get(column) != expected_type
    }
    missing_columns = tuple(
        column for column in STK_MINS_RAW_REQUIRED_COLUMNS if column not in observed_schema
    )
    return _raw_check(
        "raw_stk_mins_schema_matches_contract",
        not mismatches and not missing_columns,
        build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            file_path=raw_path,
            extra_metadata={
                "freq": freq,
                "partition_key": partition_key,
                "expected_schema": expected_schema,
                "observed_schema": dict(observed_schema),
                "missing_columns": list(missing_columns),
                "mismatched_columns": mismatches,
            },
        ),
    )


def _raw_content_checks(
    *,
    connection,
    raw_path: Path,
    freq: int,
    partition_key: str,
) -> tuple[StkMinsRawCheckAudit, ...]:
    raw_table = read_parquet(raw_path, hive_partitioning=False)
    partition_date = f"DATE {duckdb_string(partition_key)}"
    freq_mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {raw_table}
            WHERE freq IS NULL OR freq != {freq}
            """
        ).fetchone()[0]
    )
    partition_mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {raw_table}
            WHERE trade_time IS NULL OR CAST(trade_time AS DATE) != {partition_date}
            """
        ).fetchone()[0]
    )
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_time
              FROM {raw_table}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    invalid_price_volume_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {raw_table}
            WHERE ts_code IS NULL OR trim(ts_code) = ''
               OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR vwap IS NULL
               OR open < 0 OR high < 0 OR low < 0 OR close < 0 OR vwap < 0
               OR vol IS NULL OR vol < 0
               OR amount IS NULL OR amount < 0
            """
        ).fetchone()[0]
    )
    return (
        _raw_check(
            "raw_stk_mins_freq_matches_asset",
            freq_mismatch_count == 0,
            build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                failed_row_count=freq_mismatch_count,
                file_path=raw_path,
                extra_metadata={"freq": freq, "partition_key": partition_key},
            ),
        ),
        _raw_check(
            "raw_stk_mins_partition_date_matches",
            partition_mismatch_count == 0,
            build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                failed_row_count=partition_mismatch_count,
                file_path=raw_path,
                extra_metadata={"freq": freq, "partition_key": partition_key},
            ),
        ),
        _raw_check(
            "raw_stk_mins_unique_ts_code_trade_time",
            duplicate_count == 0,
            build_check_metadata(
                check_scope=CheckScope.KEY_UNIQUENESS,
                failed_row_count=duplicate_count,
                file_path=raw_path,
                extra_metadata={"freq": freq, "partition_key": partition_key},
            ),
        ),
        _raw_check(
            "raw_stk_mins_price_volume_sanity",
            invalid_price_volume_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=invalid_price_volume_count,
                file_path=raw_path,
                extra_metadata={"freq": freq, "partition_key": partition_key},
            ),
        ),
    )


def _skipped_raw_content_checks(
    raw_path: Path,
    freq: int,
    partition_key: str,
) -> tuple[StkMinsRawCheckAudit, ...]:
    metadata = build_check_metadata(
        check_scope=CheckScope.SCHEMA,
        file_path=raw_path,
        extra_metadata={
            "freq": freq,
            "partition_key": partition_key,
            "not_evaluated_reason": "required_columns_missing",
        },
    )
    return (
        _raw_check("raw_stk_mins_freq_matches_asset", False, metadata),
        _raw_check("raw_stk_mins_partition_date_matches", False, metadata),
        _raw_check("raw_stk_mins_unique_ts_code_trade_time", False, metadata),
        _raw_check("raw_stk_mins_price_volume_sanity", False, metadata),
    )


def _identity_schema_check(
    *,
    target_path: Path,
    row_count: int,
    observed_schema: Mapping[str, str],
) -> StockIdentityMapCheckAudit:
    expected_schema = _expected_schema(SILVER_STOCK_IDENTITY_MAP_SCHEMA)
    mismatches = {
        column: {"expected": expected_type, "observed": observed_schema.get(column)}
        for column, expected_type in expected_schema.items()
        if observed_schema.get(column) != expected_type
    }
    missing_columns = tuple(
        column
        for column in SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS
        if column not in observed_schema
    )
    return _identity_check(
        "silver_stock_identity_map_schema_matches_contract",
        not mismatches and not missing_columns,
        build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            file_path=target_path,
            extra_metadata={
                "expected_schema": expected_schema,
                "observed_schema": dict(observed_schema),
                "missing_columns": list(missing_columns),
                "mismatched_columns": mismatches,
            },
        ),
    )


def _identity_content_checks(
    *,
    connection,
    target_path: Path,
) -> tuple[StockIdentityMapCheckAudit, ...]:
    table = read_parquet(target_path, hive_partitioning=False)
    source_missing_count = int(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE source_ts_code IS NULL OR trim(source_ts_code) = ''"
        ).fetchone()[0]
    )
    duplicate_source_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT source_ts_code
              FROM {table}
              GROUP BY source_ts_code
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    latest_missing_count = int(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE latest_ts_code IS NULL OR trim(latest_ts_code) = ''"
        ).fetchone()[0]
    )
    unknown_source_count = _not_in_count(
        connection,
        table,
        "identity_source",
        KNOWN_IDENTITY_SOURCES,
    )
    unknown_confidence_count = _not_in_count(
        connection,
        table,
        "confidence",
        KNOWN_IDENTITY_CONFIDENCE,
    )
    invalid_date_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {table}
            WHERE valid_from IS NULL
               OR effective_list_date IS NULL
               OR (valid_to IS NOT NULL AND valid_to < valid_from)
               OR (
                    effective_delist_date IS NOT NULL
                    AND effective_delist_date < effective_list_date
                  )
            """
        ).fetchone()[0]
    )
    conflicting_mapping_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT source_ts_code
              FROM {table}
              GROUP BY source_ts_code
              HAVING count(DISTINCT latest_ts_code) > 1
            ) conflict_keys
            """
        ).fetchone()[0]
    )
    return (
        _identity_check(
            "silver_stock_identity_map_source_ts_code_present",
            source_missing_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=source_missing_count,
                file_path=target_path,
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_source_ts_code_unique",
            duplicate_source_count == 0,
            build_check_metadata(
                check_scope=CheckScope.KEY_UNIQUENESS,
                failed_row_count=duplicate_source_count,
                file_path=target_path,
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_latest_ts_code_present",
            latest_missing_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=latest_missing_count,
                file_path=target_path,
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_known_identity_source",
            unknown_source_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=unknown_source_count,
                file_path=target_path,
                extra_metadata={"allowed_values": list(KNOWN_IDENTITY_SOURCES)},
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_known_confidence",
            unknown_confidence_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=unknown_confidence_count,
                file_path=target_path,
                extra_metadata={"allowed_values": list(KNOWN_IDENTITY_CONFIDENCE)},
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_date_ranges_valid",
            invalid_date_count == 0,
            build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                failed_row_count=invalid_date_count,
                file_path=target_path,
            ),
        ),
        _identity_check(
            "silver_stock_identity_map_conflicting_mapping_absent",
            conflicting_mapping_count == 0,
            build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                failed_row_count=conflicting_mapping_count,
                file_path=target_path,
            ),
        ),
    )


def _skipped_identity_content_checks(target_path: Path) -> tuple[StockIdentityMapCheckAudit, ...]:
    metadata = build_check_metadata(
        check_scope=CheckScope.SCHEMA,
        file_path=target_path,
        extra_metadata={"not_evaluated_reason": "required_columns_missing"},
    )
    return (
        _identity_check("silver_stock_identity_map_source_ts_code_present", False, metadata),
        _identity_check("silver_stock_identity_map_source_ts_code_unique", False, metadata),
        _identity_check("silver_stock_identity_map_latest_ts_code_present", False, metadata),
        _identity_check("silver_stock_identity_map_known_identity_source", False, metadata),
        _identity_check("silver_stock_identity_map_known_confidence", False, metadata),
        _identity_check("silver_stock_identity_map_date_ranges_valid", False, metadata),
        _identity_check("silver_stock_identity_map_conflicting_mapping_absent", False, metadata),
    )


def _report_stk_mins_raw_partition_events(
    instance: dg.DagsterInstance,
    audit: StkMinsRawPartitionAudit,
) -> int:
    asset_key = RAW_STK_MINS_ASSET_KEYS[audit.freq]
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_key,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.raw_file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value,
                    "bootstrap_event_backfill": True,
                    "freq": audit.freq,
                    "partition_key": audit.partition_key,
                },
            ),
        )
    )
    materialization = _latest_materialization(instance, asset_key, audit.partition_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
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


def _report_stock_identity_map_events(
    instance: dg.DagsterInstance,
    audit: StockIdentityMapAudit,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
            metadata=build_materialization_metadata(
                uri=audit.file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value,
                    "bootstrap_event_backfill": True,
                },
            ),
        )
    )
    materialization = _latest_materialization(
        instance,
        SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
        None,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
                check_name=check.check_name,
                passed=check.passed,
                metadata=check.metadata,
                blocking=True,
                target_materialization_data=target,
            )
        )
        event_count += 1
    return event_count


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str | None,
):
    if partition_key is None:
        result = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset_key),
            limit=1,
        )
    else:
        result = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=asset_key,
                asset_partitions=[partition_key],
            ),
            limit=1,
        )
    if not result.records:
        raise RuntimeError(f"Expected materialization after runless report: {asset_key}")
    return result.records[0]


def _check_success_count(
    instance: dg.DagsterInstance,
    check_key: dg.AssetCheckKey,
) -> int:
    records = instance.event_log_storage.get_asset_check_execution_history(
        check_key,
        limit=50000,
    )
    return sum(1 for record in records if record.status.value == "SUCCEEDED")


def _raw_check(
    check_name: str,
    passed: bool,
    metadata: Mapping[str, Any],
) -> StkMinsRawCheckAudit:
    return StkMinsRawCheckAudit(check_name=check_name, passed=passed, metadata=metadata)


def _identity_check(
    check_name: str,
    passed: bool,
    metadata: Mapping[str, Any],
) -> StockIdentityMapCheckAudit:
    return StockIdentityMapCheckAudit(check_name=check_name, passed=passed, metadata=metadata)


def _expected_schema(columns) -> dict[str, str]:
    return {column.name: column.type for column in columns}


def _not_in_count(connection, table: str, column: str, allowed_values: Sequence[str]) -> int:
    values = ", ".join(duckdb_string(value) for value in allowed_values)
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {table}
            WHERE {column} IS NULL OR {column} NOT IN ({values})
            """
        ).fetchone()[0]
    )
