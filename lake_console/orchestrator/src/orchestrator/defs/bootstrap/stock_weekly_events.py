"""Frozen, bounded weekly runless event reconciliation; no data writes."""

from collections import defaultdict
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import EventRecordsFilter
from dagster._core.events import DagsterEventType

from orchestrator.defs.bootstrap.stock_weekly_candidates import fingerprint
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    check_weekly_cancel,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    STOCK_WEEKLY_PARTITIONS,
    StockWeeklySource,
    WeeklyBudget,
    normalize_week_key,
    stable_weekly_hash,
    weekly_asset_key,
    weekly_check_names,
    weekly_column_specs,
)

TOKEN = "goldenshare/weekly_event_plan"


def _value(metadata, key):
    return getattr(metadata.get(key), "value", None)


def _asset(entry):
    return dg.AssetKey(weekly_asset_key(StockWeeklySource(entry["source"])))


def _delivery(entry):
    return {key: entry[key] for key in ("path", "rows", "audit_path", "audit_hash")}


def _matching_mat(record, entry):
    if record is None:
        return False
    materialization = record.asset_materialization
    delivery = _value(materialization.metadata, "goldenshare/weekly_delivery")
    return (
        materialization.partition == entry["week"]
        and isinstance(delivery, dict)
        and all(delivery.get(key) == value for key, value in _delivery(entry).items())
        and _value(materialization.metadata, "dagster/row_count") == entry["rows"]
    )


def _matching_check(record, name, mat, entry):
    if record is None or mat is None:
        return False
    evaluation = record.event_log_entry.dagster_event.event_specific_data
    target = evaluation.target_materialization_data
    return (
        isinstance(evaluation, AssetCheckEvaluation)
        and evaluation.asset_key == _asset(entry)
        and evaluation.check_name == name
        and evaluation.partition == entry["week"]
        and evaluation.passed
        and evaluation.blocking
        and evaluation.severity == dg.AssetCheckSeverity.ERROR
        and target is not None
        and target.storage_id == mat.storage_id
        and target.run_id == mat.event_log_entry.run_id
        and target.timestamp == mat.event_log_entry.timestamp
        and _value(evaluation.metadata, "goldenshare/checked_row_count")
        == entry["rows"]
    )


def read_weekly_event_state(instance, entries, *, record_cap=None):
    """Batch latest partition state; full check bodies fetched by bounded storage IDs."""
    budget = WeeklyBudget()
    cap = (
        budget.event_record_read_cap
        if record_cap is None
        else min(record_cap, budget.event_record_read_cap)
    )
    groups, state = defaultdict(list), {}
    returned = 0

    def consume(count):
        nonlocal returned
        returned += count
        if returned > cap:
            raise WeeklyCaptureError("event_record_read_cap_exceeded")

    for entry in entries:
        groups[(entry["source"], entry["week"][:4])].append(entry)
    for (source_name, _), group in sorted(groups.items()):
        source = StockWeeklySource(source_name)
        asset = dg.AssetKey(weekly_asset_key(source))
        names = weekly_check_names(source)
        for offset in range(0, len(group), budget.event_partition_batch):
            batch = group[offset : offset + budget.event_partition_batch]
            weeks = [e["week"] for e in batch]
            mats, cursor = {}, None
            while True:
                result = instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=asset, asset_partitions=weeks),
                    limit=min(500, max(1, cap - returned + 1)),
                    cursor=cursor,
                )
                consume(len(result.records))
                for record in result.records:
                    mats.setdefault(record.asset_materialization.partition, record)
                if len(mats) == len(weeks) or not result.has_more:
                    break
                if not result.cursor or result.cursor == cursor:
                    raise WeeklyCaptureError("event_cursor_not_advancing")
                cursor = result.cursor
            infos = instance.event_log_storage.get_asset_check_partition_info(
                [dg.AssetCheckKey(asset, name) for name in names],
                partition_keys=weeks,
            )
            consume(len(infos))
            ids = sorted({i.latest_check_event_storage_id for i in infos})
            evaluations = {}
            for start in range(0, len(ids), 500):
                records = instance.event_log_storage.get_event_records(
                    EventRecordsFilter(
                        DagsterEventType.ASSET_CHECK_EVALUATION,
                        storage_ids=ids[start : start + 500],
                    ),
                    limit=500,
                )
                consume(len(records))
                evaluations.update({r.storage_id: r for r in records})
            checks = {
                (i.partition_key, i.check_key.name): (
                    i.latest_check_event_storage_id,
                    evaluations.get(i.latest_check_event_storage_id),
                )
                for i in infos
            }
            for entry in batch:
                state[(source_name, entry["week"])] = {
                    "mat": mats.get(entry["week"]),
                    "checks": {
                        name: checks.get((entry["week"], name), (None, None))
                        for name in names
                    },
                }
    return state, returned


