"""Offline publication of audited history; no source or Lake writes."""

from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    current_daily_basic_check_records,
    delivery_metadata,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_succeeded,
)
from orchestrator.defs.bootstrap.daily_basic_history import (
    _safe_root,
    _validate_plan,
    seal_history_report,
    verify_history_report,
)
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_ASSET,
    DAILY_BASIC_CHECKS,
    DAILY_BASIC_JOB,
    DAILY_BASIC_PARTITIONS,
    DailyBasicValidationError,
)
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
    file_sha256,
)
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.run_contracts.metadata import (
    build_check_metadata,
    build_materialization_metadata,
)

RECENT_CHECK_DAYS = 20
EVENT_DATE_BATCH = 500
EVENT_RECORD_LIMIT = 20_000
EVENT_PLAN_MAX_AGE_SECONDS = 3600
_ACTIVE = [
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]


def _idle(instance):
    if instance.get_runs(
        filters=dg.RunsFilter(job_name=DAILY_BASIC_JOB, statuses=_ACTIVE), limit=1
    ):
        raise DailyBasicValidationError("history_active_run")


def _latest_materializations(instance, dates):
    latest = {}
    returned = 0
    for offset in range(0, len(dates), EVENT_DATE_BATCH):
        batch = dates[offset : offset + EVENT_DATE_BATCH]
        cursor = None
        while True:
            page = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(DAILY_BASIC_ASSET), asset_partitions=batch
                ),
                limit=EVENT_DATE_BATCH,
                cursor=cursor,
            )
            returned += len(page.records)
            if returned > EVENT_RECORD_LIMIT:
                raise DailyBasicValidationError("history_event_read_budget")
            for record in page.records:
                latest.setdefault(record.partition_key, record)
            if set(batch) <= latest.keys() or not page.has_more:
                break
            if page.cursor == cursor or not page.records:
                raise DailyBasicValidationError("history_event_cursor")
            cursor = page.cursor
    return latest


def _history_evidence(plan, audit, item):
    return {
        "delivery_method": "prod_history",
        "source_system": "prod_raw_db",
        "trade_date": item["date"],
        "file_sha256": item["sha256"],
        "source_row_count": item["rows"],
        "code_count": item["rows"],
        "history_plan_fingerprint": plan["fingerprint"],
        "history_export_fingerprint": audit["export_fingerprint"],
        "history_audit_fingerprint": audit["fingerprint"],
    }


def _check_identity(check, record):
    evaluation = asset_check_record_evaluation(check)
    target = getattr(evaluation, "target_materialization_data", None)
    return (
        asset_check_record_succeeded(check)
        and getattr(evaluation, "blocking", False)
        and getattr(target, "storage_id", None) == record.storage_id
        and getattr(target, "run_id", None) == record.event_log_entry.run_id
        and getattr(target, "timestamp", None) == record.event_log_entry.timestamp
    )


