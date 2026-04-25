from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from src.db import SessionLocal
from src.foundation.datasets.registry import get_dataset_definition
from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_schedule import JobSchedule


TIME_KEYS = {"trade_date", "start_date", "end_date", "month", "start_month", "end_month", "date_field"}
TECHNICAL_KEYS = {"dataset_key", "action", "time_input", "filters", "run_scope", "run_profile", "correlation_id"}


@dataclass(frozen=True, slots=True)
class MigrationSummary:
    scanned_executions: int = 0
    migrated_executions: int = 0
    scanned_schedules: int = 0
    migrated_schedules: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Ops dataset execution refs to dataset_action/*.maintain.")
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = parser.parse_args()

    with SessionLocal() as session:
        summary = migrate(session, apply=args.apply)

    mode = "apply" if args.apply else "dry-run"
    print(
        f"migrate-ops-dataset-maintenance-actions mode={mode} "
        f"scanned_executions={summary.scanned_executions} migrated_executions={summary.migrated_executions} "
        f"scanned_schedules={summary.scanned_schedules} migrated_schedules={summary.migrated_schedules}"
    )


def migrate(session, *, apply: bool = False) -> MigrationSummary:  # type: ignore[no-untyped-def]
    scanned_executions = 0
    migrated_executions = 0
    for execution in session.query(JobExecution).all():
        scanned_executions += 1
        if _migrate_record(execution, apply=apply):
            migrated_executions += 1

    scanned_schedules = 0
    migrated_schedules = 0
    for schedule in session.query(JobSchedule).all():
        scanned_schedules += 1
        if _migrate_record(schedule, apply=apply):
            migrated_schedules += 1

    if apply:
        session.commit()
    else:
        session.rollback()
    return MigrationSummary(
        scanned_executions=scanned_executions,
        migrated_executions=migrated_executions,
        scanned_schedules=scanned_schedules,
        migrated_schedules=migrated_schedules,
    )


def _migrate_record(record: Any, *, apply: bool) -> bool:
    spec_type = str(getattr(record, "spec_type", "") or "")
    spec_key = str(getattr(record, "spec_key", "") or "")
    if spec_type == "dataset_action" and spec_key.endswith(".maintain"):
        return False
    if spec_type != "job":
        return False

    dataset_key = _dataset_key_from_legacy_spec(spec_key)
    if dataset_key is None:
        return False
    try:
        get_dataset_definition(dataset_key)
    except KeyError:
        return False

    if apply:
        params_json = dict(getattr(record, "params_json", None) or {})
        record.spec_type = "dataset_action"
        record.spec_key = f"{dataset_key}.maintain"
        if hasattr(record, "dataset_key"):
            record.dataset_key = dataset_key
        record.params_json = _normalize_params(dataset_key=dataset_key, params_json=params_json)
    return True


def _dataset_key_from_legacy_spec(spec_key: str) -> str | None:
    prefix, separator, suffix = spec_key.partition(".")
    if not separator:
        return None
    old_prefixes = {
        "sync" + "_daily",
        "sync" + "_history",
        "sync" + "_minute_history",
        "backfill" + "_trade_cal",
        "backfill" + "_equity_series",
        "backfill" + "_by_trade_date",
        "backfill" + "_by_date_range",
        "backfill" + "_by_month",
        "backfill" + "_fund_series",
        "backfill" + "_index_series",
        "backfill" + "_low_frequency",
    }
    return suffix if prefix in old_prefixes else None


def _normalize_params(*, dataset_key: str, params_json: dict[str, Any]) -> dict[str, Any]:
    time_input = params_json.get("time_input")
    filters = params_json.get("filters")
    if not isinstance(time_input, dict):
        time_input = _infer_time_input(params_json)
    if not isinstance(filters, dict):
        filters = {
            key: value
            for key, value in params_json.items()
            if key not in TIME_KEYS and key not in TECHNICAL_KEYS
        }

    normalized = dict(filters)
    for key in TIME_KEYS:
        if key in params_json:
            normalized[key] = params_json[key]
    normalized.update(
        {
            "dataset_key": dataset_key,
            "action": "maintain",
            "time_input": time_input,
            "filters": filters,
        }
    )
    return normalized


def _infer_time_input(params_json: dict[str, Any]) -> dict[str, Any]:
    if params_json.get("start_month") or params_json.get("end_month"):
        return {
            "mode": "range",
            "start_month": params_json.get("start_month"),
            "end_month": params_json.get("end_month"),
        }
    if params_json.get("start_date") or params_json.get("end_date"):
        return {
            "mode": "range",
            "start_date": params_json.get("start_date"),
            "end_date": params_json.get("end_date"),
        }
    if params_json.get("month"):
        return {"mode": "point", "month": params_json.get("month")}
    if params_json.get("trade_date"):
        return {"mode": "point", "trade_date": params_json.get("trade_date")}
    return {"mode": "none"}


if __name__ == "__main__":
    main()