def freeze_weekly_event_plan(instance, entries, *, instance_identity):
    if not entries or len(entries) * 4 > WeeklyBudget().event_write_cap:
        raise WeeklyCaptureError("event_write_budget_exceeded")
    keys = [(e["source"], normalize_week_key(e["week"])) for e in entries]
    if len(set(keys)) != len(keys):
        raise WeeklyCaptureError("event_entry_duplicate")
    state, returned = read_weekly_event_state(instance, entries)
    registered = set(instance.get_dynamic_partitions(STOCK_WEEKLY_PARTITIONS))
    pending, failed = [], 0
    for entry in entries:
        current = state[(entry["source"], entry["week"])]
        mat = current["mat"]
        mat_matches = _matching_mat(mat, entry)
        checks = current["checks"]
        missing, blocked = [], []
        for name, (_, record) in checks.items():
            if (
                record
                and not record.event_log_entry.dagster_event.event_specific_data.passed
            ):
                failed += 1
            if not mat_matches or not _matching_check(record, name, mat, entry):
                missing.append(name)
                if checks[name][0] is not None:
                    blocked.append(name)
        pending.append(
            {
                **entry,
                "previous_mat_id": mat.storage_id if mat else None,
                "previous_check_ids": {
                    name: value[0] for name, value in checks.items()
                },
                "missing_mat": not mat_matches,
                "missing_checks": missing,
                "blocked_checks": blocked,
            }
        )
    plan = {
        "version": 1,
        "kind": "weekly_event_plan",
        "instance_identity": instance_identity,
        "entries": pending,
        "missing_registrations": sorted({e["week"] for e in entries} - registered),
        "counts": {
            "files": len(entries),
            "rows": sum(e["rows"] for e in entries),
            "materializations": sum(e["missing_mat"] for e in pending),
            "checks": sum(len(e["missing_checks"]) for e in pending),
            "historical_latest_failed": failed,
            "blocked_checks": sum(len(e["blocked_checks"]) for e in pending),
            "records_returned": returned,
        },
    }
    plan["plan_hash"] = stable_weekly_hash(plan)
    return plan


def verify_weekly_event_plan(plan):
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    if (
        plan.get("kind") != "weekly_event_plan"
        or plan.get("version") != 1
        or stable_weekly_hash(body) != plan.get("plan_hash")
    ):
        raise WeeklyCaptureError("event_plan_hash_mismatch")
    entries = plan["entries"]
    if not entries or len(entries) * 4 > WeeklyBudget().event_write_cap:
        raise WeeklyCaptureError("event_write_budget_exceeded")
    if len({(e["source"], e["week"]) for e in entries}) != len(entries):
        raise WeeklyCaptureError("event_entry_duplicate")
    for entry in entries:
        normalize_week_key(entry["week"])
        names = weekly_check_names(StockWeeklySource(entry["source"]))
        if set(entry["missing_checks"]) - set(names) or set(
            entry["previous_check_ids"]
        ) != set(names):
            raise WeeklyCaptureError("event_check_scope_invalid")
    if set(plan["missing_registrations"]) - {e["week"] for e in entries}:
        raise WeeklyCaptureError("event_registration_scope_invalid")


def audit_weekly_readiness_samples(instance, entries):
    """Five representative actual file/check target reads, never a full deep scan."""
    from orchestrator.defs.checks.stock_weekly_checks import audit_weekly_file

    selected = []
    for source in StockWeeklySource:
        group = sorted(
            (e for e in entries if e["source"] == source.value), key=lambda e: e["week"]
        )
        if group:
            selected.append(group[0])
            if source is not StockWeeklySource.ALTERNATE_WEEKLY and len(group) > 1:
                selected.append(group[-1])
    state, _ = read_weekly_event_state(instance, selected)
    samples = []
    for entry in selected:
        current = state[(entry["source"], entry["week"])]
        ready = _matching_mat(current["mat"], entry) and all(
            _matching_check(record, name, current["mat"], entry)
            for name, (_, record) in current["checks"].items()
        )
        if ready:
            audit_weekly_file(
                StockWeeklySource(entry["source"]),
                entry["week"],
                Path(entry["path"]).parents[4],
                delivery=_delivery(entry),
                kind="delivery_reconciliation",
            )
        samples.append(
            {"source": entry["source"], "week": entry["week"], "ready": bool(ready)}
        )
    return samples