def plan_daily_basic_events(instance, connection, plan, audit, promote):
    """Hash all published files; evaluate only the recent twenty, without writes."""
    started = monotonic()
    _validate_plan(plan)
    verify_history_report(audit)
    verify_history_report(promote)
    if (
        audit.get("stage") != "audit"
        or audit.get("passed") is not True
        or promote.get("stage") != "promote"
        or audit.get("plan_fingerprint") != plan["fingerprint"]
        or promote.get("plan_fingerprint") != plan["fingerprint"]
        or sorted(f["date"] for f in audit["files"]) != plan["dates"]
        or sorted(f["date"] for f in promote["files"]) != plan["dates"]
        or audit["rows"] != sum(f["rows"] for f in audit["files"])
    ):
        raise DailyBasicValidationError("history_publication_evidence")
    _idle(instance)
    promoted = {f["date"]: f["sha256"] for f in promote["files"]}
    recent = plan["dates"][-RECENT_CHECK_DAYS:]
    files = []
    for item in audit["files"]:
        day = item["date"]
        path = _safe_root(raw_daily_basic_path(Path(plan["lake_root"]), day))
        if (
            not path.is_file()
            or file_sha256(path) != item["sha256"]
            or promoted[day] != item["sha256"]
        ):
            raise DailyBasicValidationError("history_published_file_changed")
        if not isinstance(item["rows"], int) or item["rows"] <= 0:
            raise DailyBasicValidationError("history_empty_publication")
        evidence = _history_evidence(plan, audit, item)
        if day in recent:
            checked = audit_daily_basic_file(connection, path, day)
            if audit_daily_basic_coverage(path, checked, (), evidence):
                raise DailyBasicValidationError("history_recent_file_contract")
        files.append({"date": day, "path": str(path), "evidence": evidence})
    registered = set(instance.get_dynamic_partitions(DAILY_BASIC_PARTITIONS))
    latest = _latest_materializations(instance, plan["dates"])
    for item in files:
        record = latest.get(item["date"])
        if record and any(
            delivery_metadata(record).get(k) != v for k, v in item["evidence"].items()
        ):
            raise DailyBasicValidationError("history_materialization_conflict")
    keys = [
        dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), name)
        for name in DAILY_BASIC_CHECKS
    ]
    check_ids = {}
    for offset in range(0, len(files), EVENT_DATE_BATCH):
        days = [f["date"] for f in files[offset : offset + EVENT_DATE_BATCH]]
        infos = instance.event_log_storage.get_asset_check_partition_info(
            keys, partition_keys=days
        )
        for info in infos:
            record = latest.get(info.partition_key)
            if (
                record is None
                or info.latest_execution_status.value != "SUCCEEDED"
                or info.latest_target_materialization_storage_id != record.storage_id
            ):
                raise DailyBasicValidationError("history_check_conflict")
            check_ids[f"{info.partition_key}|{info.check_key.name}"] = (
                info.latest_check_event_storage_id
            )
    pending_checks = []
    for day in recent:
        record = latest.get(day)
        checks = current_daily_basic_check_records(instance, day)
        for name in DAILY_BASIC_CHECKS:
            check = checks.get(dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), name))
            if check is None:
                pending_checks.append([day, name])
            elif record is None or not _check_identity(check, record):
                raise DailyBasicValidationError("history_check_target_conflict")
    payload = {
        "stage": "plan-events",
        "history_plan_fingerprint": plan["fingerprint"],
        "audit_fingerprint": audit["fingerprint"],
        "promote_fingerprint": promote["fingerprint"],
        "files": files,
        "recent_dates": recent,
        "missing_registered_dates": sorted(set(plan["dates"]) - registered),
        "materialization_ids": {d: r.storage_id for d, r in sorted(latest.items())},
        "check_ids": dict(sorted(check_ids.items())),
        "pending_materializations": sorted(set(plan["dates"]) - latest.keys()),
        "pending_checks": pending_checks,
    }
    return seal_history_report(
        {
            **payload,
            "state_fingerprint": seal_history_report(payload)["fingerprint"],
            "created_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": monotonic() - started,
            "should_stop": False,
        }
    )


