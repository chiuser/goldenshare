"""Bounded Dagster event backfill for the completed ``index_global`` Bootstrap.

This module is intentionally separate from the Raw/Silver Bootstrap writers.
It only consumes the frozen P7 reconciliation report and the existing lake;
the only write operations are the explicitly requested dynamic-partition and
runless-event writes performed by the public entry points below.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import AssetReadinessSpec, asset_readiness_status


INDEX_GLOBAL_EVENT_WINDOW_SIZE = 20
INDEX_GLOBAL_EXPECTED_PARTITION_COUNT = 1670
INDEX_GLOBAL_DATE_PLAN_FINGERPRINT = (
    "1e4868df643ab6b35f0b76405a823bda240386dab78c7f8d274dacb7a5579492"
)
INDEX_GLOBAL_PARTITION_SET = cn_global_index_trade_days.name
RAW_INDEX_GLOBAL_ASSET_KEY = dg.AssetKey("raw_index_global")
SILVER_INDEX_GLOBAL_ASSET_KEY = dg.AssetKey("silver_index_global")
RAW_INDEX_GLOBAL_CHECK_NAME = "raw_index_global_core_check"
SILVER_INDEX_GLOBAL_CHECK_NAME = "silver_index_global_core_check"

_ASSET_SPECS = (
    (RAW_INDEX_GLOBAL_ASSET_KEY, RAW_INDEX_GLOBAL_CHECK_NAME, raw_index_global_path, RAW_INDEX_GLOBAL_SCHEMA),
    (
        SILVER_INDEX_GLOBAL_ASSET_KEY,
        SILVER_INDEX_GLOBAL_CHECK_NAME,
        silver_index_global_path,
        SILVER_INDEX_GLOBAL_SCHEMA,
    ),
)


class IndexGlobalEventPlanError(ValueError):
    """Raised when the frozen lake/event scope cannot be trusted."""


@dataclass(frozen=True, slots=True)
class IndexGlobalPartitionAudit:
    trade_date: str
    raw_row_count: int
    silver_row_count: int


@dataclass(frozen=True, slots=True)
class IndexGlobalEventPlan:
    lake_root: Path
    reconciliation_report_path: Path
    date_plan_fingerprint: str
    expected_dates: tuple[str, ...]
    recent_check_dates: tuple[str, ...]
    audits: Mapping[str, IndexGlobalPartitionAudit]
    registered_partition_count: int
    missing_registered_dates: tuple[str, ...]
    existing_raw_materialized_dates: tuple[str, ...]
    existing_silver_materialized_dates: tuple[str, ...]
    existing_raw_ready_check_dates: tuple[str, ...]
    existing_silver_ready_check_dates: tuple[str, ...]
    precondition_errors: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors) or bool(self.missing_registered_dates)

    @property
    def planned_raw_materialization_count(self) -> int:
        return sum(
            date not in set(self.existing_raw_materialized_dates)
            for date in self.expected_dates
        )

    @property
    def planned_silver_materialization_count(self) -> int:
        return sum(
            date not in set(self.existing_silver_materialized_dates)
            for date in self.expected_dates
        )

    @property
    def planned_raw_check_count(self) -> int:
        return sum(date not in set(self.existing_raw_ready_check_dates) for date in self.recent_check_dates)

    @property
    def planned_silver_check_count(self) -> int:
        return sum(date not in set(self.existing_silver_ready_check_dates) for date in self.recent_check_dates)

    @property
    def planned_event_count(self) -> int:
        return (
            self.planned_raw_materialization_count
            + self.planned_silver_materialization_count
            + self.planned_raw_check_count
            + self.planned_silver_check_count
        )

    def to_dict(self) -> dict[str, object]:
        sample_dates = tuple(dict.fromkeys((*self.expected_dates[:3], *self.expected_dates[-3:])))
        return {
            "schema_version": 1,
            "lake_root": str(self.lake_root),
            "reconciliation_report_path": str(self.reconciliation_report_path),
            "partition_set": INDEX_GLOBAL_PARTITION_SET,
            "date_plan_fingerprint": self.date_plan_fingerprint,
            "expected_date_count": len(self.expected_dates),
            "expected_start_date": self.expected_dates[0] if self.expected_dates else None,
            "expected_end_date": self.expected_dates[-1] if self.expected_dates else None,
            "expected_date_samples": list(sample_dates),
            "recent_check_dates": list(self.recent_check_dates),
            "registered_partition_count": self.registered_partition_count,
            "missing_registered_count": len(self.missing_registered_dates),
            "missing_registered_samples": list(self.missing_registered_dates[:10]),
            "existing_raw_materialized_count": len(self.existing_raw_materialized_dates),
            "existing_silver_materialized_count": len(self.existing_silver_materialized_dates),
            "existing_raw_ready_check_count": len(self.existing_raw_ready_check_dates),
            "existing_silver_ready_check_count": len(self.existing_silver_ready_check_dates),
            "planned_raw_materialization_event_count": self.planned_raw_materialization_count,
            "planned_silver_materialization_event_count": self.planned_silver_materialization_count,
            "planned_raw_check_event_count": self.planned_raw_check_count,
            "planned_silver_check_event_count": self.planned_silver_check_count,
            "planned_event_count": self.planned_event_count,
            "row_count_samples": [
                {
                    "trade_date": date,
                    "raw_row_count": self.audits[date].raw_row_count,
                    "silver_row_count": self.audits[date].silver_row_count,
                }
                for date in sample_dates
            ],
            "precondition_errors": list(self.precondition_errors),
            "should_stop": self.should_stop,
        }


@dataclass(frozen=True, slots=True)
class IndexGlobalEventReport:
    mode: str
    confirmed: bool
    plan: IndexGlobalEventPlan
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


def _date_plan_fingerprint(dates: Sequence[str]) -> str:
    payload = "\n".join(("index_global", "2022-01-01", *dates))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_reconciliation_report(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise IndexGlobalEventPlanError(f"missing P7 reconciliation report: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexGlobalEventPlanError(f"invalid P7 reconciliation report: {path}") from exc
    if report.get("should_stop") is not False:
        raise IndexGlobalEventPlanError("P7 reconciliation report is not green")
    date_plan = report.get("date_plan")
    if not isinstance(date_plan, Mapping):
        raise IndexGlobalEventPlanError("P7 reconciliation report has no date_plan")
    dates = date_plan.get("expected_natural_dates")
    if not isinstance(dates, list) or not all(isinstance(value, str) for value in dates):
        raise IndexGlobalEventPlanError("P7 date_plan has no complete natural-date list")
    if len(dates) != INDEX_GLOBAL_EXPECTED_PARTITION_COUNT:
        raise IndexGlobalEventPlanError(
            f"P7 date_plan must contain {INDEX_GLOBAL_EXPECTED_PARTITION_COUNT} dates"
        )
    normalized_dates = tuple(dates)
    if date_plan.get("fingerprint") != INDEX_GLOBAL_DATE_PLAN_FINGERPRINT:
        raise IndexGlobalEventPlanError("P7 date_plan fingerprint is not the frozen fingerprint")
    if _date_plan_fingerprint(normalized_dates) != INDEX_GLOBAL_DATE_PLAN_FINGERPRINT:
        raise IndexGlobalEventPlanError("P7 date_plan contents do not match its fingerprint")
    if date_plan.get("start_date") != normalized_dates[0] or date_plan.get("end_date") != normalized_dates[-1]:
        raise IndexGlobalEventPlanError("P7 date_plan boundary does not match its natural dates")
    for layer in ("raw_audit", "silver_audit"):
        audit = report.get(layer)
        if not isinstance(audit, Mapping):
            raise IndexGlobalEventPlanError(f"P7 reconciliation report has no {layer}")
        if any(audit.get(key) != expected for key, expected in (
            ("expected_file_count", INDEX_GLOBAL_EXPECTED_PARTITION_COUNT),
            ("missing_count", 0),
            ("invalid_existing_count", 0),
            ("valid_existing_count", INDEX_GLOBAL_EXPECTED_PARTITION_COUNT),
        )):
            raise IndexGlobalEventPlanError(f"P7 {layer} is not a complete green audit")
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
    spec = AssetReadinessSpec(asset_key, (check_name,))
    return tuple(
        trade_date
        for trade_date in dates
        if asset_readiness_status(instance, spec, partition_key=trade_date).ready
    )


def plan_index_global_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    require_registered: bool = True,
) -> IndexGlobalEventPlan:
    report = _load_reconciliation_report(reconciliation_report_path)
    expected_dates = tuple(report["date_plan"]["expected_natural_dates"])
    recent_dates = expected_dates[-INDEX_GLOBAL_EVENT_WINDOW_SIZE:]
    raw_paths = tuple(raw_index_global_path(lake_root, date) for date in expected_dates)
    silver_paths = tuple(silver_index_global_path(lake_root, date) for date in expected_dates)
    missing_files = [str(path) for path in (*raw_paths, *silver_paths) if not path.is_file()]
    precondition_errors: list[str] = []
    if missing_files:
        precondition_errors.append(f"lake target files are missing: {missing_files[:3]}")
    with duckdb_resource.connect() as connection:
        raw_counts = _row_counts(connection, raw_paths) if not missing_files else {}
        silver_counts = _row_counts(connection, silver_paths) if not missing_files else {}
    audits = {
        date: IndexGlobalPartitionAudit(
            trade_date=date,
            raw_row_count=raw_counts.get(str(raw_index_global_path(lake_root, date).resolve()), 0),
            silver_row_count=silver_counts.get(str(silver_index_global_path(lake_root, date).resolve()), 0),
        )
        for date in expected_dates
    }
    registered = set(str(value) for value in instance.get_dynamic_partitions(INDEX_GLOBAL_PARTITION_SET))
    missing_registered = tuple(sorted(set(expected_dates) - registered))
    if require_registered and missing_registered:
        precondition_errors.append(
            f"registered partition set is missing {len(missing_registered)} expected dates"
        )
    existing_raw = tuple(sorted(set(expected_dates) & set(instance.get_materialized_partitions(RAW_INDEX_GLOBAL_ASSET_KEY))))
    existing_silver = tuple(sorted(set(expected_dates) & set(instance.get_materialized_partitions(SILVER_INDEX_GLOBAL_ASSET_KEY))))
    existing_raw_checks = _existing_ready_checks(
        instance,
        asset_key=RAW_INDEX_GLOBAL_ASSET_KEY,
        check_name=RAW_INDEX_GLOBAL_CHECK_NAME,
        dates=recent_dates,
    )
    existing_silver_checks = _existing_ready_checks(
        instance,
        asset_key=SILVER_INDEX_GLOBAL_ASSET_KEY,
        check_name=SILVER_INDEX_GLOBAL_CHECK_NAME,
        dates=recent_dates,
    )
    return IndexGlobalEventPlan(
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        date_plan_fingerprint=str(report["date_plan"]["fingerprint"]),
        expected_dates=expected_dates,
        recent_check_dates=recent_dates,
        audits=audits,
        registered_partition_count=len(registered),
        missing_registered_dates=missing_registered,
        existing_raw_materialized_dates=existing_raw,
        existing_silver_materialized_dates=existing_silver,
        existing_raw_ready_check_dates=existing_raw_checks,
        existing_silver_ready_check_dates=existing_silver_checks,
        precondition_errors=tuple(precondition_errors),
    )


def register_index_global_partitions(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    confirm_partition_write: bool,
) -> IndexGlobalEventReport:
    if not confirm_partition_write:
        raise ValueError("partition registration requires --confirm-partition-write")
    plan = plan_index_global_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
        require_registered=False,
    )
    if plan.precondition_errors:
        raise ValueError("partition registration is blocked: " + "; ".join(plan.precondition_errors))
    registered_before = set(instance.get_dynamic_partitions(INDEX_GLOBAL_PARTITION_SET))
    unexpected = registered_before - set(plan.expected_dates)
    if unexpected:
        raise ValueError(
            "partition registration found dates outside the frozen P7 plan: "
            + ",".join(sorted(unexpected)[:10])
        )
    missing = list(plan.missing_registered_dates)
    if missing:
        instance.add_dynamic_partitions(INDEX_GLOBAL_PARTITION_SET, missing)
    registered_after = set(instance.get_dynamic_partitions(INDEX_GLOBAL_PARTITION_SET))
    if registered_after != set(plan.expected_dates):
        raise RuntimeError("partition registration did not exactly match the frozen P7 date plan")
    post_plan = plan_index_global_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
        require_registered=True,
    )
    return IndexGlobalEventReport(
        mode="register-partitions",
        confirmed=True,
        plan=post_plan,
        registered_partition_count=len(registered_after),
        scan_elapsed_ms=0.0,
    )


def _latest_materialization(instance: dg.DagsterInstance, asset_key: dg.AssetKey, trade_date: str):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[trade_date]),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"materialization was not recorded for {asset_key.to_user_string()}:{trade_date}")
    return result.records[0]


def _report_materialization(
    *,
    instance: dg.DagsterInstance,
    plan: IndexGlobalEventPlan,
    asset_key: dg.AssetKey,
    trade_date: str,
    row_count: int,
    layer: str,
) -> None:
    path = raw_index_global_path(plan.lake_root, trade_date) if layer == "raw" else silver_index_global_path(plan.lake_root, trade_date)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_key,
            partition=trade_date,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=row_count,
                observed_columns=tuple(column.name for column in (RAW_INDEX_GLOBAL_SCHEMA if layer == "raw" else SILVER_INDEX_GLOBAL_SCHEMA)),
                extra_metadata={
                    "source_method": "index_global_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "partition_key": trade_date,
                    "reconciliation_report_path": str(plan.reconciliation_report_path),
                    "date_plan_fingerprint": plan.date_plan_fingerprint,
                },
            ),
        )
    )


def _report_check(
    *,
    instance: dg.DagsterInstance,
    plan: IndexGlobalEventPlan,
    asset_key: dg.AssetKey,
    check_name: str,
    trade_date: str,
    row_count: int,
    layer: str,
) -> None:
    materialization = _latest_materialization(instance, asset_key, trade_date)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    path = raw_index_global_path(plan.lake_root, trade_date) if layer == "raw" else silver_index_global_path(plan.lake_root, trade_date)
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=asset_key,
            check_name=check_name,
            passed=True,
            blocking=True,
            partition=trade_date,
            target_materialization_data=target,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=row_count,
                failed_row_count=0,
                file_path=path,
                extra_metadata={
                    "source_method": "index_global_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_natural_days",
                    "partition_key": trade_date,
                    "reason_code": "ready",
                    "reconciliation_report_path": str(plan.reconciliation_report_path),
                    "date_plan_fingerprint": plan.date_plan_fingerprint,
                },
            ),
        )
    )


def report_index_global_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    reconciliation_report_path: Path,
    duckdb_resource: DuckDBResource,
    dry_run: bool = True,
    confirm_event_write: bool = False,
) -> IndexGlobalEventReport:
    if not dry_run and not confirm_event_write:
        raise ValueError("event apply requires --confirm-event-write")
    started = perf_counter()
    plan = plan_index_global_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        reconciliation_report_path=reconciliation_report_path,
        duckdb_resource=duckdb_resource,
    )
    if dry_run:
        return IndexGlobalEventReport(
            mode="dry-run",
            confirmed=False,
            plan=plan,
            registered_partition_count=plan.registered_partition_count,
            scan_elapsed_ms=(perf_counter() - started) * 1000,
        )
    if plan.should_stop:
        raise ValueError("index_global event apply is blocked: " + "; ".join(plan.precondition_errors))

    raw_existing = set(plan.existing_raw_materialized_dates)
    silver_existing = set(plan.existing_silver_materialized_dates)
    raw_checks = set(plan.existing_raw_ready_check_dates)
    silver_checks = set(plan.existing_silver_ready_check_dates)
    reported_materializations = 0
    skipped_materializations = 0
    reported_checks = 0
    skipped_checks = 0

    for trade_date in plan.expected_dates:
        if trade_date in raw_existing:
            skipped_materializations += 1
        else:
            _report_materialization(
                instance=instance,
                plan=plan,
                asset_key=RAW_INDEX_GLOBAL_ASSET_KEY,
                trade_date=trade_date,
                row_count=plan.audits[trade_date].raw_row_count,
                layer="raw",
            )
            raw_existing.add(trade_date)
            reported_materializations += 1
        if trade_date in silver_existing:
            skipped_materializations += 1
        else:
            _report_materialization(
                instance=instance,
                plan=plan,
                asset_key=SILVER_INDEX_GLOBAL_ASSET_KEY,
                trade_date=trade_date,
                row_count=plan.audits[trade_date].silver_row_count,
                layer="silver",
            )
            silver_existing.add(trade_date)
            reported_materializations += 1

    for trade_date in plan.recent_check_dates:
        if trade_date in raw_checks:
            skipped_checks += 1
        else:
            _report_check(
                instance=instance,
                plan=plan,
                asset_key=RAW_INDEX_GLOBAL_ASSET_KEY,
                check_name=RAW_INDEX_GLOBAL_CHECK_NAME,
                trade_date=trade_date,
                row_count=plan.audits[trade_date].raw_row_count,
                layer="raw",
            )
            reported_checks += 1
        if trade_date in silver_checks:
            skipped_checks += 1
        else:
            _report_check(
                instance=instance,
                plan=plan,
                asset_key=SILVER_INDEX_GLOBAL_ASSET_KEY,
                check_name=SILVER_INDEX_GLOBAL_CHECK_NAME,
                trade_date=trade_date,
                row_count=plan.audits[trade_date].silver_row_count,
                layer="silver",
            )
            reported_checks += 1

    return IndexGlobalEventReport(
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
    "INDEX_GLOBAL_DATE_PLAN_FINGERPRINT",
    "INDEX_GLOBAL_EVENT_WINDOW_SIZE",
    "INDEX_GLOBAL_EXPECTED_PARTITION_COUNT",
    "IndexGlobalEventPlan",
    "IndexGlobalEventPlanError",
    "IndexGlobalEventReport",
    "plan_index_global_bootstrap_events",
    "register_index_global_partitions",
    "report_index_global_events",
]
