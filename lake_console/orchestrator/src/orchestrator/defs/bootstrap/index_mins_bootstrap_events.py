"""Bounded runless event backfill for the completed index_mins Bootstrap.

The Bootstrap writes are already complete.  This module only reconciles the
verified lake files with Dagster's partitioned materialization/check history:
all successful Raw/Silver files get materializations, while core checks are
limited to the latest twenty dedicated index-mins dates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_SOURCE_FREQS
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import AssetReadinessSpec, asset_readiness_status


INDEX_MINS_EVENT_WINDOW_SIZE = 20
INDEX_MINS_PARTITION_SET = cn_a_index_mins_trade_days.name
INDEX_MINS_RAW_FREQS = tuple(INDEX_MINS_SOURCE_FREQS)
INDEX_MINS_SILVER_FREQS = (1, 5, 15, 30, 60, 90, 120)

RAW_INDEX_MINS_ASSET_KEYS = {
    freq: dg.AssetKey(f"raw_index_mins_{freq.removesuffix('min')}m")
    for freq in INDEX_MINS_RAW_FREQS
}
SILVER_INDEX_MINS_ASSET_KEYS = {
    freq: dg.AssetKey(f"silver_index_mins_{freq}m")
    for freq in INDEX_MINS_SILVER_FREQS
}
RAW_INDEX_MINS_CHECK_NAMES = {
    freq: f"raw_index_mins_{freq.removesuffix('min')}m_core_check"
    for freq in INDEX_MINS_RAW_FREQS
}
SILVER_INDEX_MINS_CHECK_NAMES = {
    freq: f"silver_index_mins_{freq}m_core_check"
    for freq in INDEX_MINS_SILVER_FREQS
}


class IndexMinsEventPlanError(ValueError):
    """Raised when the frozen Bootstrap/event scope is not safe to use."""


@dataclass(frozen=True, slots=True)
class IndexMinsFileAudit:
    asset_key: str
    partition_key: str
    file_path: Path
    row_count: int
    layer: str
    frequency: str


@dataclass(frozen=True, slots=True)
class IndexMinsEventPlan:
    lake_root: Path
    reconciliation_report_path: Path
    date_plan_fingerprint: str
    expected_dates: tuple[str, ...]
    recent_check_dates: tuple[str, ...]
    files: tuple[IndexMinsFileAudit, ...]
    registered_partition_count: int
    missing_registered_dates: tuple[str, ...]
    existing_materializations: Mapping[str, tuple[str, ...]]
    existing_checks: Mapping[str, tuple[str, ...]]
    source_empty_raw_count: int
    precondition_errors: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors) or bool(self.missing_registered_dates)

    @property
    def planned_materialization_count(self) -> int:
        return sum(
            audit.partition_key not in set(self.existing_materializations.get(audit.asset_key, ()))
            for audit in self.files
        )

    @property
    def planned_check_count(self) -> int:
        recent = set(self.recent_check_dates)
        return sum(
            audit.partition_key in recent
            and audit.partition_key not in set(self.existing_checks.get(audit.asset_key, ()))
            for audit in self.files
        )

    @property
    def planned_event_count(self) -> int:
        return self.planned_materialization_count + self.planned_check_count

    def to_dict(self) -> dict[str, object]:
        by_asset: dict[str, dict[str, int]] = {}
        for audit in self.files:
            counts = by_asset.setdefault(audit.asset_key, {"files": 0, "rows": 0})
            counts["files"] += 1
            counts["rows"] += audit.row_count
        return {
            "schema_version": 1,
            "lake_root": str(self.lake_root),
            "reconciliation_report_path": str(self.reconciliation_report_path),
            "partition_set": INDEX_MINS_PARTITION_SET,
            "date_plan_fingerprint": self.date_plan_fingerprint,
            "expected_date_count": len(self.expected_dates),
            "expected_start_date": self.expected_dates[0] if self.expected_dates else None,
            "expected_end_date": self.expected_dates[-1] if self.expected_dates else None,
            "recent_check_dates": list(self.recent_check_dates),
            "registered_partition_count": self.registered_partition_count,
            "missing_registered_count": len(self.missing_registered_dates),
            "missing_registered_samples": list(self.missing_registered_dates[:10]),
            "source_empty_raw_count": self.source_empty_raw_count,
            "asset_file_counts": by_asset,
            "existing_materialization_counts": {
                asset: len(dates) for asset, dates in self.existing_materializations.items()
            },
            "existing_check_counts": {
                asset: len(dates) for asset, dates in self.existing_checks.items()
            },
            "planned_materialization_event_count": self.planned_materialization_count,
            "planned_check_event_count": self.planned_check_count,
            "planned_event_count": self.planned_event_count,
            "precondition_errors": list(self.precondition_errors),
            "should_stop": self.should_stop,
        }


@dataclass(frozen=True, slots=True)
class IndexMinsEventReport:
    mode: str
    confirmed: bool
    plan: IndexMinsEventPlan
    registered_partition_count: int = 0
    reported_materialization_count: int = 0
    reported_check_count: int = 0
    skipped_materialization_count: int = 0
    skipped_check_count: int = 0
    scan_elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "confirmed": self.confirmed,
            "registered_partition_count": self.registered_partition_count,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "reported_event_count": self.reported_materialization_count + self.reported_check_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "scan_elapsed_ms": round(self.scan_elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def _load_reconciliation_report(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise IndexMinsEventPlanError(f"missing P7 reconciliation report: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexMinsEventPlanError(f"invalid P7 reconciliation report: {path}") from exc
    if report.get("should_stop") is not False:
        raise IndexMinsEventPlanError("P7 reconciliation report is not green")
    date_plan = report.get("date_plan")
    if not isinstance(date_plan, Mapping):
        raise IndexMinsEventPlanError("P7 reconciliation report has no date_plan")
    expected_dates = date_plan.get("expected_trade_dates")
    if not isinstance(expected_dates, list) or not expected_dates:
        raise IndexMinsEventPlanError("P7 date_plan has no expected trade dates")
    if not all(isinstance(value, str) for value in expected_dates):
        raise IndexMinsEventPlanError("P7 date_plan contains non-string dates")
    if date_plan.get("start_date") != expected_dates[0] or date_plan.get("end_date") != expected_dates[-1]:
        raise IndexMinsEventPlanError("P7 date_plan boundary does not match expected dates")
    if date_plan.get("expected_date_count") != len(expected_dates):
        raise IndexMinsEventPlanError("P7 date_plan count does not match expected dates")
    for layer in ("raw_audit", "silver_audit"):
        audit = report.get(layer)
        if not isinstance(audit, Mapping) or audit.get("missing_count") != 0 or audit.get("invalid_existing_count") != 0:
            raise IndexMinsEventPlanError(f"P7 {layer} is not a complete green audit")
    return report


def _row_counts(connection: Any, paths: Sequence[Path]) -> dict[str, int]:
    if not paths:
        return {}
    rows = connection.execute(
        """
        SELECT filename, count(*)
        FROM read_parquet(?, filename=true, hive_partitioning=false)
        GROUP BY filename
        """,
        [[str(path) for path in paths]],
    ).fetchall()
    return {str(Path(str(filename)).resolve()): int(count or 0) for filename, count in rows}


def _existing_ready_checks(
    instance: dg.DagsterInstance,
    *,
    asset_key: dg.AssetKey,
    check_name: str,
    dates: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        trade_date
        for trade_date in dates
        if asset_readiness_status(
            instance,
            AssetReadinessSpec(asset_key, (check_name,)),
            partition_key=trade_date,
        ).ready
    )


def _asset_specs() -> tuple[tuple[str, dg.AssetKey, str, str], ...]:
    return tuple(
        [
            ("raw", asset_key, freq, RAW_INDEX_MINS_CHECK_NAMES[freq])
            for freq, asset_key in RAW_INDEX_MINS_ASSET_KEYS.items()
        ]
        + [
            ("silver", asset_key, str(freq), SILVER_INDEX_MINS_CHECK_NAMES[freq])
            for freq, asset_key in SILVER_INDEX_MINS_ASSET_KEYS.items()
        ]
    )


def plan_index_mins_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    require_registered: bool = True,
) -> IndexMinsEventPlan:
    report = _load_reconciliation_report(reconciliation_report_path)
    expected_dates = tuple(str(value) for value in report["date_plan"]["expected_trade_dates"])
    recent_dates = expected_dates[-INDEX_MINS_EVENT_WINDOW_SIZE:]
    precondition_errors: list[str] = []
    files: list[IndexMinsFileAudit] = []
    source_empty_raw_count = 0
    raw_records = report.get("raw_records")
    silver_records = report.get("silver_records")
    if not isinstance(raw_records, list) or not isinstance(silver_records, list):
        raise IndexMinsEventPlanError("P7 report is missing raw_records or silver_records")

    raw_expected: set[tuple[str, str]] = set()
    for record in raw_records:
        if not isinstance(record, Mapping):
            raise IndexMinsEventPlanError("P7 raw_records contains a non-object")
        trade_date = str(record.get("partition_key") or record.get("trade_date") or "")
        if not trade_date:
            raise IndexMinsEventPlanError("P7 raw record has no partition/trade date")
        source_freq = str(record.get("source_freq"))
        key = (trade_date, source_freq)
        if key in raw_expected:
            raise IndexMinsEventPlanError(f"duplicate P7 raw record: {key}")
        raw_expected.add(key)
        if record.get("write_mode") == "source_empty_exempt":
            source_empty_raw_count += 1
            continue
        if source_freq not in RAW_INDEX_MINS_ASSET_KEYS:
            raise IndexMinsEventPlanError(f"unknown P7 raw frequency: {source_freq}")
        path = raw_index_mins_path(lake_root, source_freq, trade_date)
        if not path.is_file():
            precondition_errors.append(f"missing raw lake file: {path}")
        files.append(
            IndexMinsFileAudit(
                asset_key=RAW_INDEX_MINS_ASSET_KEYS[source_freq].to_user_string(),
                partition_key=trade_date,
                file_path=path,
                row_count=(
                    int(record["written_row_count"])
                    if record.get("written_row_count") is not None
                    else -1
                ),
                layer="raw",
                frequency=source_freq,
            )
        )

    silver_expected: set[tuple[str, str]] = set()
    for record in silver_records:
        if not isinstance(record, Mapping):
            raise IndexMinsEventPlanError("P7 silver_records contains a non-object")
        trade_date = str(record.get("partition_key") or record.get("trade_date") or "")
        if not trade_date:
            raise IndexMinsEventPlanError("P7 silver record has no partition/trade date")
        frequency = int(str(record.get("silver_freq", "")).removesuffix("min"))
        key = (trade_date, str(frequency))
        if key in silver_expected:
            raise IndexMinsEventPlanError(f"duplicate P7 silver record: {key}")
        silver_expected.add(key)
        if frequency not in SILVER_INDEX_MINS_ASSET_KEYS:
            raise IndexMinsEventPlanError(f"unknown P7 silver frequency: {frequency}")
        path = silver_index_mins_path(lake_root, frequency, trade_date)
        if not path.is_file():
            precondition_errors.append(f"missing silver lake file: {path}")
        files.append(
            IndexMinsFileAudit(
                asset_key=SILVER_INDEX_MINS_ASSET_KEYS[frequency].to_user_string(),
                partition_key=trade_date,
                file_path=path,
                row_count=(
                    int(record["written_row_count"])
                    if record.get("written_row_count") is not None
                    else -1
                ),
                layer="silver",
                frequency=str(frequency),
            )
        )

    expected_raw_count = len(expected_dates) * len(INDEX_MINS_RAW_FREQS)
    expected_silver_count = len(expected_dates) * len(INDEX_MINS_SILVER_FREQS)
    if len(raw_expected) != expected_raw_count:
        raise IndexMinsEventPlanError(
            f"P7 raw record count {len(raw_expected)} != expected logical count {expected_raw_count}"
        )
    if len(silver_expected) != expected_silver_count:
        raise IndexMinsEventPlanError(
            f"P7 silver record count {len(silver_expected)} != expected count {expected_silver_count}"
        )

    paths_by_asset: dict[str, list[Path]] = {}
    for audit in files:
        paths_by_asset.setdefault(audit.asset_key, []).append(audit.file_path)
    observed_counts: dict[str, int] = {}
    with duckdb_resource.connect() as connection:
        for asset_key, paths in paths_by_asset.items():
            observed_counts.update(_row_counts(connection, paths))
    for audit in files:
        observed = observed_counts.get(str(audit.file_path.resolve()), 0)
        if observed <= 0:
            precondition_errors.append(f"empty index_mins event target: {audit.file_path}")
        if audit.row_count >= 0 and observed != audit.row_count:
            precondition_errors.append(
                f"P7 row count mismatch for {audit.file_path}: report={audit.row_count}, lake={observed}"
            )

    files = [
        IndexMinsFileAudit(
            asset_key=audit.asset_key,
            partition_key=audit.partition_key,
            file_path=audit.file_path,
            row_count=observed_counts[str(audit.file_path.resolve())],
            layer=audit.layer,
            frequency=audit.frequency,
        )
        for audit in files
    ]

    registered = {str(value) for value in instance.get_dynamic_partitions(INDEX_MINS_PARTITION_SET)}
    missing_registered = tuple(sorted(set(expected_dates) - registered))
    if require_registered and missing_registered:
        precondition_errors.append(
            f"registered partition set is missing {len(missing_registered)} expected dates"
        )
    existing_materializations = {
        asset_key.to_user_string(): tuple(
            sorted(set(expected_dates) & set(instance.get_materialized_partitions(asset_key)))
        )
        for _, asset_key, _, _ in _asset_specs()
    }
    existing_checks = {
        asset_key.to_user_string(): _existing_ready_checks(
            instance,
            asset_key=asset_key,
            check_name=check_name,
            dates=recent_dates,
        )
        for _, asset_key, _, check_name in _asset_specs()
    }
    return IndexMinsEventPlan(
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        date_plan_fingerprint=str(report["date_plan"].get("fingerprint")),
        expected_dates=expected_dates,
        recent_check_dates=recent_dates,
        files=tuple(files),
        registered_partition_count=len(registered),
        missing_registered_dates=missing_registered,
        existing_materializations=existing_materializations,
        existing_checks=existing_checks,
        source_empty_raw_count=source_empty_raw_count,
        precondition_errors=tuple(precondition_errors),
    )


def register_index_mins_partitions(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    confirm_partition_write: bool,
) -> IndexMinsEventReport:
    if not confirm_partition_write:
        raise ValueError("partition registration requires --confirm-partition-write")
    plan = plan_index_mins_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
        require_registered=False,
    )
    if plan.precondition_errors:
        raise ValueError("partition registration is blocked: " + "; ".join(plan.precondition_errors))
    registered = set(instance.get_dynamic_partitions(INDEX_MINS_PARTITION_SET))
    unexpected = registered - set(plan.expected_dates)
    if unexpected:
        raise ValueError("unexpected index_mins registered partitions: " + ",".join(sorted(unexpected)[:10]))
    missing = sorted(set(plan.expected_dates) - registered)
    if missing:
        instance.add_dynamic_partitions(INDEX_MINS_PARTITION_SET, missing)
    post_plan = plan_index_mins_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
        require_registered=True,
    )
    return IndexMinsEventReport(
        mode="register-partitions",
        confirmed=True,
        plan=post_plan,
        registered_partition_count=len(post_plan.expected_dates),
        scan_elapsed_ms=0.0,
    )


def _latest_materialization(instance: dg.DagsterInstance, asset_key: dg.AssetKey, trade_date: str):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[trade_date]),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"materialization missing after event write: {asset_key.to_user_string()}:{trade_date}")
    return result.records[0]


def _report_materialization(
    *,
    instance: dg.DagsterInstance,
    plan: IndexMinsEventPlan,
    audit: IndexMinsFileAudit,
) -> None:
    schema = RAW_INDEX_MINS_SCHEMA if audit.layer == "raw" else SILVER_INDEX_MINS_SCHEMA
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(audit.asset_key),
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.file_path,
                row_count=audit.row_count,
                observed_columns=tuple(column.name for column in schema),
                extra_metadata={
                    "source_method": "index_mins_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "partition_key": audit.partition_key,
                    "frequency": audit.frequency,
                    "reconciliation_report_path": str(plan.reconciliation_report_path),
                    "date_plan_fingerprint": plan.date_plan_fingerprint,
                },
            ),
        )
    )


def _report_check(
    *,
    instance: dg.DagsterInstance,
    plan: IndexMinsEventPlan,
    audit: IndexMinsFileAudit,
    check_name: str,
) -> None:
    materialization = _latest_materialization(instance, dg.AssetKey(audit.asset_key), audit.partition_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=dg.AssetKey(audit.asset_key),
            check_name=check_name,
            passed=True,
            blocking=True,
            partition=audit.partition_key,
            target_materialization_data=target,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=audit.row_count,
                failed_row_count=0,
                file_path=audit.file_path,
                extra_metadata={
                    "source_method": "index_mins_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "partition_key": audit.partition_key,
                    "frequency": audit.frequency,
                    "reason_code": "ready",
                    "reconciliation_report_path": str(plan.reconciliation_report_path),
                    "date_plan_fingerprint": plan.date_plan_fingerprint,
                },
            ),
        )
    )


def report_index_mins_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    dry_run: bool = True,
    confirm_event_write: bool = False,
) -> IndexMinsEventReport:
    if not dry_run and not confirm_event_write:
        raise ValueError("event apply requires --confirm-event-write")
    started = perf_counter()
    plan = plan_index_mins_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
    )
    if dry_run:
        return IndexMinsEventReport(
            mode="dry-run",
            confirmed=False,
            plan=plan,
            registered_partition_count=plan.registered_partition_count,
            scan_elapsed_ms=(perf_counter() - started) * 1000,
        )
    if plan.should_stop:
        raise ValueError("index_mins event apply is blocked: " + "; ".join(plan.precondition_errors))

    materialized = {asset: set(dates) for asset, dates in plan.existing_materializations.items()}
    checks = {asset: set(dates) for asset, dates in plan.existing_checks.items()}
    reported_materializations = 0
    skipped_materializations = 0
    reported_checks = 0
    skipped_checks = 0
    recent = set(plan.recent_check_dates)
    check_name_by_asset = {
        asset_key.to_user_string(): check_name
        for _, asset_key, _, check_name in _asset_specs()
    }
    for audit in plan.files:
        if audit.partition_key in materialized[audit.asset_key]:
            skipped_materializations += 1
        else:
            _report_materialization(instance=instance, plan=plan, audit=audit)
            materialized[audit.asset_key].add(audit.partition_key)
            reported_materializations += 1
        if audit.partition_key not in recent:
            continue
        if audit.partition_key in checks[audit.asset_key]:
            skipped_checks += 1
        else:
            _report_check(
                instance=instance,
                plan=plan,
                audit=audit,
                check_name=check_name_by_asset[audit.asset_key],
            )
            checks[audit.asset_key].add(audit.partition_key)
            reported_checks += 1
    return IndexMinsEventReport(
        mode="apply",
        confirmed=True,
        plan=plan,
        registered_partition_count=plan.registered_partition_count,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
        scan_elapsed_ms=(perf_counter() - started) * 1000,
    )


__all__ = [
    "INDEX_MINS_EVENT_WINDOW_SIZE",
    "INDEX_MINS_PARTITION_SET",
    "IndexMinsEventPlan",
    "IndexMinsEventPlanError",
    "IndexMinsEventReport",
    "plan_index_mins_bootstrap_events",
    "register_index_mins_partitions",
    "report_index_mins_events",
]
