"""Bounded runless event planning and reporting for the stock nine-turn bootstrap."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.stk_nineturn_lake_readiness import (
    batch_raw_stk_nineturn_lake_readiness,
    batch_silver_stock_nineturn_daily_lake_readiness,
)
from orchestrator.defs.bootstrap.stk_nineturn_history import (
    StkNineturnProdExportManifest,
)
from orchestrator.defs.catalog.lake_assets import (
    RAW_STK_NINETURN_CHECKS,
    SILVER_STOCK_NINETURN_DAILY_CHECKS,
)
from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)


STK_NINETURN_RUNLESS_CHECK_WINDOW_SIZE = 20
RAW_STK_NINETURN_ASSET_KEY = dg.AssetKey("raw_tushare_stk_nineturn")
SILVER_STOCK_NINETURN_DAILY_ASSET_KEY = dg.AssetKey(
    "silver_stock_nineturn_daily"
)
_RAW_CHECKS = tuple(RAW_STK_NINETURN_CHECKS)
_SILVER_CHECKS = tuple(SILVER_STOCK_NINETURN_DAILY_CHECKS)
_CHECK_HISTORY_LIMIT = 100


@dataclass(frozen=True, slots=True)
class StkNineturnPartitionAudit:
    asset_key: str
    partition_key: str
    file_path: Path
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...] = ()
    missing_check_names: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()
    summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", dict(self.summary))

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["file_path"] = str(self.file_path)
        payload["failed_check_names"] = list(self.failed_check_names)
        payload["missing_check_names"] = list(self.missing_check_names)
        payload["missing_file_paths"] = list(self.missing_file_paths)
        return payload


@dataclass(frozen=True, slots=True)
class StkNineturnRunlessEventPlan:
    raw_materialization_partition_keys: tuple[str, ...]
    silver_materialization_partition_keys: tuple[str, ...]
    raw_check_partition_keys: tuple[str, ...]
    silver_check_partition_keys: tuple[str, ...]
    existing_raw_materialized_partition_keys: tuple[str, ...]
    existing_silver_materialized_partition_keys: tuple[str, ...]
    existing_raw_ready_check_partition_keys: tuple[str, ...]
    existing_silver_ready_check_partition_keys: tuple[str, ...]
    existing_raw_passed_check_keys: tuple[tuple[str, str], ...]
    existing_silver_passed_check_keys: tuple[tuple[str, str], ...]
    failed_raw_partition_keys: tuple[str, ...]
    failed_silver_partition_keys: tuple[str, ...]
    raw_row_counts: tuple[tuple[str, int], ...]
    silver_row_counts: tuple[tuple[str, int], ...]
    sample_partition_audits: tuple[StkNineturnPartitionAudit, ...]
    planned_materialization_event_count: int
    planned_check_event_count: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "raw_materialization_partition_keys",
            "silver_materialization_partition_keys",
            "raw_check_partition_keys",
            "silver_check_partition_keys",
            "existing_raw_materialized_partition_keys",
            "existing_silver_materialized_partition_keys",
            "existing_raw_ready_check_partition_keys",
            "existing_silver_ready_check_partition_keys",
            "failed_raw_partition_keys",
            "failed_silver_partition_keys",
        ):
            payload[field_name] = list(getattr(self, field_name))
        payload["existing_raw_passed_check_keys"] = [
            list(value) for value in self.existing_raw_passed_check_keys
        ]
        payload["existing_silver_passed_check_keys"] = [
            list(value) for value in self.existing_silver_passed_check_keys
        ]
        payload["raw_row_counts"] = {
            key: value for key, value in self.raw_row_counts
        }
        payload["silver_row_counts"] = {
            key: value for key, value in self.silver_row_counts
        }
        payload["sample_partition_audits"] = [
            audit.to_dict() for audit in self.sample_partition_audits
        ]
        payload["raw_materialization_partition_count"] = len(
            self.raw_materialization_partition_keys
        )
        payload["silver_materialization_partition_count"] = len(
            self.silver_materialization_partition_keys
        )
        payload["raw_check_partition_count"] = len(self.raw_check_partition_keys)
        payload["silver_check_partition_count"] = len(
            self.silver_check_partition_keys
        )
        return payload


@dataclass(frozen=True, slots=True)
class StkNineturnRunlessEventReport:
    plan: StkNineturnRunlessEventPlan
    dry_run: bool
    reported_raw_materialization_partition_keys: tuple[str, ...]
    reported_silver_materialization_partition_keys: tuple[str, ...]
    skipped_raw_materialization_partition_keys: tuple[str, ...]
    skipped_silver_materialization_partition_keys: tuple[str, ...]
    reported_raw_check_keys: tuple[tuple[str, str], ...]
    reported_silver_check_keys: tuple[tuple[str, str], ...]
    reported_event_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "reported_raw_materialization_partition_keys": list(
                self.reported_raw_materialization_partition_keys
            ),
            "reported_silver_materialization_partition_keys": list(
                self.reported_silver_materialization_partition_keys
            ),
            "skipped_raw_materialization_partition_keys": list(
                self.skipped_raw_materialization_partition_keys
            ),
            "skipped_silver_materialization_partition_keys": list(
                self.skipped_silver_materialization_partition_keys
            ),
            "reported_raw_check_keys": [list(value) for value in self.reported_raw_check_keys],
            "reported_silver_check_keys": [
                list(value) for value in self.reported_silver_check_keys
            ],
            "reported_event_count": self.reported_event_count,
            "plan": self.plan.to_dict(),
        }


def plan_stk_nineturn_runless_events(
    *,
    instance: dg.DagsterInstance,
    manifest: StkNineturnProdExportManifest,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    materialization_partition_keys: Sequence[str] | None = None,
    check_partition_keys: Sequence[str] | None = None,
    check_window_size: int = STK_NINETURN_RUNLESS_CHECK_WINDOW_SIZE,
) -> StkNineturnRunlessEventPlan:
    """Build a bounded, idempotent plan without writing Dagster events."""
    manifest_keys = _normalized_manifest_keys(manifest)
    if check_window_size <= 0:
        raise ValueError("check_window_size must be positive.")
    selected_materialization_keys = _select_keys(
        materialization_partition_keys,
        default=manifest_keys,
        field_name="materialization_partition_keys",
    )
    selected_check_keys = _select_keys(
        check_partition_keys,
        default=manifest_keys[-check_window_size:],
        field_name="check_partition_keys",
    )
    manifest_key_set = set(manifest_keys)
    if not set(selected_materialization_keys).issubset(manifest_key_set):
        raise ValueError("materialization_partition_keys must be a manifest subset.")
    if not set(selected_check_keys).issubset(manifest_key_set):
        raise ValueError("check_partition_keys must be a manifest subset.")
    if not set(selected_check_keys).issubset(selected_materialization_keys):
        raise ValueError(
            "check_partition_keys must be a subset of materialization_partition_keys."
        )

    registered = set(
        instance.get_dynamic_partitions(cn_a_stk_nineturn_trade_days.name)
    )
    missing_registered = sorted(
        set(selected_materialization_keys).union(selected_check_keys) - registered
    )
    if missing_registered:
        raise ValueError(
            "Nine-turn event scope contains unregistered trade dates: "
            f"{missing_registered[:10]}"
        )

    audit_keys = tuple(
        sorted(set(selected_materialization_keys).union(selected_check_keys))
    )
    with duckdb_resource.connect() as connection:
        raw_readiness = batch_raw_stk_nineturn_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=audit_keys,
            registered_trade_days=registered,
            full_semantics=True,
        )
        silver_readiness = batch_silver_stock_nineturn_daily_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=audit_keys,
            registered_trade_days=registered,
            full_semantics=True,
        )

    raw_failed = tuple(
        key for key in selected_materialization_keys
        if not raw_readiness.status_for_trade_date(key).ready
    )
    silver_failed = tuple(
        key for key in selected_materialization_keys
        if not silver_readiness.status_for_trade_date(key).ready
    )
    raw_materialized = instance.get_materialized_partitions(RAW_STK_NINETURN_ASSET_KEY)
    silver_materialized = instance.get_materialized_partitions(
        SILVER_STOCK_NINETURN_DAILY_ASSET_KEY
    )
    raw_materialization_records = _latest_materialization_records(
        instance, RAW_STK_NINETURN_ASSET_KEY, selected_materialization_keys
    )
    silver_materialization_records = _latest_materialization_records(
        instance, SILVER_STOCK_NINETURN_DAILY_ASSET_KEY, selected_materialization_keys
    )
    raw_passed_checks = _existing_passed_check_keys(
        instance=instance,
        asset_key=RAW_STK_NINETURN_ASSET_KEY,
        check_names=_RAW_CHECKS,
        partition_keys=selected_check_keys,
        materialization_records=raw_materialization_records,
    )
    silver_passed_checks = _existing_passed_check_keys(
        instance=instance,
        asset_key=SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
        check_names=_SILVER_CHECKS,
        partition_keys=selected_check_keys,
        materialization_records=silver_materialization_records,
    )
    raw_ready_check_partitions = _complete_check_partitions(
        raw_passed_checks, selected_check_keys, _RAW_CHECKS
    )
    silver_ready_check_partitions = _complete_check_partitions(
        silver_passed_checks, selected_check_keys, _SILVER_CHECKS
    )
    audits = _sample_audits(
        raw_readiness=raw_readiness,
        silver_readiness=silver_readiness,
        lake_root=lake_root,
        partition_keys=selected_check_keys,
    )
    planned_materialization_event_count = sum(
        key not in raw_materialized for key in selected_materialization_keys
    ) + sum(
        key not in silver_materialized for key in selected_materialization_keys
    )
    planned_check_event_count = sum(
        (key, check_name) not in raw_passed_checks
        for key in selected_check_keys
        for check_name in _RAW_CHECKS
    ) + sum(
        (key, check_name) not in silver_passed_checks
        for key in selected_check_keys
        for check_name in _SILVER_CHECKS
    )
    return StkNineturnRunlessEventPlan(
        raw_materialization_partition_keys=selected_materialization_keys,
        silver_materialization_partition_keys=selected_materialization_keys,
        raw_check_partition_keys=selected_check_keys,
        silver_check_partition_keys=selected_check_keys,
        existing_raw_materialized_partition_keys=tuple(
            key for key in selected_materialization_keys if key in raw_materialized
        ),
        existing_silver_materialized_partition_keys=tuple(
            key for key in selected_materialization_keys if key in silver_materialized
        ),
        existing_raw_ready_check_partition_keys=tuple(
            key for key in selected_check_keys if key in raw_ready_check_partitions
        ),
        existing_silver_ready_check_partition_keys=tuple(
            key for key in selected_check_keys if key in silver_ready_check_partitions
        ),
        existing_raw_passed_check_keys=tuple(sorted(raw_passed_checks)),
        existing_silver_passed_check_keys=tuple(sorted(silver_passed_checks)),
        failed_raw_partition_keys=raw_failed,
        failed_silver_partition_keys=silver_failed,
        raw_row_counts=tuple(
            sorted(
                (
                    key,
                    _status_row_count(raw_readiness.status_for_trade_date(key)),
                )
                for key in selected_materialization_keys
            )
        ),
        silver_row_counts=tuple(
            sorted(
                (
                    key,
                    _status_row_count(silver_readiness.status_for_trade_date(key)),
                )
                for key in selected_materialization_keys
            )
        ),
        sample_partition_audits=audits,
        planned_materialization_event_count=planned_materialization_event_count,
        planned_check_event_count=planned_check_event_count,
    )


def report_stk_nineturn_runless_events(
    *,
    instance: dg.DagsterInstance,
    manifest: StkNineturnProdExportManifest,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    materialization_partition_keys: Sequence[str] | None = None,
    check_partition_keys: Sequence[str] | None = None,
    check_window_size: int = STK_NINETURN_RUNLESS_CHECK_WINDOW_SIZE,
    history_audit_report_path: str | None = None,
    dry_run: bool = True,
    confirm_write: bool = False,
) -> StkNineturnRunlessEventReport:
    plan = plan_stk_nineturn_runless_events(
        instance=instance,
        manifest=manifest,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        materialization_partition_keys=materialization_partition_keys,
        check_partition_keys=check_partition_keys,
        check_window_size=check_window_size,
    )
    if not dry_run and not confirm_write:
        raise ValueError("Runless event reporting requires confirm_write=True.")
    if not dry_run and not history_audit_report_path:
        raise ValueError(
            "Runless event reporting requires history_audit_report_path."
        )
    if plan.failed_raw_partition_keys or plan.failed_silver_partition_keys:
        raise ValueError(
            "Nine-turn runless audit failed: "
            f"raw={plan.failed_raw_partition_keys}, "
            f"silver={plan.failed_silver_partition_keys}"
        )
    if dry_run:
        return _report(
            plan=plan,
            dry_run=True,
            reported_raw_materialization_partition_keys=(),
            reported_silver_materialization_partition_keys=(),
            skipped_raw_materialization_partition_keys=(),
            skipped_silver_materialization_partition_keys=(),
            reported_raw_check_keys=(),
            reported_silver_check_keys=(),
            reported_event_count=0,
        )

    raw_existing = set(plan.existing_raw_materialized_partition_keys)
    silver_existing = set(plan.existing_silver_materialized_partition_keys)
    reported_raw_materializations: list[str] = []
    reported_silver_materializations: list[str] = []
    skipped_raw_materializations: list[str] = []
    skipped_silver_materializations: list[str] = []
    reported_raw_checks: list[tuple[str, str]] = []
    reported_silver_checks: list[tuple[str, str]] = []
    event_count = 0

    for partition_key in plan.raw_materialization_partition_keys:
        if partition_key in raw_existing:
            skipped_raw_materializations.append(partition_key)
            continue
        event_count += _report_materialization(
            instance=instance,
            asset_key=RAW_STK_NINETURN_ASSET_KEY,
            partition_key=partition_key,
            path=raw_stk_nineturn_path(lake_root, partition_key),
            row_count=_audit_row_count(plan, RAW_STK_NINETURN_ASSET_KEY, partition_key),
            observed_columns=tuple(column.name for column in RAW_TUSHARE_STK_NINETURN_SCHEMA),
            event_backfill_scope="full_history",
            manifest=manifest,
            history_audit_report_path=history_audit_report_path,
        )
        reported_raw_materializations.append(partition_key)

    for partition_key in plan.silver_materialization_partition_keys:
        if partition_key in silver_existing:
            skipped_silver_materializations.append(partition_key)
            continue
        event_count += _report_materialization(
            instance=instance,
            asset_key=SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
            partition_key=partition_key,
            path=silver_stock_nineturn_daily_path(lake_root, partition_key),
            row_count=_audit_row_count(
                plan, SILVER_STOCK_NINETURN_DAILY_ASSET_KEY, partition_key
            ),
            observed_columns=tuple(
                column.name for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
            ),
            event_backfill_scope="full_history",
            manifest=manifest,
            history_audit_report_path=history_audit_report_path,
        )
        reported_silver_materializations.append(partition_key)

    raw_passed = set(plan.existing_raw_passed_check_keys)
    silver_passed = set(plan.existing_silver_passed_check_keys)
    for partition_key in plan.raw_check_partition_keys:
        materialization = _latest_materialization(
            instance, RAW_STK_NINETURN_ASSET_KEY, partition_key
        )
        if materialization is None:
            raise RuntimeError(f"Missing Raw materialization for {partition_key}.")
        for check_name in _RAW_CHECKS:
            check_key = (partition_key, check_name)
            if check_key in raw_passed:
                continue
            event_count += _report_check(
                instance=instance,
                asset_key=RAW_STK_NINETURN_ASSET_KEY,
                check_name=check_name,
                partition_key=partition_key,
                materialization=materialization,
                path=raw_stk_nineturn_path(lake_root, partition_key),
                status=_status_for(plan, RAW_STK_NINETURN_ASSET_KEY, partition_key),
                check_scope=_check_scope(check_name, _RAW_CHECKS),
                event_backfill_scope=(
                    "recent_20_trade_days"
                    if partition_key in plan.raw_check_partition_keys
                    else "full_history"
                ),
                manifest=manifest,
                history_audit_report_path=history_audit_report_path,
            )
            reported_raw_checks.append(check_key)

    for partition_key in plan.silver_check_partition_keys:
        materialization = _latest_materialization(
            instance, SILVER_STOCK_NINETURN_DAILY_ASSET_KEY, partition_key
        )
        if materialization is None:
            raise RuntimeError(f"Missing Silver materialization for {partition_key}.")
        for check_name in _SILVER_CHECKS:
            check_key = (partition_key, check_name)
            if check_key in silver_passed:
                continue
            event_count += _report_check(
                instance=instance,
                asset_key=SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
                check_name=check_name,
                partition_key=partition_key,
                materialization=materialization,
                path=silver_stock_nineturn_daily_path(lake_root, partition_key),
                status=_status_for(
                    plan, SILVER_STOCK_NINETURN_DAILY_ASSET_KEY, partition_key
                ),
                check_scope=_check_scope(check_name, _SILVER_CHECKS),
                event_backfill_scope="recent_20_trade_days",
                manifest=manifest,
                history_audit_report_path=history_audit_report_path,
            )
            reported_silver_checks.append(check_key)

    return _report(
        plan=plan,
        dry_run=False,
        reported_raw_materialization_partition_keys=tuple(reported_raw_materializations),
        reported_silver_materialization_partition_keys=tuple(reported_silver_materializations),
        skipped_raw_materialization_partition_keys=tuple(skipped_raw_materializations),
        skipped_silver_materialization_partition_keys=tuple(skipped_silver_materializations),
        reported_raw_check_keys=tuple(reported_raw_checks),
        reported_silver_check_keys=tuple(reported_silver_checks),
        reported_event_count=event_count,
    )


def _report(
    *,
    plan: StkNineturnRunlessEventPlan,
    dry_run: bool,
    reported_raw_materialization_partition_keys: tuple[str, ...],
    reported_silver_materialization_partition_keys: tuple[str, ...],
    skipped_raw_materialization_partition_keys: tuple[str, ...],
    skipped_silver_materialization_partition_keys: tuple[str, ...],
    reported_raw_check_keys: tuple[tuple[str, str], ...],
    reported_silver_check_keys: tuple[tuple[str, str], ...],
    reported_event_count: int,
) -> StkNineturnRunlessEventReport:
    return StkNineturnRunlessEventReport(
        plan=plan,
        dry_run=dry_run,
        reported_raw_materialization_partition_keys=(
            reported_raw_materialization_partition_keys
        ),
        reported_silver_materialization_partition_keys=(
            reported_silver_materialization_partition_keys
        ),
        skipped_raw_materialization_partition_keys=(
            skipped_raw_materialization_partition_keys
        ),
        skipped_silver_materialization_partition_keys=(
            skipped_silver_materialization_partition_keys
        ),
        reported_raw_check_keys=reported_raw_check_keys,
        reported_silver_check_keys=reported_silver_check_keys,
        reported_event_count=reported_event_count,
    )


def _normalized_manifest_keys(manifest: StkNineturnProdExportManifest) -> tuple[str, ...]:
    keys = tuple(sorted(str(key) for key in manifest.partition_keys))
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("manifest partition_keys must be non-empty and unique.")
    _validate_date_keys(keys, "manifest partition_keys")
    return keys


def _select_keys(
    selected: Sequence[str] | None,
    *,
    default: Sequence[str],
    field_name: str,
) -> tuple[str, ...]:
    keys = tuple(sorted(set(str(value) for value in (default if selected is None else selected))))
    if not keys:
        raise ValueError(f"{field_name} must not be empty.")
    _validate_date_keys(keys, field_name)
    return keys


def _validate_date_keys(keys: Sequence[str], field_name: str) -> None:
    for key in keys:
        try:
            date.fromisoformat(key)
        except ValueError as error:
            raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error


def _latest_materialization_records(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=list(partition_keys),
        ),
        limit=max(1, len(partition_keys)),
    )
    records = {}
    for record in result.records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and partition_key not in records:
            records[partition_key] = record
    return records


def _existing_passed_check_keys(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    check_names: Sequence[str],
    partition_keys: Sequence[str],
    materialization_records: Mapping[str, object],
) -> set[tuple[str, str]]:
    selected = set(partition_keys)
    passed: set[tuple[str, str]] = set()
    seen_target: set[tuple[str, str]] = set()
    latest_storage_ids = {
        partition_key: getattr(record, "storage_id", None)
        for partition_key, record in materialization_records.items()
    }
    for check_name in check_names:
        records = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset_key, check_name),
            limit=_CHECK_HISTORY_LIMIT,
        )
        for record in records:
            partition_key = getattr(record, "partition", None)
            if partition_key not in selected:
                continue
            event = getattr(record, "event", None)
            dagster_event = getattr(event, "dagster_event", None) if event else None
            evaluation = (
                getattr(dagster_event, "event_specific_data", None)
                if dagster_event
                else None
            )
            target = getattr(evaluation, "target_materialization_data", None)
            if target is None or target.storage_id != latest_storage_ids.get(partition_key):
                continue
            key = (partition_key, check_name)
            if key in seen_target:
                continue
            seen_target.add(key)
            if (
                getattr(record.status, "value", None) == "SUCCEEDED"
                and bool(getattr(evaluation, "blocking", False))
                and bool(getattr(evaluation, "passed", False))
            ):
                passed.add(key)
    return passed


def _complete_check_partitions(
    passed_keys: set[tuple[str, str]],
    partition_keys: Sequence[str],
    check_names: Sequence[str],
) -> set[str]:
    return {
        partition_key
        for partition_key in partition_keys
        if all((partition_key, check_name) in passed_keys for check_name in check_names)
    }


def _sample_audits(
    *,
    raw_readiness: ContinuityBatchReadiness,
    silver_readiness: ContinuityBatchReadiness,
    lake_root: Path,
    partition_keys: Sequence[str],
) -> tuple[StkNineturnPartitionAudit, ...]:
    audits: list[StkNineturnPartitionAudit] = []
    for partition_key in partition_keys:
        audits.append(
            _partition_audit(
                RAW_STK_NINETURN_ASSET_KEY,
                raw_readiness.status_for_trade_date(partition_key),
                raw_stk_nineturn_path(lake_root, partition_key),
            )
        )
        audits.append(
            _partition_audit(
                SILVER_STOCK_NINETURN_DAILY_ASSET_KEY,
                silver_readiness.status_for_trade_date(partition_key),
                silver_stock_nineturn_daily_path(lake_root, partition_key),
            )
        )
    return tuple(audits)


def _partition_audit(
    asset_key: dg.AssetKey,
    status: ContinuityDateReadiness,
    path: Path,
) -> StkNineturnPartitionAudit:
    return StkNineturnPartitionAudit(
        asset_key=asset_key.to_user_string(),
        partition_key=status.trade_date,
        file_path=path,
        ready=status.ready,
        materialized=status.materialized,
        checks_passed=status.checks_passed,
        reason=status.reason,
        failed_check_names=status.failed_check_names,
        missing_check_names=status.missing_check_names,
        missing_file_paths=status.missing_file_paths,
        summary=status.summary,
    )


def _status_for(
    plan: StkNineturnRunlessEventPlan,
    asset_key: dg.AssetKey,
    partition_key: str,
) -> StkNineturnPartitionAudit:
    for audit in plan.sample_partition_audits:
        if audit.asset_key == asset_key.to_user_string() and audit.partition_key == partition_key:
            return audit
    raise KeyError(f"Missing sampled readiness status for {asset_key}:{partition_key}")


def _audit_row_count(
    plan: StkNineturnRunlessEventPlan,
    asset_key: dg.AssetKey,
    partition_key: str,
) -> int:
    rows = (
        plan.raw_row_counts
        if asset_key == RAW_STK_NINETURN_ASSET_KEY
        else plan.silver_row_counts
    )
    return dict(rows).get(partition_key, 0)


def _report_materialization(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str,
    path: Path,
    row_count: int,
    observed_columns: Sequence[str],
    event_backfill_scope: str,
    manifest: StkNineturnProdExportManifest,
    history_audit_report_path: str | None,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_key,
            partition=partition_key,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=row_count,
                observed_columns=observed_columns,
                extra_metadata={
                    "source_method": "prod-raw-db",
                    "bootstrap_run_id": manifest.run_id,
                    "manifest_run_id": manifest.run_id,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": event_backfill_scope,
                    "history_audit_report_path": history_audit_report_path,
                    "partition_key": partition_key,
                },
            ),
        )
    )
    return 1


def _report_check(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    check_name: str,
    partition_key: str,
    materialization,
    path: Path,
    status: StkNineturnPartitionAudit,
    check_scope: CheckScope,
    event_backfill_scope: str,
    manifest: StkNineturnProdExportManifest,
    history_audit_report_path: str | None,
) -> int:
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=asset_key,
            check_name=check_name,
            passed=True,
            metadata=build_check_metadata(
                check_scope=check_scope,
                checked_row_count=_audit_row_count_from_audit(status),
                file_path=path,
                extra_metadata={
                    "source_method": "prod-raw-db",
                    "bootstrap_run_id": manifest.run_id,
                    "manifest_run_id": manifest.run_id,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": event_backfill_scope,
                    "history_audit_report_path": history_audit_report_path,
                    "partition_key": partition_key,
                    "failed_rule_names": list(status.failed_check_names),
                    "readiness_reason": status.reason,
                },
            ),
            blocking=True,
            partition=partition_key,
            target_materialization_data=target,
        )
    )
    return 1


def _audit_row_count_from_audit(audit: StkNineturnPartitionAudit) -> int:
    return int(audit.summary.get("row_count", audit.summary.get("output_row_count", 0)))


def _status_row_count(status: ContinuityDateReadiness) -> int:
    return int(status.summary.get("row_count", status.summary.get("output_row_count", 0)))


def _check_scope(check_name: str, check_names: Sequence[str]) -> CheckScope:
    return CheckScope.SCHEMA if check_name == check_names[0] else CheckScope.VALUE_SANITY


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
        limit=1,
    )
    return result.records[0] if result.records else None
