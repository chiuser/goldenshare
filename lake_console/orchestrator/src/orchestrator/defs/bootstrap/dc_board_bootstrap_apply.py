"""Controlled direct-lake Bootstrap for the board datasets.

This module is intentionally outside Dagster.  It performs the approved M7
file-generation phases only: Raw generation, Raw reconciliation, Silver
generation, and Silver reconciliation.  It never accesses a Dagster instance
and never reports materialization or check events.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from time import perf_counter
from typing import Any

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
from orchestrator.defs.assets.dc_board import (
    DcBoardRawWriteResult,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_rows_streaming,
)
from orchestrator.defs.assets.dc_board_silver import (
    DcBoardSilverWriteResult,
    write_silver_dc_daily_partition,
    write_silver_dc_index_partition,
    write_silver_dc_member_partition,
)
from orchestrator.defs.bootstrap.dc_board_bootstrap import (
    export_dc_member_partition_from_prod_db,
)
from orchestrator.defs.bootstrap.dc_board_bootstrap_plan import (
    DcBoardBootstrapPlanError,
    DcBoardDatePlan,
    build_date_plans,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_trade_calendar_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource, TushareResource


DATASETS = ("dc_index", "dc_member", "dc_daily")
_RAW_READINESS = {
    "dc_index": batch_raw_dc_index_lake_readiness,
    "dc_member": batch_raw_dc_member_lake_readiness,
    "dc_daily": batch_raw_dc_daily_lake_readiness,
}
_SILVER_READINESS = {
    "dc_index": batch_silver_dc_index_lake_readiness,
    "dc_member": batch_silver_dc_member_lake_readiness,
    "dc_daily": batch_silver_dc_daily_lake_readiness,
}
_RAW_PATHS = {
    "dc_index": raw_dc_index_path,
    "dc_member": raw_dc_member_path,
    "dc_daily": raw_dc_daily_path,
}
_SILVER_PATHS = {
    "dc_index": silver_dc_index_path,
    "dc_member": silver_dc_member_path,
    "dc_daily": silver_dc_daily_path,
}
_MIN_FREE_BYTES = 50 * 1024**3
_ESTIMATED_BYTES_PER_SOURCE_ROW = 2_048


class DcBoardBootstrapApplyError(RuntimeError):
    """Raised when a direct Bootstrap phase cannot continue safely."""


@dataclass(frozen=True, slots=True)
class DcBoardBootstrapPhaseReport:
    phase: str
    generated_at: str
    lake_root: str
    batch_size: int
    date_plan_fingerprints: Mapping[str, str]
    entries: tuple[Mapping[str, object], ...]
    batch_reports: tuple[str, ...]
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    totals: Mapping[str, int]
    disk_free_bytes: int
    estimated_required_bytes: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": self.phase,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "batch_size": self.batch_size,
            "date_plan_fingerprints": dict(self.date_plan_fingerprints),
            "entries": [dict(entry) for entry in self.entries],
            "batch_reports": list(self.batch_reports),
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "totals": dict(self.totals),
            "disk_free_bytes": self.disk_free_bytes,
            "estimated_required_bytes": self.estimated_required_bytes,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class DcBoardReconciliationReport:
    phase: str
    generated_at: str
    lake_root: str
    date_plan_fingerprints: Mapping[str, str]
    dataset_summaries: tuple[Mapping[str, object], ...]
    staging_paths: tuple[str, ...]
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": self.phase,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "date_plan_fingerprints": dict(self.date_plan_fingerprints),
            "dataset_summaries": [dict(summary) for summary in self.dataset_summaries],
            "staging_paths": list(self.staging_paths),
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _write_json(payload: Mapping[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def write_phase_report(report: DcBoardBootstrapPhaseReport, output_path: Path) -> None:
    _write_json(report.to_dict(), output_path)


def write_reconciliation_report(report: DcBoardReconciliationReport, output_path: Path) -> None:
    _write_json(report.to_dict(), output_path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DcBoardBootstrapApplyError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DcBoardBootstrapApplyError(f"report must contain a JSON object: {path}")
    return payload


def _validate_baseline(payload: Mapping[str, Any], *, lake_root: Path) -> dict[str, dict[str, Any]]:
    if payload.get("should_stop") is not False:
        raise DcBoardBootstrapApplyError("M7 v7 baseline has should_stop=true")
    if payload.get("stop_reason_codes"):
        raise DcBoardBootstrapApplyError("M7 v7 baseline contains stop reasons")
    if payload.get("lake_root") != str(lake_root):
        raise DcBoardBootstrapApplyError(
            f"baseline lake_root mismatch: expected {lake_root}, got {payload.get('lake_root')}"
        )
    if any(bool(item.get("failed")) for item in payload.get("source_audits", ())):
        raise DcBoardBootstrapApplyError("M7 v7 baseline contains failed source audits")
    if any(int(item.get("invalid_existing_count", 0)) for item in payload.get("target_audits", ())):
        raise DcBoardBootstrapApplyError("M7 v7 baseline contains invalid existing targets")
    plans = {}
    for item in payload.get("date_plans", ()):
        dataset = str(item.get("dataset"))
        dates = tuple(str(value) for value in item.get("expected_trade_dates", ()))
        if dataset in plans or not dates or not item.get("fingerprint"):
            raise DcBoardBootstrapApplyError(f"invalid or duplicate baseline date plan: {dataset}")
        plans[dataset] = {
            "dates": dates,
            "fingerprint": str(item["fingerprint"]),
            "start_date": str(item["start_date"]),
            "end_date": str(item["end_date"]),
        }
    if set(plans) != set(DATASETS):
        raise DcBoardBootstrapApplyError(
            f"baseline date plans must cover {DATASETS}, got {tuple(sorted(plans))}"
        )
    return plans


def _selected_plans(
    *,
    connection,
    lake_root: Path,
    baseline_report: Path,
    datasets: Sequence[str],
    start_date: str | None,
    end_date: str | None,
) -> tuple[DcBoardDatePlan, ...]:
    baseline = _validate_baseline(_load_json(baseline_report), lake_root=lake_root)
    selected = tuple(dict.fromkeys(datasets))
    unknown = tuple(dataset for dataset in selected if dataset not in DATASETS)
    if unknown:
        raise DcBoardBootstrapApplyError(f"unknown dataset(s): {unknown}")
    effective_end = end_date or max(item["end_date"] for item in baseline.values())
    try:
        plans = build_date_plans(
            connection=connection,
            calendar_path=silver_trade_calendar_path(lake_root),
            start_date=start_date,
            end_date=effective_end,
            datasets=selected,
        )
    except (DcBoardBootstrapPlanError, ValueError) as exc:
        raise DcBoardBootstrapApplyError(str(exc)) from exc
    for plan in plans:
        baseline_dates = baseline[plan.dataset]["dates"]
        expected = tuple(
            value
            for value in baseline_dates
            if (start_date is None or value >= start_date)
            and value <= effective_end
        )
        if plan.expected_trade_dates != expected:
            raise DcBoardBootstrapApplyError(
                f"date plan drift for {plan.dataset}: baseline and current calendar differ"
            )
        if plan.start_date != expected[0] or plan.end_date != expected[-1]:
            raise DcBoardBootstrapApplyError(f"date plan bounds drift for {plan.dataset}")
    return plans


def _estimated_required_bytes(payload: Mapping[str, Any], datasets: Sequence[str]) -> int:
    source_rows = payload.get("source_row_count_by_dataset", {})
    return sum(int(source_rows.get(dataset, 0)) for dataset in datasets) * _ESTIMATED_BYTES_PER_SOURCE_ROW


def _assert_disk_space(*, lake_root: Path, required_bytes: int) -> tuple[int, int]:
    usage = shutil.disk_usage(lake_root)
    required = max(_MIN_FREE_BYTES, required_bytes)
    if usage.free < required:
        raise DcBoardBootstrapApplyError(
            f"insufficient lake disk space: free={usage.free}, required={required}"
        )
    return usage.free, required


def _readiness_statuses(*, connection, lake_root: Path, dataset: str, dates: Sequence[str], layer: str):
    helper = _RAW_READINESS[dataset] if layer == "raw" else _SILVER_READINESS[dataset]
    return helper(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=tuple(dates),
        registered_trade_days=tuple(dates),
    ).statuses_by_trade_date


def _assert_targets_safe(
    *, connection, lake_root: Path, dataset: str, dates: Sequence[str], layer: str
) -> dict[str, object]:
    statuses = _readiness_statuses(
        connection=connection, lake_root=lake_root, dataset=dataset, dates=dates, layer=layer
    )
    invalid = tuple(
        trade_date
        for trade_date, status in statuses.items()
        if status.materialized and not status.checks_passed
    )
    if invalid:
        raise DcBoardBootstrapApplyError(
            f"{layer} target conflict for {dataset}: {invalid[:20]}"
        )
    return statuses


def _result_entry(
    *, dataset: str, trade_date: str, action: str, target_path: Path, result: object | None, reason: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset": dataset,
        "trade_date": trade_date,
        "action": action,
        "target_path": str(target_path),
    }
    if reason:
        payload["reason"] = reason
    if isinstance(result, DcBoardRawWriteResult):
        payload["metadata"] = result.to_metadata()
    elif isinstance(result, DcBoardSilverWriteResult):
        payload["metadata"] = result.to_metadata()
    return payload


def _raw_write(
    *, lake_root: Path, duckdb_resource: DuckDBResource, tushare: TushareResource, prod_postgres: ProdPostgresResource, dataset: str, trade_date: str
) -> DcBoardRawWriteResult:
    if dataset == "dc_index":
        return write_dc_index_partition(
            lake_root_path=lake_root, duckdb_resource=duckdb_resource, tushare=tushare, partition_key=trade_date
        )
    if dataset == "dc_daily":
        return write_dc_daily_partition(
            lake_root_path=lake_root, duckdb_resource=duckdb_resource, tushare=tushare, partition_key=trade_date
        )
    if dataset == "dc_member":
        return export_dc_member_partition_from_prod_db(
            lake_root_path=lake_root,
            duckdb_resource=duckdb_resource,
            prod_postgres=prod_postgres,
            partition_key=trade_date,
        )
    raise DcBoardBootstrapApplyError(f"unsupported Raw dataset: {dataset}")


def _silver_write(*, lake_root: Path, duckdb_resource: DuckDBResource, dataset: str, trade_date: str) -> DcBoardSilverWriteResult:
    writers = {
        "dc_index": write_silver_dc_index_partition,
        "dc_member": write_silver_dc_member_partition,
        "dc_daily": write_silver_dc_daily_partition,
    }
    try:
        return writers[dataset](lake_root_path=lake_root, duckdb=duckdb_resource, partition_key=trade_date)
    except KeyError as exc:
        raise DcBoardBootstrapApplyError(f"unsupported Silver dataset: {dataset}") from exc


def _phase_report(
    *, phase: str, lake_root: Path, plans: Sequence[DcBoardDatePlan], entries: Sequence[Mapping[str, object]], batch_reports: Sequence[str], batch_size: int, disk_free_bytes: int, estimated_required_bytes: int, started: float
) -> DcBoardBootstrapPhaseReport:
    totals = {
        "expected_dates": sum(len(plan.expected_trade_dates) for plan in plans),
        "written_count": sum(entry.get("action") == "written" for entry in entries),
        "skipped_count": sum(entry.get("action") == "skipped" for entry in entries),
        "entry_count": len(entries),
    }
    return DcBoardBootstrapPhaseReport(
        phase=phase,
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        batch_size=batch_size,
        date_plan_fingerprints={plan.dataset: plan.fingerprint for plan in plans},
        entries=tuple(entries),
        batch_reports=tuple(batch_reports),
        should_stop=False,
        stop_reason_codes=(),
        totals=totals,
        disk_free_bytes=disk_free_bytes,
        estimated_required_bytes=estimated_required_bytes,
        elapsed_ms=(perf_counter() - started) * 1000,
    )


def run_raw_bootstrap(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    baseline_report: Path,
    report_dir: Path,
    datasets: Sequence[str] = DATASETS,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int = 20,
) -> DcBoardBootstrapPhaseReport:
    if batch_size <= 0 or batch_size > 20:
        raise DcBoardBootstrapApplyError("batch_size must be between 1 and 20")
    baseline_payload = _load_json(baseline_report)
    required_bytes = _estimated_required_bytes(baseline_payload, datasets)
    started = perf_counter()
    entries: list[Mapping[str, object]] = []
    batch_reports: list[str] = []
    with duckdb_resource.connect() as connection:
        plans = _selected_plans(
            connection=connection,
            lake_root=lake_root,
            baseline_report=baseline_report,
            datasets=datasets,
            start_date=start_date,
            end_date=end_date,
        )
        disk_free, required = _assert_disk_space(lake_root=lake_root, required_bytes=required_bytes)
        for plan in plans:
            dates = plan.expected_trade_dates
            for batch_number, offset in enumerate(range(0, len(dates), batch_size), start=1):
                batch_dates = dates[offset : offset + batch_size]
                statuses = _assert_targets_safe(
                    connection=connection,
                    lake_root=lake_root,
                    dataset=plan.dataset,
                    dates=batch_dates,
                    layer="raw",
                )
                batch_entries: list[Mapping[str, object]] = []
                for trade_date in batch_dates:
                    status = statuses[trade_date]
                    if status.materialized:
                        target = _RAW_PATHS[plan.dataset](lake_root, trade_date)
                        entry = _result_entry(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            action="skipped",
                            target_path=target,
                            result=None,
                            reason="existing_valid_target",
                        )
                    else:
                        result = _raw_write(
                            lake_root=lake_root,
                            duckdb_resource=duckdb_resource,
                            tushare=tushare,
                            prod_postgres=prod_postgres,
                            dataset=plan.dataset,
                            trade_date=trade_date,
                        )
                        entry = _result_entry(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            action="written",
                            target_path=result.target_path,
                            result=result,
                        )
                    entries.append(entry)
                    batch_entries.append(entry)
                batch_path = report_dir / f"dc_board_m7_raw_batch_{plan.dataset}_{batch_number:04d}.json"
                _write_json(
                    {
                        "schema_version": 1,
                        "phase": "raw",
                        "dataset": plan.dataset,
                        "batch_number": batch_number,
                        "trade_dates": list(batch_dates),
                        "entries": [dict(entry) for entry in batch_entries],
                    },
                    batch_path,
                )
                batch_reports.append(str(batch_path))
        report = _phase_report(
            phase="raw",
            lake_root=lake_root,
            plans=plans,
            entries=entries,
            batch_reports=batch_reports,
            batch_size=batch_size,
            disk_free_bytes=disk_free,
            estimated_required_bytes=required,
            started=started,
        )
    return report


def _reconciliation(
    *, phase: str, lake_root: Path, duckdb_resource: DuckDBResource, baseline_report: Path, batch_report: Path, layer: str, datasets: Sequence[str], start_date: str | None, end_date: str | None
) -> DcBoardReconciliationReport:
    started = perf_counter()
    baseline_payload = _load_json(baseline_report)
    batch_payload = _load_json(batch_report)
    entries = tuple(batch_payload.get("entries", ()))
    baseline_source_rows = baseline_payload.get("source_row_count_by_dataset", {})
    with duckdb_resource.connect() as connection:
        plans = _selected_plans(
            connection=connection,
            lake_root=lake_root,
            baseline_report=baseline_report,
            datasets=datasets,
            start_date=start_date,
            end_date=end_date,
        )
        summaries: list[Mapping[str, object]] = []
        stop_reasons: list[str] = []
        for plan in plans:
            statuses = _readiness_statuses(
                connection=connection,
                lake_root=lake_root,
                dataset=plan.dataset,
                dates=plan.expected_trade_dates,
                layer=layer,
            )
            missing = tuple(date_key for date_key, status in statuses.items() if not status.materialized)
            invalid = tuple(
                date_key for date_key, status in statuses.items() if status.materialized and not status.checks_passed
            )
            report_dates = {
                str(entry.get("trade_date"))
                for entry in entries
                if entry.get("dataset") == plan.dataset
            }
            missing_reports = tuple(date_key for date_key in plan.expected_trade_dates if date_key not in report_dates)
            observed_row_count = sum(
                int(status.summary.get("checked_row_count", 0))
                for status in statuses.values()
            )
            baseline_row_count = int(baseline_source_rows.get(plan.dataset, 0))
            row_count_delta = observed_row_count - baseline_row_count
            summary = {
                "dataset": plan.dataset,
                "layer": layer,
                "expected_count": len(plan.expected_trade_dates),
                "ready_count": sum(status.ready for status in statuses.values()),
                "observed_row_count": observed_row_count,
                "baseline_source_row_count": baseline_row_count,
                "row_count_delta": row_count_delta,
                "missing_count": len(missing),
                "invalid_count": len(invalid),
                "missing_report_count": len(missing_reports),
                "missing_sample": list(missing[:20]),
                "invalid_sample": list(invalid[:20]),
                "missing_report_sample": list(missing_reports[:20]),
            }
            summaries.append(summary)
            if missing:
                stop_reasons.append(f"{layer}_missing_{plan.dataset}")
            if invalid:
                stop_reasons.append(f"{layer}_invalid_{plan.dataset}")
            if missing_reports:
                stop_reasons.append(f"{phase}_report_incomplete_{plan.dataset}")
            if layer == "raw" and row_count_delta != 0:
                stop_reasons.append(f"raw_row_count_mismatch_{plan.dataset}")
        staging_paths = tuple(
            str(path)
            for root_name in ("raw", "silver")
            for path in (lake_root / root_name / "board").rglob("*.tmp")
            if path.is_file()
        )
    if staging_paths:
        stop_reasons.append("staging_residue")
    return DcBoardReconciliationReport(
        phase=phase,
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        date_plan_fingerprints={plan.dataset: plan.fingerprint for plan in plans},
        dataset_summaries=tuple(summaries),
        staging_paths=staging_paths,
        should_stop=bool(stop_reasons),
        stop_reason_codes=tuple(dict.fromkeys(stop_reasons)),
        elapsed_ms=(perf_counter() - started) * 1000,
    )


def run_raw_reconciliation(**kwargs: Any) -> DcBoardReconciliationReport:
    return _reconciliation(phase="raw_audit", layer="raw", **kwargs)


def run_silver_bootstrap(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    baseline_report: Path,
    raw_audit_report: Path,
    report_dir: Path,
    datasets: Sequence[str] = DATASETS,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int = 20,
) -> DcBoardBootstrapPhaseReport:
    raw_audit = _load_json(raw_audit_report)
    if raw_audit.get("should_stop") is not False:
        raise DcBoardBootstrapApplyError("Raw reconciliation is not green; Silver generation is blocked")
    if batch_size <= 0 or batch_size > 20:
        raise DcBoardBootstrapApplyError("batch_size must be between 1 and 20")
    baseline_payload = _load_json(baseline_report)
    required_bytes = _estimated_required_bytes(baseline_payload, datasets)
    started = perf_counter()
    entries: list[Mapping[str, object]] = []
    batch_reports: list[str] = []
    with duckdb_resource.connect() as connection:
        plans = _selected_plans(
            connection=connection,
            lake_root=lake_root,
            baseline_report=baseline_report,
            datasets=datasets,
            start_date=start_date,
            end_date=end_date,
        )
        disk_free, required = _assert_disk_space(lake_root=lake_root, required_bytes=required_bytes)
        for plan in plans:
            dates = plan.expected_trade_dates
            for batch_number, offset in enumerate(range(0, len(dates), batch_size), start=1):
                batch_dates = dates[offset : offset + batch_size]
                statuses = _assert_targets_safe(
                    connection=connection,
                    lake_root=lake_root,
                    dataset=plan.dataset,
                    dates=batch_dates,
                    layer="silver",
                )
                batch_entries: list[Mapping[str, object]] = []
                for trade_date in batch_dates:
                    status = statuses[trade_date]
                    target = lake_root / "silver" / "board" / plan.dataset / f"trade_date={trade_date}" / "part-000.parquet"
                    if status.materialized:
                        entry = _result_entry(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            action="skipped",
                            target_path=target,
                            result=None,
                            reason="existing_valid_target",
                        )
                    else:
                        result = _silver_write(
                            lake_root=lake_root,
                            duckdb_resource=duckdb_resource,
                            dataset=plan.dataset,
                            trade_date=trade_date,
                        )
                        entry = _result_entry(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            action="written",
                            target_path=result.target_file_path,
                            result=result,
                        )
                    entries.append(entry)
                    batch_entries.append(entry)
                batch_path = report_dir / f"dc_board_m7_silver_batch_{plan.dataset}_{batch_number:04d}.json"
                _write_json(
                    {
                        "schema_version": 1,
                        "phase": "silver",
                        "dataset": plan.dataset,
                        "batch_number": batch_number,
                        "trade_dates": list(batch_dates),
                        "entries": [dict(entry) for entry in batch_entries],
                    },
                    batch_path,
                )
                batch_reports.append(str(batch_path))
        report = _phase_report(
            phase="silver",
            lake_root=lake_root,
            plans=plans,
            entries=entries,
            batch_reports=batch_reports,
            batch_size=batch_size,
            disk_free_bytes=disk_free,
            estimated_required_bytes=required,
            started=started,
        )
    return report


def run_silver_reconciliation(**kwargs: Any) -> DcBoardReconciliationReport:
    return _reconciliation(phase="silver_audit", layer="silver", **kwargs)


def run_final_reconciliation(
    *, lake_root: Path, raw_report: Path, silver_report: Path, output_path: Path
) -> dict[str, object]:
    raw = _load_json(raw_report)
    silver = _load_json(silver_report)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lake_root": str(lake_root),
        "raw": raw,
        "silver": silver,
        "should_stop": bool(raw.get("should_stop") or silver.get("should_stop")),
        "stop_reason_codes": list(dict.fromkeys([
            *raw.get("stop_reason_codes", []),
            *silver.get("stop_reason_codes", []),
        ])),
    }
    _write_json(payload, output_path)
    return payload


__all__ = [
    "DATASETS",
    "DcBoardBootstrapApplyError",
    "DcBoardBootstrapPhaseReport",
    "DcBoardReconciliationReport",
    "run_final_reconciliation",
    "run_raw_bootstrap",
    "run_raw_reconciliation",
    "run_silver_bootstrap",
    "run_silver_reconciliation",
    "write_phase_report",
    "write_reconciliation_report",
]
