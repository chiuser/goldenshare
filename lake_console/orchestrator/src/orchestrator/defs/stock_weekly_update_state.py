"""Bounded event bindings and current-file identity for weekly scheduling."""

import tempfile
from pathlib import Path

import dagster as dg
from dagster._core.event_api import PartitionKeyFilter

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_succeeded,
)
from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_weekly import (
    weekly_asset_key,
    weekly_check_names,
)
from orchestrator.defs.sensors.readiness import (
    RAW_STOCK_DAILY_READINESS_SPEC,
    SILVER_STOCK_IDENTITY_MAP_READINESS_SPEC,
    _check_result_for_materialization_ids,
)
from orchestrator.defs.stock_weekly_update import WEEKLY_UPDATE_POLICY
from orchestrator.defs.stock_weekly_update_execution import read_weekly_control


def weekly_event_binding(instance, asset_key, names, partition=None):
    """One materialization and one batch check lookup, including failed/planned checks."""
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key, asset_partitions=[partition] if partition else None
        ),
        limit=1,
    ).records
    if not records:
        return None, False
    record = records[0]
    checks = instance.event_log_storage.get_latest_asset_check_execution_by_key(
        [dg.AssetCheckKey(asset_key, name) for name in names],
        partition_filter=PartitionKeyFilter(key=partition) if partition else None,
    )
    ready = len(checks) == len(names)
    for check in checks.values():
        evaluation = asset_check_record_evaluation(check)
        target = getattr(evaluation, "target_materialization_data", None)
        if (
            not asset_check_record_succeeded(check)
            or not getattr(evaluation, "blocking", False)
            or getattr(target, "storage_id", None) != record.storage_id
        ):
            ready = False
    return record, ready


def weekly_upstream_events_ready(instance, days):
    if not days or len(days) > WEEKLY_UPDATE_POLICY.max_daily_files:
        return False
    identity = SILVER_STOCK_IDENTITY_MAP_READINESS_SPEC
    _, ready = weekly_event_binding(
        instance, identity.asset_key, identity.blocking_check_names
    )
    if not ready:
        return False
    daily = RAW_STOCK_DAILY_READINESS_SPEC
    # Current stock Raw checks bind dates through target materialization identity,
    # not through check-event partition. Mirror that contract in one bounded batch.
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=daily.asset_key, asset_partitions=list(days)),
        limit=len(days) * WEEKLY_UPDATE_POLICY.max_materialization_versions_per_period,
    ).records
    latest = {}
    for record in records:
        latest.setdefault(record.partition_key, record)
    if set(latest) != set(days):
        return False
    ids = {record.storage_id for record in latest.values()}
    results = {storage_id: {} for storage_id in ids}
    for name in daily.blocking_check_names:
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(daily.asset_key, name),
            limit=WEEKLY_UPDATE_POLICY.max_upstream_check_records,
        )
        for record in history:
            matched = _check_result_for_materialization_ids(record, ids)
            if matched is None:
                continue
            storage_id, passed = matched
            results[storage_id].setdefault(name, passed)
    return all(
        len(values) == len(daily.blocking_check_names) and all(values.values())
        for values in results.values()
    )


def weekly_daily_intent_submitted(instance, source, run_key):
    from dagster._core.storage.tags import RUN_KEY_TAG

    from orchestrator.defs.run_contracts.stock_weekly import weekly_job_name

    return bool(
        instance.get_runs(
            filters=dg.RunsFilter(
                job_name=weekly_job_name(source), tags={RUN_KEY_TAG: run_key}
            ),
            limit=1,
        )
    )


def weekly_period_status(instance, root, source, week):
    path = partition_path(root, source, week)
    record, ready = weekly_event_binding(
        instance,
        dg.AssetKey(weekly_asset_key(source)),
        weekly_check_names(source),
        week,
    )
    if record is None:
        return "orphan_file" if path.exists() else "missing"
    if not ready:
        return "checks_failed_or_stale"
    value = record.asset_materialization.metadata.get("goldenshare/weekly_delivery")
    delivery = getattr(value, "value", None)
    if not delivery:
        return "delivery_evidence_missing"
    audit_path = Path(delivery["audit_path"])
    if not any(
        audit_path.is_relative_to(parent)
        for parent in (
            Path(DEFAULT_LAKE_STAGING_ROOT),
            Path("/private/tmp"),
            Path(tempfile.gettempdir()).resolve(),
        )
    ):
        raise WeeklyCaptureError("delivery_path_forbidden")
    # Enforce the same bounded control/path contract before reading a signed audit.
    read_weekly_control(audit_path)
    audit = read_audit(audit_path)
    files = [item for item in audit["files"] if item["week"] == week]
    if (
        audit["source"] != source.value
        or audit["target_root"] != str(root)
        or audit["audit_hash"] != delivery["audit_hash"]
        or len(files) != 1
    ):
        raise WeeklyCaptureError("weekly_delivery_identity_mismatch")
    if files[0]["target"] != str(path) or fingerprint(path) != files[0]["sha256"]:
        return "formal_file_changed"
    return "ready"
