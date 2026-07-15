"""Runless Dagster event backfill for the board Raw and Silver lake facts.

M7 wrote and audited the six board datasets outside Dagster.  This module is
the separate M8 control-plane step: it reports materializations for every
audited partition and one core check for the most recent twenty trade days.
It never writes parquet files, calls a source API, or executes a Dagster job.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
    batch_raw_dc_index_lake_readiness,
    batch_raw_dc_member_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
    batch_silver_dc_index_lake_readiness,
    batch_silver_dc_member_lake_readiness,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
    SILVER_DC_INDEX_SCHEMA,
    SILVER_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import (
    RAW_DC_DAILY_CHECKS,
    RAW_DC_INDEX_CHECKS,
    RAW_DC_MEMBER_CHECKS,
    SILVER_DC_DAILY_CHECKS,
    SILVER_DC_INDEX_CHECKS,
    SILVER_DC_MEMBER_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


DC_BOARD_EVENT_WINDOW_SIZE = 20
DC_BOARD_EVENT_ASSET_COUNT = 6
DC_BOARD_EVENT_SAMPLE_LIMIT = 10
DC_BOARD_EVENT_REGISTERED_PARTITION_SET = "cn_a_index_trade_days"
DC_BOARD_EVENT_SOURCE_REPORT = (
    "/private/tmp/dc_board_m7_bootstrap_dry_run_20260715_v7.json"
)


ReadinessBuilder = Callable[..., ContinuityBatchReadiness]
PathBuilder = Callable[[Path, str], Path]


@dataclass(frozen=True, slots=True)
class DcBoardEventAssetSpec:
    dataset: str
    layer: str
    asset_key: dg.AssetKey
    check_name: str
    path_builder: PathBuilder
    schema: Sequence[Any]
    readiness_builder: ReadinessBuilder
    source_method: str


DC_BOARD_EVENT_ASSET_SPECS = (
    DcBoardEventAssetSpec(
        dataset="dc_index",
        layer="raw",
        asset_key=dg.AssetKey("raw_tushare_dc_index"),
        check_name=RAW_DC_INDEX_CHECKS[0],
        path_builder=raw_dc_index_path,
        schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        readiness_builder=batch_raw_dc_index_lake_readiness,
        source_method="tushare_bootstrap",
    ),
    DcBoardEventAssetSpec(
        dataset="dc_member",
        layer="raw",
        asset_key=dg.AssetKey("raw_tushare_dc_member"),
        check_name=RAW_DC_MEMBER_CHECKS[0],
        path_builder=raw_dc_member_path,
        schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        readiness_builder=batch_raw_dc_member_lake_readiness,
        source_method="prod_db_readonly_export",
    ),
    DcBoardEventAssetSpec(
        dataset="dc_daily",
        layer="raw",
        asset_key=dg.AssetKey("raw_tushare_dc_daily"),
        check_name=RAW_DC_DAILY_CHECKS[0],
        path_builder=raw_dc_daily_path,
        schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        readiness_builder=batch_raw_dc_daily_lake_readiness,
        source_method="tushare_bootstrap",
    ),
    DcBoardEventAssetSpec(
        dataset="dc_index",
        layer="silver",
        asset_key=dg.AssetKey("silver_dc_index"),
        check_name=SILVER_DC_INDEX_CHECKS[0],
        path_builder=silver_dc_index_path,
        schema=SILVER_DC_INDEX_SCHEMA,
        readiness_builder=batch_silver_dc_index_lake_readiness,
        source_method="derived_from_assets",
    ),
    DcBoardEventAssetSpec(
        dataset="dc_member",
        layer="silver",
        asset_key=dg.AssetKey("silver_dc_member"),
        check_name=SILVER_DC_MEMBER_CHECKS[0],
        path_builder=silver_dc_member_path,
        schema=SILVER_DC_MEMBER_SCHEMA,
        readiness_builder=batch_silver_dc_member_lake_readiness,
        source_method="derived_from_assets",
    ),
    DcBoardEventAssetSpec(
        dataset="dc_daily",
        layer="silver",
        asset_key=dg.AssetKey("silver_dc_daily"),
        check_name=SILVER_DC_DAILY_CHECKS[0],
        path_builder=silver_dc_daily_path,
        schema=SILVER_DC_DAILY_SCHEMA,
        readiness_builder=batch_silver_dc_daily_lake_readiness,
        source_method="derived_from_assets",
    ),
)


@dataclass(frozen=True, slots=True)
class DcBoardEventAssetPlan:
    spec: DcBoardEventAssetSpec
    expected_trade_dates: tuple[str, ...]
    date_plan_fingerprint: str
    readiness: ContinuityBatchReadiness
    existing_materialized_count: int
    existing_ready_check_trade_dates: tuple[str, ...]
    existing_ready_check_count: int
    planned_materialization_count: int
    planned_check_count: int

    @property
    def first_trade_date(self) -> str | None:
        return self.expected_trade_dates[0] if self.expected_trade_dates else None

    @property
    def last_trade_date(self) -> str | None:
        return self.expected_trade_dates[-1] if self.expected_trade_dates else None

    @property
    def recent_check_trade_dates(self) -> tuple[str, ...]:
        return self.expected_trade_dates[-DC_BOARD_EVENT_WINDOW_SIZE:]

    @property
    def readiness_ready_count(self) -> int:
        return sum(
            1 for status in self.readiness.statuses_by_trade_date.values() if status.ready
        )

    def to_dict(self) -> dict[str, object]:
        failed = [
            {
                "trade_date": trade_date,
                "reason": status.reason,
                "failed_check_names": list(status.failed_check_names),
                "missing_check_names": list(status.missing_check_names),
                "summary": dict(status.summary),
            }
            for trade_date, status in self.readiness.statuses_by_trade_date.items()
            if not status.ready
        ]
        return {
            "asset_key": self.spec.asset_key.to_user_string(),
            "dataset": self.spec.dataset,
            "layer": self.spec.layer,
            "check_name": self.spec.check_name,
            "source_method": self.spec.source_method,
            "expected_count": len(self.expected_trade_dates),
            "expected_start_date": self.first_trade_date,
            "expected_end_date": self.last_trade_date,
            "date_plan_fingerprint": self.date_plan_fingerprint,
            "recent_check_count": len(self.recent_check_trade_dates),
            "existing_materialized_count": self.existing_materialized_count,
            "existing_ready_check_trade_dates": list(
                self.existing_ready_check_trade_dates
            ),
            "existing_ready_check_count": self.existing_ready_check_count,
            "planned_materialization_count": self.planned_materialization_count,
            "planned_check_count": self.planned_check_count,
            "readiness_elapsed_ms": self.readiness.elapsed_ms,
            "readiness_scanned_file_count": self.readiness.scanned_file_count,
            "readiness_ready_count": self.readiness_ready_count,
            "readiness_failed_count": len(failed),
            "readiness_failed_samples": failed[:DC_BOARD_EVENT_SAMPLE_LIMIT],
        }


@dataclass(frozen=True, slots=True)
class DcBoardEventPlan:
    lake_root: Path
    baseline_report_path: Path
    raw_audit_report_path: Path
    silver_audit_report_path: Path
    final_reconciliation_report_path: Path
    registered_partition_count: int
    missing_registered_dates: tuple[str, ...]
    asset_plans: tuple[DcBoardEventAssetPlan, ...]
    precondition_errors: tuple[str, ...] = ()

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors) or any(
            plan.readiness_ready_count != len(plan.expected_trade_dates)
            for plan in self.asset_plans
        )

    @property
    def planned_materialization_count(self) -> int:
        return sum(plan.planned_materialization_count for plan in self.asset_plans)

    @property
    def planned_check_count(self) -> int:
        return sum(plan.planned_check_count for plan in self.asset_plans)

    @property
    def planned_event_count(self) -> int:
        return self.planned_materialization_count + self.planned_check_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "lake_root": str(self.lake_root),
            "baseline_report_path": str(self.baseline_report_path),
            "raw_audit_report_path": str(self.raw_audit_report_path),
            "silver_audit_report_path": str(self.silver_audit_report_path),
            "final_reconciliation_report_path": str(self.final_reconciliation_report_path),
            "registered_partition_set": DC_BOARD_EVENT_REGISTERED_PARTITION_SET,
            "registered_partition_count": self.registered_partition_count,
            "missing_registered_dates": list(self.missing_registered_dates),
            "asset_count": len(self.asset_plans),
            "planned_materialization_event_count": self.planned_materialization_count,
            "planned_check_event_count": self.planned_check_count,
            "planned_event_count": self.planned_event_count,
            "expected_materialization_event_count": sum(
                len(plan.expected_trade_dates) for plan in self.asset_plans
            ),
            "expected_recent_check_event_count": sum(
                len(plan.recent_check_trade_dates) for plan in self.asset_plans
            ),
            "precondition_errors": list(self.precondition_errors),
            "should_stop": self.should_stop,
            "assets": [plan.to_dict() for plan in self.asset_plans],
        }


@dataclass(frozen=True, slots=True)
class DcBoardEventReport:
    plan: DcBoardEventPlan
    dry_run: bool
    confirmed: bool
    reported_materialization_count: int
    reported_check_count: int
    reported_event_count: int
    skipped_materialization_count: int
    skipped_check_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "dry_run": self.dry_run,
            "confirmed": self.confirmed,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "reported_event_count": self.reported_event_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "plan": self.plan.to_dict(),
        }


def plan_dc_board_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    baseline_report_path: Path,
    raw_audit_report_path: Path,
    silver_audit_report_path: Path,
    final_reconciliation_report_path: Path,
) -> DcBoardEventPlan:
    baseline = _load_green_report(baseline_report_path, "M7 dry-run")
    raw_audit = _load_green_report(raw_audit_report_path, "M7 Raw audit")
    silver_audit = _load_green_report(silver_audit_report_path, "M7 Silver audit")
    final_reconciliation = _load_green_report(
        final_reconciliation_report_path,
        "M7 final reconciliation",
    )
    date_plans = _date_plans_by_dataset(baseline)
    fingerprints = {
        dataset: str(plan["fingerprint"])
        for dataset, plan in date_plans.items()
    }
    precondition_errors = _validate_audit_fingerprints(
        date_plan_fingerprints=fingerprints,
        reports=(raw_audit, silver_audit),
        final_reconciliation=final_reconciliation,
    )

    registered = tuple(
        sorted(
            str(value)
            for value in instance.get_dynamic_partitions(
                DC_BOARD_EVENT_REGISTERED_PARTITION_SET
            )
        )
    )
    registered_set = set(registered)
    expected_union = set().union(
        *(set(plan["expected_trade_dates"]) for plan in date_plans.values())
    )
    missing_registered = tuple(sorted(expected_union - registered_set))
    if missing_registered:
        precondition_errors.append(
            "registered partition set is missing M7 expected dates: "
            + ",".join(missing_registered[:DC_BOARD_EVENT_SAMPLE_LIMIT])
        )

    readiness_by_asset: dict[str, ContinuityBatchReadiness] = {}
    with duckdb_resource.connect() as connection:
        for spec in DC_BOARD_EVENT_ASSET_SPECS:
            date_plan = date_plans[spec.dataset]
            readiness_by_asset[spec.asset_key.to_user_string()] = spec.readiness_builder(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=date_plan["expected_trade_dates"],
                registered_trade_days=registered,
            )

    asset_plans: list[DcBoardEventAssetPlan] = []
    for spec in DC_BOARD_EVENT_ASSET_SPECS:
        date_plan = date_plans[spec.dataset]
        expected_dates = tuple(str(value) for value in date_plan["expected_trade_dates"])
        readiness = readiness_by_asset[spec.asset_key.to_user_string()]
        materialized = set(instance.get_materialized_partitions(spec.asset_key))
        recent_dates = expected_dates[-DC_BOARD_EVENT_WINDOW_SIZE:]
        readiness_spec = AssetReadinessSpec(spec.asset_key, (spec.check_name,))
        existing_ready_checks = tuple(
            trade_date
            for trade_date in recent_dates
            if asset_readiness_status(
                instance,
                readiness_spec,
                partition_key=trade_date,
            ).ready
        )
        if any(not status.ready for status in readiness.statuses_by_trade_date.values()):
            precondition_errors.append(
                f"{spec.asset_key.to_user_string()} lake readiness is not green"
            )
        asset_plans.append(
            DcBoardEventAssetPlan(
                spec=spec,
                expected_trade_dates=expected_dates,
                date_plan_fingerprint=str(date_plan["fingerprint"]),
                readiness=readiness,
                existing_materialized_count=sum(
                    1 for trade_date in expected_dates if trade_date in materialized
                ),
                existing_ready_check_trade_dates=existing_ready_checks,
                existing_ready_check_count=len(existing_ready_checks),
                planned_materialization_count=sum(
                    1 for trade_date in expected_dates if trade_date not in materialized
                ),
                planned_check_count=sum(
                    1 for trade_date in recent_dates if trade_date not in existing_ready_checks
                ),
            )
        )

    return DcBoardEventPlan(
        lake_root=lake_root,
        baseline_report_path=baseline_report_path,
        raw_audit_report_path=raw_audit_report_path,
        silver_audit_report_path=silver_audit_report_path,
        final_reconciliation_report_path=final_reconciliation_report_path,
        registered_partition_count=len(registered),
        missing_registered_dates=missing_registered,
        asset_plans=tuple(asset_plans),
        precondition_errors=tuple(dict.fromkeys(precondition_errors)),
    )


def report_dc_board_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    baseline_report_path: Path,
    raw_audit_report_path: Path,
    silver_audit_report_path: Path,
    final_reconciliation_report_path: Path,
    dry_run: bool = True,
    confirm_event_write: bool = False,
) -> DcBoardEventReport:
    plan = plan_dc_board_events(
        instance=instance,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        baseline_report_path=baseline_report_path,
        raw_audit_report_path=raw_audit_report_path,
        silver_audit_report_path=silver_audit_report_path,
        final_reconciliation_report_path=final_reconciliation_report_path,
    )
    if dry_run:
        return DcBoardEventReport(
            plan=plan,
            dry_run=True,
            confirmed=False,
            reported_materialization_count=0,
            reported_check_count=0,
            reported_event_count=0,
            skipped_materialization_count=0,
            skipped_check_count=0,
        )
    if not confirm_event_write:
        raise ValueError("event apply requires --confirm-event-write")
    if plan.should_stop:
        raise ValueError(
            "M8 event apply is blocked by preconditions: "
            + "; ".join(plan.precondition_errors[:DC_BOARD_EVENT_SAMPLE_LIMIT])
        )

    materialized = {
        plan_item.spec.asset_key.to_user_string(): set(
            instance.get_materialized_partitions(plan_item.spec.asset_key)
        )
        for plan_item in plan.asset_plans
    }
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0
    for plan_item in plan.asset_plans:
        asset_key_label = plan_item.spec.asset_key.to_user_string()
        statuses = plan_item.readiness.statuses_by_trade_date
        for trade_date in plan_item.expected_trade_dates:
            if trade_date in materialized[asset_key_label]:
                skipped_materializations += 1
                continue
            _report_materialization_event(
                instance=instance,
                plan=plan,
                asset_plan=plan_item,
                trade_date=trade_date,
                status=statuses[trade_date],
            )
            materialized[asset_key_label].add(trade_date)
            reported_materializations += 1

        existing_ready_check_dates = set(plan_item.existing_ready_check_trade_dates)
        for trade_date in plan_item.recent_check_trade_dates:
            if trade_date in existing_ready_check_dates:
                skipped_checks += 1
                continue
            _report_check_event(
                instance=instance,
                plan=plan,
                asset_plan=plan_item,
                trade_date=trade_date,
                status=statuses[trade_date],
            )
            reported_checks += 1

    return DcBoardEventReport(
        plan=plan,
        dry_run=False,
        confirmed=True,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        reported_event_count=reported_materializations + reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
    )


def _report_materialization_event(
    *,
    instance: dg.DagsterInstance,
    plan: DcBoardEventPlan,
    asset_plan: DcBoardEventAssetPlan,
    trade_date: str,
    status: ContinuityDateReadiness,
) -> None:
    if not status.ready:
        raise ValueError(
            f"cannot report materialization for non-ready board partition: "
            f"{asset_plan.spec.asset_key.to_user_string()}:{trade_date}"
        )
    path = asset_plan.spec.path_builder(plan.lake_root, trade_date)
    row_count = int(status.summary.get("checked_row_count", 0))
    observed_columns = tuple(str(column.name) for column in asset_plan.spec.schema)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_plan.spec.asset_key,
            partition=trade_date,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=row_count,
                observed_columns=observed_columns,
                extra_metadata={
                    "source_method": asset_plan.spec.source_method,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "partition_key": trade_date,
                    "date_plan_fingerprint": asset_plan.date_plan_fingerprint,
                    "m7_baseline_report_path": str(plan.baseline_report_path),
                    "m7_raw_audit_report_path": str(plan.raw_audit_report_path),
                    "m7_silver_audit_report_path": str(plan.silver_audit_report_path),
                    "m7_final_reconciliation_report_path": str(
                        plan.final_reconciliation_report_path
                    ),
                },
            ),
        )
    )


def _report_check_event(
    *,
    instance: dg.DagsterInstance,
    plan: DcBoardEventPlan,
    asset_plan: DcBoardEventAssetPlan,
    trade_date: str,
    status: ContinuityDateReadiness,
) -> None:
    if not status.ready:
        raise ValueError(
            f"cannot report check for non-ready board partition: "
            f"{asset_plan.spec.asset_key.to_user_string()}:{trade_date}"
        )
    materialization = _latest_materialization(
        instance,
        asset_plan.spec.asset_key,
        trade_date,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    path = asset_plan.spec.path_builder(plan.lake_root, trade_date)
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=asset_plan.spec.asset_key,
            check_name=asset_plan.spec.check_name,
            passed=True,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=int(status.summary.get("checked_row_count", 0)),
                failed_row_count=0,
                file_path=path,
                extra_metadata={
                    "source_method": asset_plan.spec.source_method,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "partition_key": trade_date,
                    "date_plan_fingerprint": asset_plan.date_plan_fingerprint,
                    "m7_final_reconciliation_report_path": str(
                        plan.final_reconciliation_report_path
                    ),
                },
            ),
            blocking=True,
            partition=trade_date,
            target_materialization_data=target,
        )
    )


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"expected materialization for {asset_key}:{partition_key}")
    return result.records[0]


def _load_green_report(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing {label} report: {path}")
    report = json.loads(path.read_text())
    if report.get("should_stop") is not False:
        raise ValueError(f"{label} report is not green: {path}")
    return report


def _date_plans_by_dataset(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    date_plans = report.get("date_plans")
    if not isinstance(date_plans, list):
        raise ValueError("M7 baseline report has no date_plans list")
    result = {}
    for item in date_plans:
        if not isinstance(item, Mapping):
            raise ValueError("M7 baseline date plan is not an object")
        dataset = str(item.get("dataset", ""))
        expected = tuple(str(value) for value in item.get("expected_trade_dates", ()))
        fingerprint = str(item.get("fingerprint", ""))
        if dataset not in {"dc_index", "dc_member", "dc_daily"}:
            raise ValueError(f"unexpected M7 dataset: {dataset}")
        if not expected or not fingerprint:
            raise ValueError(f"incomplete M7 date plan: {dataset}")
        if tuple(sorted(set(expected))) != expected:
            raise ValueError(f"M7 expected dates are not sorted and unique: {dataset}")
        for value in expected:
            date.fromisoformat(value)
        result[dataset] = {
            "expected_trade_dates": expected,
            "fingerprint": fingerprint,
        }
    if set(result) != {"dc_index", "dc_member", "dc_daily"}:
        raise ValueError("M7 baseline must contain exactly three board date plans")
    return result


def _validate_audit_fingerprints(
    *,
    date_plan_fingerprints: Mapping[str, str],
    reports: Sequence[Mapping[str, Any]],
    final_reconciliation: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    for label, report in zip(("Raw", "Silver"), reports, strict=True):
        observed = report.get("date_plan_fingerprints")
        if observed != dict(date_plan_fingerprints):
            errors.append(f"M7 {label} audit fingerprint mismatch")
    for layer in ("raw", "silver"):
        nested = final_reconciliation.get(layer, {})
        if nested.get("date_plan_fingerprints") != dict(date_plan_fingerprints):
            errors.append(f"M7 final reconciliation {layer} fingerprint mismatch")
    return errors


__all__ = [
    "DC_BOARD_EVENT_ASSET_SPECS",
    "DC_BOARD_EVENT_REGISTERED_PARTITION_SET",
    "DC_BOARD_EVENT_SOURCE_REPORT",
    "DC_BOARD_EVENT_WINDOW_SIZE",
    "DcBoardEventAssetPlan",
    "DcBoardEventAssetSpec",
    "DcBoardEventPlan",
    "DcBoardEventReport",
    "plan_dc_board_events",
    "report_dc_board_events",
]