def _verify_file(entry):
    if (
        fingerprint(Path(entry["path"])) != entry["sha256"]
        or fingerprint(Path(entry["audit_path"])) != entry["audit_sha256"]
    ):
        raise WeeklyCaptureError("event_formal_evidence_changed")


def apply_weekly_events(
    instance, plan, *, stage, checkpoint, cancel=None, start=0, count=100
):
    """One approved stage and at most 100 writes; persisted events govern replay."""
    verify_weekly_event_plan(plan)
    cancel = cancel or (lambda: False)
    if any(entry["blocked_checks"] for entry in plan["entries"]):
        raise WeeklyCaptureError("event_existing_check_requires_review")
    if stage not in ("register", "materializations", "checks"):
        raise WeeklyCaptureError("event_stage_invalid")
    checkpoint = Path(checkpoint)
    # A journal is progress only, never authorization or a reason to skip a DB read.
    writes, skipped = 0, 0
    cap = WeeklyBudget().event_write_batch
    if (
        type(start) is not int
        or type(count) is not int
        or start < 0
        or not 1 <= count <= cap
    ):
        raise WeeklyCaptureError("event_batch_scope_invalid")
    entries = plan["entries"][start : start + count]
    proof_entries = entries
    if stage == "register":
        selected_weeks = set(plan["missing_registrations"][start : start + count])
        proof_entries = [e for e in plan["entries"] if e["week"] in selected_weeks]
    # Revalidate immutable source proof once per annual audit, not once per check.
    from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit
    from orchestrator.defs.checks.stock_weekly_checks import (
        verify_weekly_delivery_evidence,
    )

    verified = {}
    for entry in proof_entries:
        check_weekly_cancel(cancel)
        _verify_file(entry)
        if entry["audit_path"] not in verified:
            audit = read_audit(Path(entry["audit_path"]))
            if audit["audit_hash"] != entry["audit_hash"]:
                raise WeeklyCaptureError("event_formal_evidence_changed")
            verify_weekly_delivery_evidence(audit)
            verified[entry["audit_path"]] = audit
        audit = verified[entry["audit_path"]]
        matches = [f for f in audit["files"] if f["week"] == entry["week"]]
        if (
            audit["source"] != entry["source"]
            or len(matches) != 1
            or any(
                matches[0].get(field) != entry[key]
                for field, key in (
                    ("target", "path"),
                    ("sha256", "sha256"),
                    ("rows", "rows"),
                    ("logical_hash", "logical_hash"),
                )
            )
        ):
            raise WeeklyCaptureError("event_audit_entry_mismatch")
    if stage == "register":
        weeks = plan["missing_registrations"][start : start + count]
        for entry in plan["entries"]:
            check_weekly_cancel(cancel)
            if entry["week"] in weeks:
                _verify_file(entry)
        existing = set(instance.get_dynamic_partitions(STOCK_WEEKLY_PARTITIONS))
        for week in weeks:
            check_weekly_cancel(cancel)
            if week in existing:
                skipped += 1
                continue
            if writes == cap:
                break
            instance.add_dynamic_partitions(STOCK_WEEKLY_PARTITIONS, [week])
            if not instance.has_dynamic_partition(STOCK_WEEKLY_PARTITIONS, week):
                raise WeeklyCaptureError("event_registration_readback_failed")
            writes += 1
            _atomic_json(
                checkpoint,
                {
                    "plan_hash": plan["plan_hash"],
                    "stage": stage,
                    "last_week": week,
                    "writes": writes,
                },
            )
            check_weekly_cancel(cancel)
        return {"writes": writes, "skipped": skipped}
    for entry in entries:
        if writes == cap:
            break
        check_weekly_cancel(cancel)
        _verify_file(entry)
        if not instance.has_dynamic_partition(STOCK_WEEKLY_PARTITIONS, entry["week"]):
            raise WeeklyCaptureError("event_registration_missing")
        asset = _asset(entry)
        latest = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[entry["week"]]),
            limit=1,
        ).records
        mat = latest[0] if latest else None
        current_id = mat.storage_id if mat else None
        matches = _matching_mat(mat, entry)
        owned = (
            mat
            and _value(mat.asset_materialization.metadata, TOKEN) == plan["plan_hash"]
        )
        if current_id != entry["previous_mat_id"] and not (matches and owned):
            raise WeeklyCaptureError("event_materialization_changed")
        if stage == "materializations":
            if not entry["missing_mat"] or matches:
                skipped += 1
                continue
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=entry["week"],
                    metadata=build_materialization_metadata(
                        uri=entry["path"],
                        row_count=entry["rows"],
                        observed_columns=[
                            s[0]
                            for s in weekly_column_specs(
                                StockWeeklySource(entry["source"])
                            )
                        ],
                        extra_metadata={
                            "goldenshare/weekly_delivery": _delivery(entry),
                            TOKEN: plan["plan_hash"],
                        },
                    ),
                )
            )
            latest = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=asset, asset_partitions=[entry["week"]]
                ),
                limit=1,
            ).records
            if (
                not latest
                or not _matching_mat(latest[0], entry)
                or _value(latest[0].asset_materialization.metadata, TOKEN)
                != plan["plan_hash"]
            ):
                raise WeeklyCaptureError("event_materialization_readback_failed")
            writes += 1
            _atomic_json(
                checkpoint,
                {
                    "plan_hash": plan["plan_hash"],
                    "stage": stage,
                    "source": entry["source"],
                    "week": entry["week"],
                    "writes": writes,
                },
            )
        else:
            if not matches:
                raise WeeklyCaptureError("event_target_materialization_missing")
            for name in entry["missing_checks"]:
                if writes == cap:
                    break
                check_weekly_cancel(cancel)
                _verify_file(entry)
                current, _ = read_weekly_event_state(instance, [entry])
                current = current[(entry["source"], entry["week"])]
                if not current["mat"] or current["mat"].storage_id != mat.storage_id:
                    raise WeeklyCaptureError("event_materialization_changed")
                check_id, check_record = current["checks"][name]
                if _matching_check(check_record, name, mat, entry):
                    if (
                        check_id != entry["previous_check_ids"][name]
                        and _value(
                            check_record.event_log_entry.dagster_event.event_specific_data.metadata,
                            TOKEN,
                        )
                        != plan["plan_hash"]
                    ):
                        raise WeeklyCaptureError("event_check_changed")
                    skipped += 1
                    continue
                if check_id != entry["previous_check_ids"][name]:
                    raise WeeklyCaptureError("event_check_changed")
                scope = (
                    CheckScope.SCHEMA
                    if "file_contract" in name
                    else CheckScope.PARTITION_ALIGNMENT
                    if "key_partition" in name
                    else CheckScope.RECONCILIATION
                )
                instance.report_runless_asset_event(
                    AssetCheckEvaluation(
                        asset_key=asset,
                        check_name=name,
                        partition=entry["week"],
                        passed=True,
                        blocking=True,
                        severity=dg.AssetCheckSeverity.ERROR,
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=mat.storage_id,
                            run_id=mat.event_log_entry.run_id,
                            timestamp=mat.event_log_entry.timestamp,
                        ),
                        metadata=build_check_metadata(
                            check_scope=scope,
                            checked_row_count=entry["rows"],
                            extra_metadata={
                                TOKEN: plan["plan_hash"],
                                "goldenshare/week_end": entry["week"],
                                "goldenshare/reason_code": "ok",
                            },
                        ),
                    )
                )
                after, _ = read_weekly_event_state(instance, [entry])
                readback = after[(entry["source"], entry["week"])]
                if (
                    not readback["mat"]
                    or readback["mat"].storage_id != mat.storage_id
                    or not _matching_check(
                        readback["checks"][name][1], name, mat, entry
                    )
                ):
                    raise WeeklyCaptureError("event_check_readback_failed")
                writes += 1
                _atomic_json(
                    checkpoint,
                    {
                        "plan_hash": plan["plan_hash"],
                        "stage": stage,
                        "source": entry["source"],
                        "week": entry["week"],
                        "check": name,
                        "writes": writes,
                    },
                )
        check_weekly_cancel(cancel)
    return {"writes": writes, "skipped": skipped}
