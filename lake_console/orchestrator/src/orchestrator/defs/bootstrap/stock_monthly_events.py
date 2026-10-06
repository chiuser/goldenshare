"""Frozen, bounded monthly runless event reconciliation; no data writes."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import EventRecordsFilter
from dagster._core.events import DagsterEventType

from orchestrator.defs.bootstrap.stock_monthly_delivery import (
    read_month_bootstrap_delivery,
)
from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    monthly_file_hash,
    read_monthly_json,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_monthly_history import audit_monthly_history
from orchestrator.defs.bootstrap.stock_monthly_history_plan import (
    load_monthly_history_plan,
)
from orchestrator.defs.paths import raw_stock_monthly_path
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    STOCK_MONTHLY_PARTITIONS,
    MonthlyBootstrapIOPolicy,
    StockMonthlySource,
    monthly_asset_key,
    monthly_check_names,
    monthly_column_specs,
    monthly_contract_hash,
    normalize_month_key,
)


@dataclass(frozen=True)
class MonthlyEventPolicy:
    event_write_cap: int = 2048
    event_record_read_cap: int = 8192
    event_partition_batch: int = 12
    event_write_batch: int = 100
    plan_max_bytes: int = 8 * 1024 * 1024


TOKEN = "goldenshare/monthly_event_plan"


def _value(metadata, key):
    return getattr(metadata.get(key), "value", None)


def _asset(entry):
    return dg.AssetKey(monthly_asset_key(StockMonthlySource(entry["source"])))


def _delivery(entry):
    return {
        key: entry[key]
        for key in (
            "delivery_method",
            "source",
            "month",
            "path",
            "rows",
            "audit_path",
            "audit_hash",
        )
    }


def _matching_mat(record, entry):
    if record is None:
        return False
    materialization = record.asset_materialization
    return (
        materialization.partition == entry["month"]
        and _value(materialization.metadata, "dagster/uri") == entry["path"]
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
        and evaluation.partition == entry["month"]
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


def read_monthly_event_state(instance, entries, *, record_cap=None):
    """Batch latest partition state; full check bodies fetched by bounded storage IDs."""
    budget = MonthlyEventPolicy()
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
            raise ValueError("event_record_read_cap_exceeded")

    for entry in entries:
        groups[(entry["source"], entry["month"][:4])].append(entry)
    for (source_name, _), group in sorted(groups.items()):
        source = StockMonthlySource(source_name)
        asset = dg.AssetKey(monthly_asset_key(source))
        names = monthly_check_names(source)
        for offset in range(0, len(group), budget.event_partition_batch):
            batch = group[offset : offset + budget.event_partition_batch]
            months = [e["month"] for e in batch]
            mats, cursor = {}, None
            while True:
                result = instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=asset, asset_partitions=months),
                    limit=min(500, max(1, cap - returned + 1)),
                    cursor=cursor,
                )
                consume(len(result.records))
                for record in result.records:
                    mats.setdefault(record.asset_materialization.partition, record)
                if len(mats) == len(months) or not result.has_more:
                    break
                if not result.cursor or result.cursor == cursor:
                    raise ValueError("event_cursor_not_advancing")
                cursor = result.cursor
            infos = instance.event_log_storage.get_asset_check_partition_info(
                [dg.AssetCheckKey(asset, name) for name in names],
                partition_keys=months,
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
                state[(source_name, entry["month"])] = {
                    "mat": mats.get(entry["month"]),
                    "checks": {
                        name: checks.get((entry["month"], name), (None, None))
                        for name in names
                    },
                }
    return state, returned


def freeze_monthly_event_plan(instance, entries, *, instance_identity, evidence):
    if not entries or len(entries) * 4 > MonthlyEventPolicy().event_write_cap:
        raise ValueError("event_write_budget_exceeded")
    for entry in entries:
        verify_monthly_event_file(entry, Path(evidence["lake_root"]))
    keys = [(e["source"], normalize_month_key(e["month"])) for e in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("event_entry_duplicate")
    state, returned = read_monthly_event_state(instance, entries)
    registered = set(instance.get_dynamic_partitions(STOCK_MONTHLY_PARTITIONS))
    pending, failed = [], 0
    for entry in entries:
        current = state[(entry["source"], entry["month"])]
        mat = current["mat"]
        mat_matches = _matching_mat(mat, entry)
        if mat is not None and not mat_matches:
            raise ValueError("monthly_event_existing_materialization_conflict")
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
        "kind": "monthly_event_plan",
        "instance_identity": instance_identity,
        "evidence": evidence,
        "policy": asdict(MonthlyEventPolicy()),
        "entries": pending,
        "missing_registrations": sorted({e["month"] for e in entries} - registered),
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
    plan["plan_hash"] = monthly_contract_hash(plan)
    return plan


def verify_monthly_event_plan(plan):
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    if (
        plan.get("kind") != "monthly_event_plan"
        or plan.get("version") != 1
        or monthly_contract_hash(body) != plan.get("plan_hash")
        or plan.get("policy") != asdict(MonthlyEventPolicy())
    ):
        raise ValueError("event_plan_hash_mismatch")
    entries = plan["entries"]
    if not entries or len(entries) * 4 > MonthlyEventPolicy().event_write_cap:
        raise ValueError("event_write_budget_exceeded")
    if len({(e["source"], e["month"]) for e in entries}) != len(entries):
        raise ValueError("event_entry_duplicate")
    for entry in entries:
        normalize_month_key(entry["month"])
        if entry["delivery_method"] != "prod_month_bootstrap":
            raise ValueError("monthly_event_delivery_invalid")
        if entry["path"] != str(
            raw_stock_monthly_path(
                Path(plan["evidence"]["lake_root"]),
                StockMonthlySource(entry["source"]),
                entry["month"],
            )
        ):
            raise ValueError("monthly_event_path_invalid")
        names = monthly_check_names(StockMonthlySource(entry["source"]))
        if set(entry["missing_checks"]) - set(names) or set(
            entry["previous_check_ids"]
        ) != set(names):
            raise ValueError("event_check_scope_invalid")
    if set(plan["missing_registrations"]) - {e["month"] for e in entries}:
        raise ValueError("event_registration_scope_invalid")


def audit_monthly_event_files(evidence, *, cancel=lambda: False):
    """Full semantic audit once per source/year, never per check event."""
    entries, metrics = [], []
    sources = set()
    for ref in evidence["history_plans"]:
        path = Path(ref["path"])
        if (
            monthly_file_hash(path, max_bytes=MonthlyEventPolicy().plan_max_bytes)
            != ref["sha256"]
        ):
            raise ValueError("monthly_event_history_plan_changed")
        plan = load_monthly_history_plan(path)
        if plan.source.value in sources:
            raise ValueError("monthly_event_source_duplicate")
        sources.add(plan.source.value)
        result = audit_monthly_history(
            plan, evidence["lake_root"], evidence["staging_root"], cancel=cancel
        )
        entries.extend(result.pop("entries"))
        metrics.append(result)
    if sources != {s.value for s in StockMonthlySource}:
        raise ValueError("monthly_event_requires_two_sources")
    return sorted(entries, key=lambda e: (e["month"], e["source"])), metrics


def verify_monthly_event_file(entry, root):
    io = MonthlyBootstrapIOPolicy()
    if (
        monthly_file_hash(Path(entry["path"]), max_bytes=io.prod_csv_max_bytes)
        != entry["sha256"]
    ):
        raise ValueError("monthly_event_file_changed")
    read_month_bootstrap_delivery(
        _delivery(entry), root, StockMonthlySource(entry["source"]), entry["month"]
    )
    audit = read_monthly_json(Path(entry["audit_path"]), io.control_max_bytes)
    selected = next(r for r in audit["records"] if r["month"] == entry["month"])
    if selected["logical_hash"] != entry["logical_hash"]:
        raise ValueError("monthly_event_logical_hash_changed")


def _assert_state_owned(current, entry, plan_hash):
    mat = current["mat"]
    if (mat.storage_id if mat else None) != entry["previous_mat_id"] and (
        not _matching_mat(mat, entry)
        or _value(mat.asset_materialization.metadata, TOKEN) != plan_hash
    ):
        raise ValueError("monthly_event_materialization_changed")
    for name, (record_id, record) in current["checks"].items():
        if record_id != entry["previous_check_ids"][name] and (
            not _matching_check(record, name, mat, entry)
            or _value(
                record.event_log_entry.dagster_event.event_specific_data.metadata, TOKEN
            )
            != plan_hash
        ):
            raise ValueError("monthly_event_check_changed")


def apply_monthly_events(
    instance,
    plan,
    *,
    checkpoint,
    start=0,
    count=25,
    register=False,
    months=None,
    cancel=lambda: False,
):
    """Bounded writes with live event replay, exact targets, no data modification."""
    verify_monthly_event_plan(plan)
    policy = MonthlyEventPolicy()
    if (
        type(start) is not int
        or type(count) is not int
        or start < 0
        or not 1 <= count <= (100 if register else policy.event_write_batch // 4)
    ):
        raise ValueError("monthly_event_batch_invalid")
    if any(e["blocked_checks"] for e in plan["entries"]):
        raise ValueError("monthly_event_existing_check_requires_review")
    root = Path(plan["evidence"]["lake_root"])
    entries = plan["entries"][start : start + count]
    if months is not None:
        if register or start or len(set(months)) != len(months):
            raise ValueError("monthly_event_sample_scope_invalid")
        entries = [e for e in plan["entries"] if e["month"] in months]
        if (
            not entries
            or len(entries) > count
            or set(months) != {e["month"] for e in entries}
        ):
            raise ValueError("monthly_event_sample_scope_invalid")
    months = plan["missing_registrations"][start : start + count] if register else []
    proofs = (
        [e for e in plan["entries"] if e["month"] in months] if register else entries
    )
    for entry in proofs:
        check_monthly_cancel(cancel)
        verify_monthly_event_file(entry, root)
    writes = skipped = 0

    def persist(unit):
        write_monthly_json(
            Path(checkpoint),
            {
                "plan_hash": plan["plan_hash"],
                "writes": writes,
                "skipped": skipped,
                **unit,
            },
            policy.plan_max_bytes,
        )
        check_monthly_cancel(cancel)

    if register:
        existing = set(instance.get_dynamic_partitions(STOCK_MONTHLY_PARTITIONS))
        for month in months:
            check_monthly_cancel(cancel)
            if month in existing:
                skipped += 1
                continue
            instance.add_dynamic_partitions(STOCK_MONTHLY_PARTITIONS, [month])
            if not instance.has_dynamic_partition(STOCK_MONTHLY_PARTITIONS, month):
                raise ValueError("monthly_event_registration_readback_failed")
            writes += 1
            persist({"month": month, "stage": "register"})
        return {"writes": writes, "skipped": skipped}
    before, _ = read_monthly_event_state(instance, entries)
    for entry in entries:
        check_monthly_cancel(cancel)
        key = (entry["source"], entry["month"])
        current = before[key]
        _assert_state_owned(current, entry, plan["plan_hash"])
        if not instance.has_dynamic_partition(STOCK_MONTHLY_PARTITIONS, entry["month"]):
            raise ValueError("monthly_event_registration_missing")
        verify_monthly_event_file(entry, root)
        asset, source = _asset(entry), StockMonthlySource(entry["source"])
        # This exact target read is part of writing, not a historical readiness scan.
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[entry["month"]]),
            limit=1,
        ).records
        mat = records[0] if records else None
        if (mat.storage_id if mat else None) != (
            current["mat"].storage_id if current["mat"] else None
        ):
            raise ValueError("monthly_event_materialization_changed")
        if not _matching_mat(mat, entry):
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=entry["month"],
                    metadata=build_materialization_metadata(
                        uri=entry["path"],
                        row_count=entry["rows"],
                        observed_columns=[s[0] for s in monthly_column_specs(source)],
                        extra_metadata={
                            TOKEN: plan["plan_hash"],
                        },
                    ),
                )
            )
            writes += 1
            persist(
                {
                    "source": source.value,
                    "month": entry["month"],
                    "stage": "materialization",
                }
            )
            records = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=asset, asset_partitions=[entry["month"]]
                ),
                limit=1,
            ).records
            mat = records[0] if records else None
            if (
                not _matching_mat(mat, entry)
                or _value(mat.asset_materialization.metadata, TOKEN)
                != plan["plan_hash"]
            ):
                raise ValueError("monthly_event_materialization_readback_failed")
        else:
            skipped += 1
        for name, scope in zip(
            monthly_check_names(source),
            (
                CheckScope.SCHEMA,
                CheckScope.PARTITION_ALIGNMENT,
                CheckScope.RECONCILIATION,
            ),
            strict=True,
        ):
            check_monthly_cancel(cancel)
            record = current["checks"][name][1]
            if _matching_check(record, name, mat, entry):
                skipped += 1
                continue
            instance.report_runless_asset_event(
                AssetCheckEvaluation(
                    asset_key=asset,
                    check_name=name,
                    partition=entry["month"],
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
                            "goldenshare/month": entry["month"],
                            "goldenshare/reason_code": "ok",
                            "goldenshare/logical_hash": entry["logical_hash"],
                            "goldenshare/delivery_audit_hash": entry["audit_hash"],
                        },
                    ),
                )
            )
            writes += 1
            persist({"source": source.value, "month": entry["month"], "stage": name})
    after, returned = read_monthly_event_state(instance, entries)
    for entry in entries:
        current = after[(entry["source"], entry["month"])]
        _assert_state_owned(current, entry, plan["plan_hash"])
        if not _matching_mat(current["mat"], entry) or not all(
            _matching_check(r, n, current["mat"], entry)
            for n, (_, r) in current["checks"].items()
        ):
            raise ValueError("monthly_event_batch_readback_failed")
        verify_monthly_event_file(entry, root)
    return {"writes": writes, "skipped": skipped, "records_returned": returned}


def audit_monthly_readiness_samples(instance, entries, root):
    import tempfile

    from orchestrator.defs.checks.stock_monthly_checks import audit_monthly_file
    from orchestrator.defs.stock_monthly_point import monthly_connection

    selected = []
    for source in StockMonthlySource:
        group = sorted(
            (e for e in entries if e["source"] == source.value),
            key=lambda e: e["month"],
        )
        months = {group[0]["month"], group[-1]["month"], "2020-02", "2026-05"}
        selected.extend(e for e in group if e["month"] in months)
    state, _ = read_monthly_event_state(instance, selected)
    samples = []
    for entry in selected:
        current = state[(entry["source"], entry["month"])]
        ready = _matching_mat(current["mat"], entry) and all(
            _matching_check(r, n, current["mat"], entry)
            for n, (_, r) in current["checks"].items()
        )
        if ready:
            with monthly_connection(
                Path(tempfile.gettempdir()).resolve(), readonly=True
            ) as con:
                audit_monthly_file(
                    con, Path(root), StockMonthlySource(entry["source"]), entry["month"]
                )
                read_month_bootstrap_delivery(
                    _delivery(entry),
                    Path(root),
                    StockMonthlySource(entry["source"]),
                    entry["month"],
                    connection=con,
                )
        samples.append(
            {"source": entry["source"], "month": entry["month"], "ready": bool(ready)}
        )
    return samples
