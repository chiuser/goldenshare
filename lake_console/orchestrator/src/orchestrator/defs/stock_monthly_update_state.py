"""Monthly event evidence with bounded histories and target-materialization binding."""

import dagster as dg
from dagster._core.storage.tags import RUN_KEY_TAG

from orchestrator.defs.run_contracts.stock_monthly import (
    MONTHLY_UPDATE_POLICY,
    monthly_asset_key,
    monthly_check_names,
    monthly_job_name,
)
from orchestrator.defs.sensors.readiness import (
    RAW_STOCK_DAILY_READINESS_SPEC,
    SILVER_STOCK_IDENTITY_MAP_READINESS_SPEC,
    _check_result_for_materialization_ids,
)
from orchestrator.defs.stock_weekly_update_state import weekly_event_binding


def monthly_upstream_bindings(instance, days):
    policy = MONTHLY_UPDATE_POLICY
    if not days or len(days) > policy.max_daily_files or len(days) != len(set(days)):
        return None
    identity = SILVER_STOCK_IDENTITY_MAP_READINESS_SPEC
    record, ready = weekly_event_binding(
        instance, identity.asset_key, identity.blocking_check_names
    )
    if not ready:
        return None
    daily = RAW_STOCK_DAILY_READINESS_SPEC
    limit = len(days) * policy.max_materialization_versions_per_date
    event_count = 1 + len(identity.blocking_check_names)
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=daily.asset_key, asset_partitions=list(days)),
        limit=limit,
    ).records
    event_count += len(records)
    latest = {}
    for item in records:
        latest.setdefault(item.partition_key, item)
    if set(latest) != set(days):
        return None
    ids = {item.storage_id for item in latest.values()}
    results = {sid: {} for sid in ids}
    for name in daily.blocking_check_names:
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(daily.asset_key, name),
            limit=policy.max_upstream_check_records,
        )
        event_count += len(history)
        if event_count > policy.max_event_records_per_tick:
            return None
        if history and history[0].status.value not in {"SUCCEEDED", "FAILED"}:
            return None
        for check in history:
            matched = _check_result_for_materialization_ids(check, ids)
            if matched:
                sid, passed = matched
                results[sid].setdefault(
                    name, {"passed": passed, "execution_id": check.id}
                )
    if not all(
        len(values) == len(daily.blocking_check_names)
        and all(v["passed"] for v in values.values())
        for values in results.values()
    ):
        return None
    return {
        "identity_materialization_id": record.storage_id,
        "daily_materialization_ids": {
            day: latest[day].storage_id for day in sorted(days)
        },
        "checks": {str(sid): values for sid, values in sorted(results.items())},
    }


def monthly_daily_intent_submitted(instance, source, key):
    return bool(
        instance.get_runs(
            filters=dg.RunsFilter(
                job_name=monthly_job_name(source), tags={RUN_KEY_TAG: key}
            ),
            limit=1,
        )
    )


def monthly_period_status(instance, root, source, month):
    from orchestrator.defs.paths import raw_stock_monthly_path
    from orchestrator.defs.stock_monthly_point import read_month_delivery

    path = raw_stock_monthly_path(root, source, month)
    record, ready = weekly_event_binding(
        instance,
        dg.AssetKey(monthly_asset_key(source)),
        monthly_check_names(source),
        month,
    )
    if record is None:
        return "orphan_file" if path.exists() else "missing"
    if not ready:
        return "checks_failed_or_stale"
    value = record.asset_materialization.metadata.get("goldenshare/monthly_delivery")
    delivery = getattr(value, "value", None)
    if not delivery:
        return "delivery_evidence_missing"
    try:
        read_month_delivery(delivery, root, source, month)
    except (ValueError, KeyError, OSError):
        return "formal_file_or_proof_changed"
    return "ready"
