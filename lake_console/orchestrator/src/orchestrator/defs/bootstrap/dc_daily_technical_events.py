"""Bounded runless event planning and reporting for Gold dc_daily technical data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
    GoldDcDailyTechnicalAudit,
    batch_gold_dc_daily_technical_audit,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, gold_dc_daily_technical_path, silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import GOLD_DC_DAILY_TECHNICAL_SCHEMA
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import AssetReadinessSpec, asset_readiness_status


GOLD_DC_DAILY_TECHNICAL_ASSET_KEY = dg.AssetKey("gold_dc_daily_technical")
GOLD_DC_DAILY_TECHNICAL_EVENT_WINDOW_SIZE = 20
GOLD_DC_DAILY_TECHNICAL_PARTITION_SET = "cn_a_index_trade_days"


@dataclass(frozen=True, slots=True)
class GoldDcDailyTechnicalEventPlan:
    lake_root: Path
    audit_report_path: Path
    expected_trade_dates: tuple[str, ...]
    recent_check_trade_dates: tuple[str, ...]
    selected_materialization_trade_dates: tuple[str, ...]
    selected_check_trade_dates: tuple[str, ...]
    existing_materialized_trade_dates: tuple[str, ...]
    existing_ready_check_trade_dates: tuple[str, ...]
    audits: Mapping[str, GoldDcDailyTechnicalAudit]
    registered_partition_count: int
    precondition_errors: tuple[str, ...] = ()

    @property
    def planned_materialization_count(self) -> int:
        existing = set(self.existing_materialized_trade_dates)
        return sum(
            trade_date in set(self.selected_materialization_trade_dates)
            and trade_date not in existing
            for trade_date in self.selected_materialization_trade_dates
        )

    @property
    def planned_check_count(self) -> int:
        existing = set(self.existing_ready_check_trade_dates)
        return sum(
            trade_date not in existing for trade_date in self.selected_check_trade_dates
        )

    @property
    def planned_event_count(self) -> int:
        return self.planned_materialization_count + self.planned_check_count

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors) or any(
            not self.audits[trade_date].passed for trade_date in self.expected_trade_dates
        )

    def to_dict(self) -> dict[str, object]:
        failed = [
            {
                "trade_date": trade_date,
                "failed_rules": list(audit.failed_rules),
                "reason_code": audit.reason_code,
                "checked_row_count": audit.checked_row_count,
            }
            for trade_date, audit in self.audits.items()
            if not audit.passed
        ]
        return {
            "schema_version": 1,
            "asset_key": GOLD_DC_DAILY_TECHNICAL_ASSET_KEY.to_user_string(),
            "check_name": GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
            "partition_set": GOLD_DC_DAILY_TECHNICAL_PARTITION_SET,
            "lake_root": str(self.lake_root),
            "audit_report_path": str(self.audit_report_path),
            "expected_date_count": len(self.expected_trade_dates),
            "expected_start_date": self.expected_trade_dates[0]
            if self.expected_trade_dates
            else None,
            "expected_end_date": self.expected_trade_dates[-1]
            if self.expected_trade_dates
            else None,
            "recent_check_trade_dates": list(self.recent_check_trade_dates),
            "selected_materialization_trade_dates": list(
                self.selected_materialization_trade_dates
            ),
            "selected_check_trade_dates": list(self.selected_check_trade_dates),
            "existing_materialized_count": len(self.existing_materialized_trade_dates),
            "existing_ready_check_count": len(self.existing_ready_check_trade_dates),
            "registered_partition_count": self.registered_partition_count,
            "planned_materialization_event_count": self.planned_materialization_count,
            "planned_check_event_count": self.planned_check_count,
            "planned_event_count": self.planned_event_count,
            "precondition_errors": list(self.precondition_errors),
            "failed_date_count": len(failed),
            "failed_date_samples": failed[:10],
            "should_stop": self.should_stop,
        }


@dataclass(frozen=True, slots=True)
class GoldDcDailyTechnicalEventReport:
    plan: GoldDcDailyTechnicalEventPlan
    mode: str
    confirmed: bool
    reported_materialization_count: int = 0
    reported_check_count: int = 0
    skipped_materialization_count: int = 0
    skipped_check_count: int = 0

    @property
    def reported_event_count(self) -> int:
        return self.reported_materialization_count + self.reported_check_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "confirmed": self.confirmed,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "reported_event_count": self.reported_event_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "plan": self.plan.to_dict(),
        }


def _expected_dates_from_calendar(
    connection,
    *,
    lake_root: Path,
    start_date: str,
    end_date: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        SELECT CAST(trade_date AS DATE)::VARCHAR
        FROM {read_parquet(silver_trade_calendar_path(lake_root), hive_partitioning=False)}
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
        GROUP BY CAST(trade_date AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _sample_dates(expected_dates: Sequence[str]) -> tuple[str, ...]:
    if not expected_dates:
        return ()
    candidates = (expected_dates[0], expected_dates[len(expected_dates) // 2], expected_dates[-1])
    return tuple(dict.fromkeys(candidates))


def _load_audit_report(path: Path) -> dict[str, Any]:
    import json

    if not path.exists():
        raise FileNotFoundError(f"missing Gold audit report: {path}")
    report = json.loads(path.read_text())
    if report.get("should_stop") is not False:
        raise ValueError(f"Gold audit report is not green: {path}")
    if report.get("expected_date_count") != 611 or report.get("target_file_count") != 611:
        raise ValueError("Gold audit report does not cover exactly 611 partitions")
    return report


def plan_gold_dc_daily_technical_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    audit_report_path: Path,
    duckdb_resource: DuckDBResource,
    mode: str = "full",
    check_window_size: int = GOLD_DC_DAILY_TECHNICAL_EVENT_WINDOW_SIZE,
) -> GoldDcDailyTechnicalEventPlan:
    if mode not in {"full", "sample"}:
        raise ValueError(f"unsupported event plan mode: {mode}")
    if check_window_size != GOLD_DC_DAILY_TECHNICAL_EVENT_WINDOW_SIZE:
        raise ValueError("Gold event check window is fixed at 20 trade dates")

    audit_report = _load_audit_report(audit_report_path)
    with duckdb_resource.connect() as connection:
        expected_dates = _expected_dates_from_calendar(
            connection,
            lake_root=lake_root,
            start_date=str(audit_report["expected_start_date"]),
            end_date=str(audit_report["expected_end_date"]),
        )
        audits = batch_gold_dc_daily_technical_audit(
            connection=connection,
            lake_root=lake_root,
            trade_dates=expected_dates,
        )

    recent_dates = expected_dates[-check_window_size:]
    if mode == "sample":
        selected_materializations = _sample_dates(expected_dates)
        selected_checks = (expected_dates[-1],)
    else:
        selected_materializations = expected_dates
        selected_checks = recent_dates

    registered = tuple(
        sorted(str(value) for value in instance.get_dynamic_partitions(GOLD_DC_DAILY_TECHNICAL_PARTITION_SET))
    )
    registered_set = set(registered)
    precondition_errors: list[str] = []
    missing_registered = set(expected_dates) - registered_set
    if missing_registered:
        precondition_errors.append(
            "registered partition set is missing expected dates: "
            + ",".join(sorted(missing_registered)[:10])
        )

    existing_materialized = tuple(
        sorted(set(expected_dates) & set(instance.get_materialized_partitions(GOLD_DC_DAILY_TECHNICAL_ASSET_KEY)))
    )
    readiness_spec = AssetReadinessSpec(
        GOLD_DC_DAILY_TECHNICAL_ASSET_KEY,
        (GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,),
    )
    existing_ready_checks = tuple(
        trade_date
        for trade_date in recent_dates
        if asset_readiness_status(instance, readiness_spec, partition_key=trade_date).ready
    )
    if len(expected_dates) != 611:
        precondition_errors.append(f"expected date count is {len(expected_dates)}, not 611")
    if any(not audits[trade_date].passed for trade_date in expected_dates):
        precondition_errors.append("current Gold lake audit is not green")
    if any(not gold_dc_daily_technical_path(lake_root, trade_date).is_file() for trade_date in expected_dates):
        precondition_errors.append("one or more Gold target files are missing")

    return GoldDcDailyTechnicalEventPlan(
        lake_root=lake_root,
        audit_report_path=audit_report_path,
        expected_trade_dates=expected_dates,
        recent_check_trade_dates=recent_dates,
        selected_materialization_trade_dates=tuple(selected_materializations),
        selected_check_trade_dates=tuple(selected_checks),
        existing_materialized_trade_dates=existing_materialized,
        existing_ready_check_trade_dates=existing_ready_checks,
        audits=audits,
        registered_partition_count=len(registered),
        precondition_errors=tuple(dict.fromkeys(precondition_errors)),
    )


def report_gold_dc_daily_technical_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    audit_report_path: Path,
    duckdb_resource: DuckDBResource,
    mode: str = "full",
    dry_run: bool = True,
    confirm_event_write: bool = False,
) -> GoldDcDailyTechnicalEventReport:
    plan = plan_gold_dc_daily_technical_events(
        instance=instance,
        lake_root=lake_root,
        audit_report_path=audit_report_path,
        duckdb_resource=duckdb_resource,
        mode=mode,
    )
    if dry_run:
        return GoldDcDailyTechnicalEventReport(plan=plan, mode=mode, confirmed=False)
    if not confirm_event_write:
        raise ValueError("event apply requires --confirm-event-write")
    if plan.should_stop:
        raise ValueError(
            "Gold event apply is blocked: "
            + "; ".join(plan.precondition_errors[:10])
        )

    existing_materialized = set(plan.existing_materialized_trade_dates)
    existing_ready_checks = set(plan.existing_ready_check_trade_dates)
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0

    for trade_date in plan.selected_materialization_trade_dates:
        if trade_date in existing_materialized:
            skipped_materializations += 1
            continue
        _report_materialization_event(plan=plan, instance=instance, trade_date=trade_date)
        existing_materialized.add(trade_date)
        reported_materializations += 1

    for trade_date in plan.selected_check_trade_dates:
        if trade_date in existing_ready_checks:
            skipped_checks += 1
            continue
        _report_check_event(plan=plan, instance=instance, trade_date=trade_date)
        reported_checks += 1

    return GoldDcDailyTechnicalEventReport(
        plan=plan,
        mode=mode,
        confirmed=True,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
    )


def _report_materialization_event(
    *,
    plan: GoldDcDailyTechnicalEventPlan,
    instance: dg.DagsterInstance,
    trade_date: str,
) -> None:
    audit = plan.audits[trade_date]
    path = gold_dc_daily_technical_path(plan.lake_root, trade_date)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=GOLD_DC_DAILY_TECHNICAL_ASSET_KEY,
            partition=trade_date,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=audit.checked_row_count,
                observed_columns=tuple(column.name for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA),
                extra_metadata={
                    "source_method": "silver_dc_daily_derived",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "partition_key": trade_date,
                    "gold_audit_report_path": str(plan.audit_report_path),
                },
            ),
        )
    )


def _latest_materialization(instance: dg.DagsterInstance, trade_date: str):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=GOLD_DC_DAILY_TECHNICAL_ASSET_KEY,
            asset_partitions=[trade_date],
        ),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"materialization was not recorded for {trade_date}")
    return result.records[0]


def _report_check_event(
    *,
    plan: GoldDcDailyTechnicalEventPlan,
    instance: dg.DagsterInstance,
    trade_date: str,
) -> None:
    audit = plan.audits[trade_date]
    materialization = _latest_materialization(instance, trade_date)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    path = gold_dc_daily_technical_path(plan.lake_root, trade_date)
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=GOLD_DC_DAILY_TECHNICAL_ASSET_KEY,
            check_name=GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
            passed=True,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=audit.checked_row_count,
                failed_row_count=0,
                file_path=path,
                extra_metadata={
                    "source_method": "silver_dc_daily_derived",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "partition_key": trade_date,
                    "gold_audit_report_path": str(plan.audit_report_path),
                    "reason_code": "ready",
                },
            ),
            blocking=True,
            partition=trade_date,
            target_materialization_data=target,
        )
    )


__all__ = [
    "GOLD_DC_DAILY_TECHNICAL_ASSET_KEY",
    "GOLD_DC_DAILY_TECHNICAL_CHECK_NAME",
    "GOLD_DC_DAILY_TECHNICAL_EVENT_WINDOW_SIZE",
    "GoldDcDailyTechnicalEventPlan",
    "GoldDcDailyTechnicalEventReport",
    "plan_gold_dc_daily_technical_events",
    "report_gold_dc_daily_technical_events",
]