def apply_daily_basic_events(
    instance,
    connection,
    plan,
    audit,
    promote,
    approved,
    *,
    stage,
    apply=False,
    sample_date=None,
):
    if not apply or stage not in ("register", "report-events"):
        raise DailyBasicValidationError("history_event_apply_required")
    verify_history_report(approved)
    age = (
        datetime.now(UTC) - datetime.fromisoformat(approved["created_at"])
    ).total_seconds()
    if not 0 <= age <= EVENT_PLAN_MAX_AGE_SECONDS:
        raise DailyBasicValidationError("history_event_plan_expired")
    fresh = plan_daily_basic_events(instance, connection, plan, audit, promote)
    if fresh["state_fingerprint"] != approved["state_fingerprint"]:
        raise DailyBasicValidationError("history_event_plan_stale")
    if sample_date is not None and (
        stage != "report-events" or sample_date not in fresh["recent_dates"]
    ):
        raise DailyBasicValidationError("history_sample_outside_recent_window")
    if stage == "register":
        dates = fresh["missing_registered_dates"]
        if dates:
            instance.add_dynamic_partitions(DAILY_BASIC_PARTITIONS, dates)
        if set(plan["dates"]) - set(
            instance.get_dynamic_partitions(DAILY_BASIC_PARTITIONS)
        ):
            raise DailyBasicValidationError("history_registration_incomplete")
        return seal_history_report(
            {"stage": stage, "registered_count": len(dates), "event_count": 0}
        )
    if fresh["missing_registered_dates"]:
        raise DailyBasicValidationError("history_missing_registered_dates")
    files = [
        f for f in fresh["files"] if sample_date is None or f["date"] == sample_date
    ]
    written = 0
    for offset in range(0, len(files), EVENT_DATE_BATCH):
        _idle(instance)
        batch = files[offset : offset + EVENT_DATE_BATCH]
        days = [f["date"] for f in batch]
        if set(days) - set(instance.get_dynamic_partitions(DAILY_BASIC_PARTITIONS)):
            raise DailyBasicValidationError("history_registration_changed")
        infos = instance.event_log_storage.get_asset_check_partition_info(
            [
                dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), name)
                for name in DAILY_BASIC_CHECKS
            ],
            partition_keys=days,
        )
        current_check_ids = {
            f"{info.partition_key}|{info.check_key.name}": info.latest_check_event_storage_id
            for info in infos
        }
        approved_check_ids = {
            key: value
            for key, value in fresh["check_ids"].items()
            if key.split("|", 1)[0] in days
        }
        if current_check_ids != approved_check_ids:
            raise DailyBasicValidationError("history_concurrent_check")
        records = _latest_materializations(instance, days)
        for item in batch:
            day, path = item["date"], Path(item["path"])
            if file_sha256(path) != item["evidence"]["file_sha256"]:
                raise DailyBasicValidationError("history_file_changed_before_event")
            if getattr(records.get(day), "storage_id", None) != fresh[
                "materialization_ids"
            ].get(day):
                raise DailyBasicValidationError("history_concurrent_materialization")
            if day in fresh["pending_materializations"]:
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=DAILY_BASIC_ASSET,
                        partition=day,
                        metadata=build_materialization_metadata(
                            uri=path,
                            row_count=item["evidence"]["source_row_count"],
                            extra_metadata={
                                **item["evidence"],
                                "summary": "历史每日指标文件已核实并登记。",
                            },
                        ),
                    )
                )
                written += 1
        records = _latest_materializations(instance, days)
        for item in batch:
            day = item["date"]
            if day not in fresh["recent_dates"]:
                continue
            record = records.get(day)
            if record is None or any(
                delivery_metadata(record).get(k) != v
                for k, v in item["evidence"].items()
            ):
                raise DailyBasicValidationError("history_delivery_not_current")
            path = Path(item["path"])
            checked = audit_daily_basic_file(connection, path, day)
            if audit_daily_basic_coverage(path, checked, (), item["evidence"]):
                raise DailyBasicValidationError("history_file_changed_before_check")
            target = AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id,
                run_id=record.event_log_entry.run_id,
                timestamp=record.event_log_entry.timestamp,
            )
            for name in DAILY_BASIC_CHECKS:
                existing = current_daily_basic_check_records(instance, day).get(
                    dg.AssetCheckKey(dg.AssetKey(DAILY_BASIC_ASSET), name)
                )
                if existing is not None:
                    if not _check_identity(existing, record):
                        raise DailyBasicValidationError("history_concurrent_check")
                    continue
                if (
                    _latest_materializations(instance, [day])[day].storage_id
                    != record.storage_id
                ):
                    raise DailyBasicValidationError(
                        "history_concurrent_materialization"
                    )
                instance.report_runless_asset_event(
                    dg.AssetCheckEvaluation(
                        asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
                        check_name=name,
                        partition=day,
                        passed=True,
                        blocking=True,
                        severity=dg.AssetCheckSeverity.ERROR,
                        target_materialization_data=target,
                        metadata=build_check_metadata(
                            check_scope="reconciliation",
                            checked_row_count=checked.row_count,
                            failed_row_count=0,
                            extra_metadata={
                                "summary": "历史交付文件核验通过。",
                                "delivery_method": "prod_history",
                            },
                        ),
                    )
                )
                written += 1
        print(
            f"daily_basic events completed_dates={min(offset + EVENT_DATE_BATCH, len(files))} total_dates={len(files)} written={written}",
            flush=True,
        )
    return seal_history_report(
        {"stage": stage, "event_count": written, "sample_date": sample_date}
    )
