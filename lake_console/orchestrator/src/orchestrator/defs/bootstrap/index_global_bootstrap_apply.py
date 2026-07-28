"""Approved, bounded Raw/Silver Bootstrap writer for ``index_global``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from time import perf_counter, sleep
from typing import Any

from orchestrator.defs.assets.index_global_raw import (
    fetch_index_global_phase,
    merge_index_global_phase,
)
from orchestrator.defs.assets.index_global_silver import (
    write_silver_index_global_partition,
)
from orchestrator.defs.bootstrap.index_global_bootstrap_plan import (
    IndexGlobalBootstrapDryRunReport,
    IndexGlobalDatePlan,
    run_dry_run,
)
from orchestrator.defs.paths import raw_index_global_path
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_NORMAL_PHASES,
    build_index_global_request_policy,
)


class IndexGlobalBootstrapApplyError(RuntimeError):
    """Raised when the approved Bootstrap cannot continue safely."""


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _audit_dict(report: IndexGlobalBootstrapDryRunReport) -> dict[str, object]:
    return report.to_dict()


def _audit_layer(report: IndexGlobalBootstrapDryRunReport, layer: str) -> Mapping[str, object]:
    for audit in report.target_audits:
        if audit.layer == layer:
            return audit.to_dict()
    raise IndexGlobalBootstrapApplyError(f"missing {layer} audit in Bootstrap report")


def _validate_source_report(
    source_report: Mapping[str, Any],
    *,
    date_plan: IndexGlobalDatePlan,
) -> None:
    if source_report.get("should_stop") is not False:
        raise IndexGlobalBootstrapApplyError("P7B source report is not successful")
    report_plan = source_report.get("date_plan")
    if not isinstance(report_plan, Mapping):
        raise IndexGlobalBootstrapApplyError("P7B source report has no date_plan")
    if report_plan.get("fingerprint") != date_plan.fingerprint:
        raise IndexGlobalBootstrapApplyError(
            "P7B source report fingerprint does not match the Bootstrap date plan"
        )
    expected_phases = len(date_plan.expected_natural_dates) * len(INDEX_GLOBAL_NORMAL_PHASES)
    if source_report.get("attempted_phase_count") != expected_phases:
        raise IndexGlobalBootstrapApplyError("P7B source report phase count is incomplete")
    if source_report.get("successful_phase_count") != expected_phases:
        raise IndexGlobalBootstrapApplyError("P7B source report has unsuccessful phases")
    if source_report.get("failed_phase_count") != 0:
        raise IndexGlobalBootstrapApplyError("P7B source report contains failed phases")


def _required_free_bytes(source_report: Mapping[str, Any]) -> int:
    source_rows = int(source_report.get("source_row_count") or 0)
    return max(1_000_000_000, source_rows * 512 * 2)


def _wait_between_phases(
    *,
    last_finished_at: float | None,
    sleep_fn: Callable[[float], None],
) -> tuple[float | None, float]:
    if last_finished_at is None:
        return None, 0.0
    interval = build_index_global_request_policy().minimum_interval_seconds
    wait_seconds = max(interval - (perf_counter() - last_finished_at), 0.0)
    if wait_seconds:
        sleep_fn(wait_seconds)
    return None, wait_seconds * 1000


def _apply_report_paths(output_dir: Path, apply_id: str) -> dict[str, Path]:
    return {
        "raw_batch": output_dir / f"index_global_m7_raw_batch_{apply_id}.json",
        "raw_audit": output_dir / f"index_global_m7_raw_audit_{apply_id}.json",
        "silver_batch": output_dir / f"index_global_m7_silver_batch_{apply_id}.json",
        "silver_audit": output_dir / f"index_global_m7_silver_audit_{apply_id}.json",
        "final": output_dir / f"index_global_m7_final_reconciliation_{apply_id}.json",
    }


def _base_report(
    *,
    apply_id: str,
    lake_root: Path,
    date_plan: IndexGlobalDatePlan,
    source_report_path: Path,
    required_free_bytes: int,
    free_bytes: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "apply_id": apply_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lake_root": str(lake_root),
        "source_report_path": str(source_report_path),
        "date_plan": date_plan.to_dict(),
        "required_free_bytes": required_free_bytes,
        "free_bytes_at_preflight": free_bytes,
        "source_method": "tushare_index_global_bootstrap_apply",
    }


def run_bootstrap_apply(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    source_report_path: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    batch_size: int = 20,
    apply_id: str | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> dict[str, object]:
    """Write all missing Raw/Silver partitions after strict preflight gates."""

    if batch_size <= 0 or batch_size > 20:
        raise ValueError("batch_size must be between 1 and 20")
    lake_root = lake_root.expanduser().resolve()
    if not lake_root.is_dir():
        raise IndexGlobalBootstrapApplyError(f"lake root is not a directory: {lake_root}")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    date_plan_report = source_report.get("date_plan")
    if not isinstance(date_plan_report, Mapping):
        raise IndexGlobalBootstrapApplyError("P7B source report date_plan is invalid")
    from orchestrator.defs.bootstrap.index_global_bootstrap_plan import build_date_plan

    date_plan = build_date_plan(start_date=start_date, end_date=end_date)
    _validate_source_report(source_report, date_plan=date_plan)
    required_free = _required_free_bytes(source_report)
    free_bytes = shutil.disk_usage(lake_root).free
    if free_bytes < required_free:
        raise IndexGlobalBootstrapApplyError(
            f"insufficient lake disk space: free={free_bytes}, required={required_free}"
        )

    preflight = run_dry_run(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        start_date=date_plan.start_date,
        end_date=date_plan.end_date,
    )
    for layer in ("raw", "silver"):
        audit = _audit_layer(preflight, layer)
        if int(audit["invalid_existing_count"]) != 0:
            raise IndexGlobalBootstrapApplyError(
                f"{layer} has invalid existing targets; formal apply is stopped"
            )

    apply_id = apply_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    report_paths = _apply_report_paths(output_dir, apply_id)
    base = _base_report(
        apply_id=apply_id,
        lake_root=lake_root,
        date_plan=date_plan,
        source_report_path=source_report_path,
        required_free_bytes=required_free,
        free_bytes=free_bytes,
    )
    raw_records: list[dict[str, object]] = []
    silver_records: list[dict[str, object]] = []
    total_throttle_wait_ms = 0.0
    last_phase_finished_at: float | None = None

    for batch_start in range(0, len(date_plan.expected_natural_dates), batch_size):
        batch_dates = date_plan.expected_natural_dates[batch_start : batch_start + batch_size]
        for trade_date in batch_dates:
            target_path = raw_index_global_path(lake_root, trade_date)
            if target_path.exists():
                raw_records.append(
                    {
                        "trade_date": trade_date,
                        "status": "skipped_existing",
                        "target_path": str(target_path),
                    }
                )
                continue

            work_root = Path(mkdtemp(prefix=f".index_global_bootstrap_{apply_id}_", dir=lake_root))
            phase_records: list[dict[str, object]] = []
            try:
                for phase in INDEX_GLOBAL_NORMAL_PHASES:
                    _, wait_ms = _wait_between_phases(
                        last_finished_at=last_phase_finished_at,
                        sleep_fn=sleep_fn,
                    )
                    total_throttle_wait_ms += wait_ms
                    try:
                        fetched = fetch_index_global_phase(
                            tushare=tushare,
                            trade_date=trade_date,
                            probe_phase=phase,
                            request_policy=build_index_global_request_policy(),
                        )
                    finally:
                        last_phase_finished_at = perf_counter()
                    merged = merge_index_global_phase(
                        lake_root_path=work_root,
                        duckdb_resource=duckdb_resource,
                        trade_date=trade_date,
                        probe_phase=phase,
                        phase_rows=fetched.rows,
                        run_id=f"{apply_id}-{trade_date}-{phase}",
                    )
                    phase_records.append(
                        {
                            "phase": phase,
                            "source_row_count": len(fetched.rows),
                            "request_count": fetched.request_count,
                            "page_count": fetched.page_count,
                            "retry_count": fetched.retry_count,
                            "elapsed_ms": round(fetched.elapsed_ms, 3),
                            "output_row_count": merged.output_row_count,
                            "replaced_row_count": merged.replaced_row_count,
                            "source_observation": "empty" if fetched.empty else "rows",
                        }
                    )
                staged_path = raw_index_global_path(work_root, trade_date)
                if target_path.exists():
                    raise IndexGlobalBootstrapApplyError(
                        f"Raw target appeared during apply: {target_path}"
                    )
                target_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, target_path)
                raw_records.append(
                    {
                        "trade_date": trade_date,
                        "status": "written",
                        "target_path": str(target_path),
                        "source_row_count": sum(int(item["source_row_count"]) for item in phase_records),
                        "request_count": sum(int(item["request_count"]) for item in phase_records),
                        "page_count": sum(int(item["page_count"]) for item in phase_records),
                        "retry_count": sum(int(item["retry_count"]) for item in phase_records),
                        "output_row_count": int(phase_records[-1]["output_row_count"]),
                        "replaced_row_count": sum(int(item["replaced_row_count"]) for item in phase_records),
                        "phases": phase_records,
                    }
                )
            finally:
                shutil.rmtree(work_root, ignore_errors=True)

        _write_json(
            report_paths["raw_batch"],
            base
            | {
                "stage": "raw",
                "batch_size": batch_size,
                "completed_batch_end": batch_dates[-1],
                "records": raw_records,
                "throttle_wait_ms": round(total_throttle_wait_ms, 3),
            },
        )

    raw_audit = run_dry_run(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        start_date=date_plan.start_date,
        end_date=date_plan.end_date,
    )
    raw_audit_summary = _audit_layer(raw_audit, "raw")
    _write_json(report_paths["raw_audit"], {"stage": "raw", **_audit_dict(raw_audit)})
    if int(raw_audit_summary["missing_count"]) or int(raw_audit_summary["invalid_existing_count"]):
        raise IndexGlobalBootstrapApplyError("Raw full reconciliation failed")

    for batch_start in range(0, len(date_plan.expected_natural_dates), batch_size):
        batch_dates = date_plan.expected_natural_dates[batch_start : batch_start + batch_size]
        for trade_date in batch_dates:
            target_path = Path(str(lake_root / "silver/index_global" / f"trade_date={trade_date}" / "part-000.parquet"))
            if target_path.exists():
                silver_records.append(
                    {
                        "trade_date": trade_date,
                        "status": "skipped_existing",
                        "target_path": str(target_path),
                    }
                )
                continue
            result = write_silver_index_global_partition(
                lake_root_path=lake_root,
                duckdb_resource=duckdb_resource,
                partition_key=trade_date,
                run_id=f"{apply_id}-{trade_date}-silver",
            )
            silver_records.append(
                {
                    "trade_date": trade_date,
                    "status": "written",
                    "target_path": str(result.target_file_path),
                    "source_row_count": result.source_row_count,
                    "output_row_count": result.output_row_count,
                    "duplicate_removed_count": result.duplicate_removed_count,
                    "rejected_row_count": result.rejected_row_count,
                    "elapsed_ms": round(result.elapsed_ms, 3),
                }
            )
        _write_json(
            report_paths["silver_batch"],
            base
            | {
                "stage": "silver",
                "batch_size": batch_size,
                "completed_batch_end": batch_dates[-1],
                "records": silver_records,
            },
        )

    final_audit = run_dry_run(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        start_date=date_plan.start_date,
        end_date=date_plan.end_date,
    )
    silver_audit_summary = _audit_layer(final_audit, "silver")
    _write_json(report_paths["silver_audit"], {"stage": "silver", **_audit_dict(final_audit)})
    if any(
        int(_audit_layer(final_audit, layer)[key])
        for layer in ("raw", "silver")
        for key in ("missing_count", "invalid_existing_count")
    ):
        raise IndexGlobalBootstrapApplyError("final Raw/Silver reconciliation failed")

    final_report = base | {
        "stage": "final",
        "raw_records": raw_records,
        "silver_records": silver_records,
        "raw_audit": raw_audit_summary,
        "silver_audit": silver_audit_summary,
        "source_report_summary": {
            key: source_report.get(key)
            for key in (
                "attempted_phase_count",
                "successful_phase_count",
                "empty_phase_count",
                "source_row_count",
                "request_count",
                "page_count",
                "retry_count",
                "elapsed_ms",
                "throttle_wait_ms",
            )
        },
        "apply_throttle_wait_ms": round(total_throttle_wait_ms, 3),
        "should_stop": False,
    }
    _write_json(report_paths["final"], final_report)
    return {"report_paths": {key: str(path) for key, path in report_paths.items()}, **final_report}


__all__ = ["IndexGlobalBootstrapApplyError", "run_bootstrap_apply"]
