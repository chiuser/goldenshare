"""Read-only planning and guarded apply for nine-turn dynamic partitions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from itertools import islice
from pathlib import Path
from time import perf_counter

import dagster as dg

from orchestrator.defs.asset_guards.stk_nineturn_lake_readiness import (
    batch_raw_stk_nineturn_lake_readiness,
    batch_silver_stock_nineturn_daily_lake_readiness,
)
from orchestrator.defs.bootstrap.stk_nineturn_events import (
    RAW_STK_NINETURN_ASSET_KEY,
    SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
)
from orchestrator.defs.catalog.lake_assets import (
    RAW_STK_NINETURN_CHECKS,
    SILVER_STOCK_NINETURN_DAILY_CHECKS,
)
from orchestrator.defs.partitions import (
    cn_a_stock_trade_days,
    cn_a_stk_nineturn_trade_days,
)
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_nineturn_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.stk_nineturn_contract import STK_NINETURN_HISTORY_START_DATE


STK_NINETURN_PARTITION_AUDIT_BATCH_SIZE = 60
STK_NINETURN_EVENT_HISTORY_LIMIT = 2_000
_ASSET_CHECKS = (
    (RAW_STK_NINETURN_ASSET_KEY, RAW_STK_NINETURN_CHECKS),
    (SILVER_STOCK_NINETURN_DAILY_ASSET_KEY, SILVER_STOCK_NINETURN_DAILY_CHECKS),
)


@dataclass(frozen=True, slots=True)
class StkNineturnCheckEventCompatibility:
    asset_key: str
    check_name: str
    record_count: int
    history_limit_reached: bool
    candidate_external_partition_count: int
    target_partition_mismatch_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StkNineturnEventCompatibility:
    raw_materialized_partition_count: int
    silver_materialized_partition_count: int
    materialized_partition_keys_outside_candidate: tuple[str, ...]
    check_reports: tuple[StkNineturnCheckEventCompatibility, ...]

    @property
    def stop_reasons(self) -> tuple[str, ...]:
        reasons = []
        if self.materialized_partition_keys_outside_candidate:
            reasons.append("materialized_partition_outside_candidate")
        if any(report.history_limit_reached for report in self.check_reports):
            reasons.append("asset_check_history_limit_reached")
        if any(
            report.candidate_external_partition_count > 0
            for report in self.check_reports
        ):
            reasons.append("asset_check_partition_outside_candidate")
        if any(
            report.target_partition_mismatch_count > 0
            for report in self.check_reports
        ):
            reasons.append("asset_check_target_partition_mismatch")
        return tuple(reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_materialized_partition_count": self.raw_materialized_partition_count,
            "silver_materialized_partition_count": (
                self.silver_materialized_partition_count
            ),
            "materialized_partition_keys_outside_candidate": list(
                self.materialized_partition_keys_outside_candidate
            ),
            "check_reports": [report.to_dict() for report in self.check_reports],
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StkNineturnPartitionMigrationPlan:
    candidate_partition_keys: tuple[str, ...]
    candidate_partition_hash: str
    raw_partition_keys: tuple[str, ...]
    silver_partition_keys: tuple[str, ...]
    candidate_missing_raw_keys: tuple[str, ...]
    candidate_missing_silver_keys: tuple[str, ...]
    raw_outside_candidate_keys: tuple[str, ...]
    silver_outside_candidate_keys: tuple[str, ...]
    existing_new_partition_keys: tuple[str, ...]
    existing_new_partition_keys_outside_candidate: tuple[str, ...]
    planned_partition_keys: tuple[str, ...]
    shared_stock_partition_keys_missing_candidate: tuple[str, ...]
    raw_readiness_failed_keys: tuple[str, ...]
    silver_readiness_failed_keys: tuple[str, ...]
    readiness_batch_size: int
    readiness_batch_count: int
    readiness_scanned_file_count: int
    readiness_elapsed_ms: int
    event_compatibility: StkNineturnEventCompatibility

    @property
    def stop_reasons(self) -> tuple[str, ...]:
        reasons = []
        if self.candidate_missing_raw_keys:
            reasons.append("candidate_missing_raw_files")
        if self.candidate_missing_silver_keys:
            reasons.append("candidate_missing_silver_files")
        if self.raw_outside_candidate_keys:
            reasons.append("raw_files_outside_candidate")
        if self.silver_outside_candidate_keys:
            reasons.append("silver_files_outside_candidate")
        if self.existing_new_partition_keys_outside_candidate:
            reasons.append("existing_new_partition_outside_candidate")
        if self.raw_readiness_failed_keys:
            reasons.append("raw_readiness_failed")
        if self.silver_readiness_failed_keys:
            reasons.append("silver_readiness_failed")
        reasons.extend(self.event_compatibility.stop_reasons)
        return tuple(reasons)

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_partition_count": len(self.candidate_partition_keys),
            "candidate_partition_keys": list(self.candidate_partition_keys),
            "candidate_partition_min": (
                self.candidate_partition_keys[0]
                if self.candidate_partition_keys
                else None
            ),
            "candidate_partition_max": (
                self.candidate_partition_keys[-1]
                if self.candidate_partition_keys
                else None
            ),
            "candidate_partition_hash": self.candidate_partition_hash,
            "raw_partition_count": len(self.raw_partition_keys),
            "silver_partition_count": len(self.silver_partition_keys),
            "candidate_missing_raw_keys": list(self.candidate_missing_raw_keys),
            "candidate_missing_silver_keys": list(self.candidate_missing_silver_keys),
            "raw_outside_candidate_keys": list(self.raw_outside_candidate_keys),
            "silver_outside_candidate_keys": list(self.silver_outside_candidate_keys),
            "existing_new_partition_count": len(self.existing_new_partition_keys),
            "existing_new_partition_keys": list(self.existing_new_partition_keys),
            "existing_new_partition_keys_outside_candidate": list(
                self.existing_new_partition_keys_outside_candidate
            ),
            "planned_partition_count": len(self.planned_partition_keys),
            "planned_partition_keys": list(self.planned_partition_keys),
            "shared_stock_partition_keys_missing_candidate": list(
                self.shared_stock_partition_keys_missing_candidate
            ),
            "raw_readiness_failed_keys": list(self.raw_readiness_failed_keys),
            "silver_readiness_failed_keys": list(
                self.silver_readiness_failed_keys
            ),
            "readiness_batch_size": self.readiness_batch_size,
            "readiness_batch_count": self.readiness_batch_count,
            "readiness_scanned_file_count": self.readiness_scanned_file_count,
            "readiness_elapsed_ms": self.readiness_elapsed_ms,
            "event_compatibility": self.event_compatibility.to_dict(),
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StkNineturnPartitionMigrationApplyReport:
    plan: StkNineturnPartitionMigrationPlan
    registered_partition_keys: tuple[str, ...]
    final_partition_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.to_dict(),
            "registered_partition_keys": list(self.registered_partition_keys),
            "registered_partition_count": len(self.registered_partition_keys),
            "final_partition_count": len(self.final_partition_keys),
        }


def plan_stk_nineturn_partition_migration(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> StkNineturnPartitionMigrationPlan:
    """Freeze the only allowed dynamic-partition migration input set."""
    started = perf_counter()
    candidate_keys = _load_candidate_partition_keys(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    if not candidate_keys:
        raise ValueError("Nine-turn candidate partition set must not be empty.")

    raw_keys = _discover_partition_keys(
        raw_stk_nineturn_path(lake_root, "2000-01-01").parent.parent
    )
    silver_keys = _discover_partition_keys(
        silver_stock_nineturn_daily_path(lake_root, "2000-01-01").parent.parent
    )
    candidate_set = set(candidate_keys)
    raw_set = set(raw_keys)
    silver_set = set(silver_keys)
    existing_new_keys = tuple(
        sorted(instance.get_dynamic_partitions(cn_a_stk_nineturn_trade_days.name))
    )
    shared_stock_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    )
    raw_failed, silver_failed, scanned_file_count, batch_count = _audit_lake_readiness(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        candidate_partition_keys=candidate_keys,
    )
    event_compatibility = audit_stk_nineturn_event_compatibility(
        instance=instance,
        candidate_partition_keys=candidate_keys,
    )
    elapsed_ms = int((perf_counter() - started) * 1000)
    return StkNineturnPartitionMigrationPlan(
        candidate_partition_keys=candidate_keys,
        candidate_partition_hash=_sorted_key_hash(candidate_keys),
        raw_partition_keys=raw_keys,
        silver_partition_keys=silver_keys,
        candidate_missing_raw_keys=tuple(sorted(candidate_set - raw_set)),
        candidate_missing_silver_keys=tuple(sorted(candidate_set - silver_set)),
        raw_outside_candidate_keys=tuple(sorted(raw_set - candidate_set)),
        silver_outside_candidate_keys=tuple(sorted(silver_set - candidate_set)),
        existing_new_partition_keys=existing_new_keys,
        existing_new_partition_keys_outside_candidate=tuple(
            sorted(set(existing_new_keys) - candidate_set)
        ),
        planned_partition_keys=tuple(
            key for key in candidate_keys if key not in set(existing_new_keys)
        ),
        shared_stock_partition_keys_missing_candidate=tuple(
            key for key in candidate_keys if key not in shared_stock_keys
        ),
        raw_readiness_failed_keys=raw_failed,
        silver_readiness_failed_keys=silver_failed,
        readiness_batch_size=STK_NINETURN_PARTITION_AUDIT_BATCH_SIZE,
        readiness_batch_count=batch_count,
        readiness_scanned_file_count=scanned_file_count,
        readiness_elapsed_ms=elapsed_ms,
        event_compatibility=event_compatibility,
    )


def apply_stk_nineturn_partition_migration(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    confirm_apply: bool = False,
) -> StkNineturnPartitionMigrationApplyReport:
    """Add only the fresh-plan delta after all read-only gates pass."""
    if not confirm_apply:
        raise ValueError("Dynamic partition apply requires confirm_apply=True.")
    plan = plan_stk_nineturn_partition_migration(
        instance=instance,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    if plan.should_stop:
        raise ValueError(
            "Nine-turn partition migration plan is not eligible for apply: "
            f"{', '.join(plan.stop_reasons)}"
        )
    if plan.planned_partition_keys:
        instance.add_dynamic_partitions(
            cn_a_stk_nineturn_trade_days.name,
            list(plan.planned_partition_keys),
        )
    final_keys = tuple(
        sorted(instance.get_dynamic_partitions(cn_a_stk_nineturn_trade_days.name))
    )
    expected_final = tuple(
        sorted(
            set(plan.existing_new_partition_keys)
            | set(plan.planned_partition_keys)
        )
    )
    if final_keys != expected_final:
        raise RuntimeError(
            "Nine-turn dynamic partition apply verification failed: "
            f"expected={len(expected_final)}, actual={len(final_keys)}"
        )
    return StkNineturnPartitionMigrationApplyReport(
        plan=plan,
        registered_partition_keys=plan.planned_partition_keys,
        final_partition_keys=final_keys,
    )


def audit_stk_nineturn_event_compatibility(
    *,
    instance: dg.DagsterInstance,
    candidate_partition_keys: Sequence[str],
) -> StkNineturnEventCompatibility:
    """Bounded API audit for historical event partition identity."""
    candidate_set = set(candidate_partition_keys)
    materialized_by_asset = {
        asset_key: set(instance.get_materialized_partitions(asset_key))
        for asset_key, _check_names in _ASSET_CHECKS
    }
    materialized_outside_candidate = tuple(
        sorted(
            {
                partition_key
                for partition_keys in materialized_by_asset.values()
                for partition_key in partition_keys
                if partition_key not in candidate_set
            }
        )
    )
    materialization_partition_by_storage_id = {
        asset_key: _materialization_partition_by_storage_id(
            instance=instance,
            asset_key=asset_key,
            candidate_partition_keys=candidate_partition_keys,
        )
        for asset_key, _check_names in _ASSET_CHECKS
    }
    check_reports = []
    for asset_key, check_names in _ASSET_CHECKS:
        for check_name in check_names:
            records = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(asset_key, check_name),
                limit=STK_NINETURN_EVENT_HISTORY_LIMIT,
            )
            candidate_external_count = 0
            target_mismatch_count = 0
            for record in records:
                partition_key = getattr(record, "partition", None)
                if partition_key not in candidate_set:
                    candidate_external_count += 1
                    continue
                target = _check_target_materialization(record)
                target_partition = materialization_partition_by_storage_id[
                    asset_key
                ].get(getattr(target, "storage_id", None))
                if target_partition != partition_key:
                    target_mismatch_count += 1
            check_reports.append(
                StkNineturnCheckEventCompatibility(
                    asset_key=asset_key.to_user_string(),
                    check_name=check_name,
                    record_count=len(records),
                    history_limit_reached=(
                        len(records) >= STK_NINETURN_EVENT_HISTORY_LIMIT
                    ),
                    candidate_external_partition_count=candidate_external_count,
                    target_partition_mismatch_count=target_mismatch_count,
                )
            )
    return StkNineturnEventCompatibility(
        raw_materialized_partition_count=len(
            materialized_by_asset[RAW_STK_NINETURN_ASSET_KEY]
        ),
        silver_materialized_partition_count=len(
            materialized_by_asset[SILVER_STOCK_NINETURN_DAILY_ASSET_KEY]
        ),
        materialized_partition_keys_outside_candidate=materialized_outside_candidate,
        check_reports=tuple(check_reports),
    )


def _load_candidate_partition_keys(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        raise FileNotFoundError(f"Missing silver trade calendar: {calendar_path}")
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            """
            SELECT CAST(trade_date AS VARCHAR) AS trade_date
            FROM read_parquet(?)
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date >= CAST(? AS DATE)
            ORDER BY trade_date
            """,
            [str(calendar_path), STK_NINETURN_HISTORY_START_DATE],
        ).fetchall()
    return _validated_partition_keys((str(row[0]) for row in rows), "candidate")


def _discover_partition_keys(dataset_root: Path) -> tuple[str, ...]:
    if not dataset_root.exists():
        return ()
    keys = []
    for path in dataset_root.glob("trade_date=*/part-000.parquet"):
        prefix, separator, value = path.parent.name.partition("=")
        if prefix != "trade_date" or not separator:
            continue
        keys.append(value)
    return _validated_partition_keys(keys, f"lake path {dataset_root}")


def _audit_lake_readiness(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    candidate_partition_keys: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], int, int]:
    raw_failed = []
    silver_failed = []
    scanned_file_count = 0
    batches = tuple(
        _chunked(candidate_partition_keys, STK_NINETURN_PARTITION_AUDIT_BATCH_SIZE)
    )
    with duckdb_resource.connect() as connection:
        for batch in batches:
            registered = set(batch)
            raw_readiness = batch_raw_stk_nineturn_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=batch,
                registered_trade_days=registered,
                full_semantics=True,
            )
            silver_readiness = batch_silver_stock_nineturn_daily_lake_readiness(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=batch,
                registered_trade_days=registered,
                full_semantics=True,
            )
            raw_failed.extend(
                key
                for key in batch
                if not raw_readiness.status_for_trade_date(key).ready
            )
            silver_failed.extend(
                key
                for key in batch
                if not silver_readiness.status_for_trade_date(key).ready
            )
            scanned_file_count += (
                raw_readiness.scanned_file_count
                + silver_readiness.scanned_file_count
            )
    return (
        tuple(sorted(raw_failed)),
        tuple(sorted(silver_failed)),
        scanned_file_count,
        len(batches),
    )


def _materialization_partition_by_storage_id(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    candidate_partition_keys: Sequence[str],
) -> dict[int, str]:
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=list(candidate_partition_keys),
        ),
        limit=STK_NINETURN_EVENT_HISTORY_LIMIT,
    )
    return {
        record.storage_id: record.partition_key
        for record in result.records
        if getattr(record, "storage_id", None) is not None
        and getattr(record, "partition_key", None) is not None
    }


def _check_target_materialization(record: object) -> object | None:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event else None
    evaluation = (
        getattr(dagster_event, "event_specific_data", None)
        if dagster_event is not None
        else None
    )
    return getattr(evaluation, "target_materialization_data", None)


def _chunked(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    iterator = iter(values)
    while batch := tuple(islice(iterator, size)):
        yield batch


def _validated_partition_keys(
    values: Iterable[str],
    label: str,
) -> tuple[str, ...]:
    keys = tuple(sorted(set(str(value) for value in values)))
    for key in keys:
        try:
            date.fromisoformat(key)
        except ValueError as error:
            raise ValueError(f"Invalid {label} partition key: {key!r}") from error
    return keys


def _sorted_key_hash(values: Sequence[str]) -> str:
    return sha256("\n".join(values).encode("utf-8")).hexdigest()
