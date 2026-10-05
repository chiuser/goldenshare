"""Bounded monthly reads and strict partition/materialization identity matching."""

from collections import defaultdict

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
)
from dagster._core.event_api import EventRecordsFilter
from dagster._core.events import DagsterEventType

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    ANNOUNCEMENT_VERSION,
    AnnouncementError,
)

TOKEN = "goldenshare/announcement_event_plan"
ASSET = dg.AssetKey(ANNOUNCEMENT_ASSET)
RECORD_CAP = 30000


def value(metadata, key):
    return getattr(metadata.get(key), "value", None)


def matching_mat(record, entry):
    if record is None:
        return False
    mat = record.asset_materialization
    return (
        mat.asset_key == ASSET
        and mat.partition == entry["day"]
        and value(mat.metadata, "goldenshare/announcement_file") == entry["file"]
        and value(mat.metadata, "goldenshare/announcement_contract_version")
        == ANNOUNCEMENT_VERSION
        and value(mat.metadata, "dagster/row_count") == entry["rows"]
        and value(mat.metadata, "dagster/uri") == entry["path"]
        and value(mat.metadata, "goldenshare/announcement_checkpoint")
        == entry["checkpoint"]
        and value(mat.metadata, "goldenshare/announcement_identity")
        == entry["identity"]
    )


def matching_check(record, name, mat, entry):
    if record is None or mat is None:
        return False
    check = record.event_log_entry.dagster_event.event_specific_data
    if not isinstance(check, AssetCheckEvaluation):
        return False
    target = check.target_materialization_data
    return (
        check.asset_key == ASSET
        and check.check_name == name
        and check.partition == entry["day"]
        and check.passed
        and check.blocking
        and check.severity == dg.AssetCheckSeverity.ERROR
        and target is not None
        and target.storage_id == mat.storage_id
        and target.run_id == mat.event_log_entry.run_id
        and target.timestamp == mat.event_log_entry.timestamp
        and value(check.metadata, "goldenshare/announcement_contract_version")
        == ANNOUNCEMENT_VERSION
        and value(check.metadata, "goldenshare/checked_row_count") == entry["rows"]
        and value(check.metadata, "goldenshare/announcement_file") == entry["file"]
    )


class EventReadBudget:
    def __init__(self, cap=RECORD_CAP):
        self.cap, self.returned = min(cap, RECORD_CAP), 0

    def consume(self, count):
        self.returned += count
        if self.returned > self.cap:
            raise AnnouncementError("announcement_event_read_budget")


def read_announcement_event_state(instance, entries, budget, control):
    groups, state = defaultdict(list), {}
    for entry in entries:
        groups[entry["day"][:7]].append(entry)
    for _, group in sorted(groups.items()):
        if len(group) > 31:
            raise AnnouncementError("announcement_event_month_budget")
        control.check()
        days = [e["day"] for e in group]
        mats, cursor = {}, None
        while True:
            result = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=ASSET, asset_partitions=days),
                limit=min(500, max(1, budget.cap - budget.returned + 1)),
                cursor=cursor,
            )
            budget.consume(len(result.records))
            for record in result.records:
                mats.setdefault(record.asset_materialization.partition, record)
            if len(mats) == len(days) or not result.has_more:
                break
            if not result.cursor or result.cursor == cursor:
                raise AnnouncementError("announcement_event_cursor_not_advancing")
            cursor = result.cursor
            control.check()
        infos = instance.event_log_storage.get_asset_check_partition_info(
            [dg.AssetCheckKey(ASSET, name) for name in ANNOUNCEMENT_CHECKS],
            partition_keys=days,
        )
        budget.consume(len(infos))
        ids = sorted({i.latest_check_event_storage_id for i in infos})
        bodies = {}
        if ids:
            records = instance.event_log_storage.get_event_records(
                EventRecordsFilter(
                    DagsterEventType.ASSET_CHECK_EVALUATION, storage_ids=ids
                ),
                limit=62,
            )
            budget.consume(len(records))
            bodies = {r.storage_id: r for r in records}
            if set(bodies) != set(ids):
                raise AnnouncementError("announcement_event_check_body_missing")
        checks = {
            (i.partition_key, i.check_key.name): (
                i.latest_check_event_storage_id,
                bodies[i.latest_check_event_storage_id],
            )
            for i in infos
        }
        for entry in group:
            state[entry["day"]] = {
                "mat": mats.get(entry["day"]),
                "checks": {
                    name: checks.get((entry["day"], name), (None, None))
                    for name in ANNOUNCEMENT_CHECKS
                },
            }
    return state


def freeze_announcement_events(instance, entries, identity, control):
    budget = EventReadBudget()
    states = read_announcement_event_state(instance, entries, budget, control)
    pending = []
    for entry in entries:
        state = states[entry["day"]]
        mat = state["mat"]
        if mat is not None and not matching_mat(mat, entry):
            raise AnnouncementError(
                "announcement_event_existing_materialization_conflict"
            )
        missing = []
        for name, (storage_id, record) in state["checks"].items():
            if storage_id is not None and not matching_check(record, name, mat, entry):
                raise AnnouncementError("announcement_event_existing_check_conflict")
            if record is None:
                missing.append(name)
        pending.append(
            {
                **entry,
                "previous_mat_id": mat.storage_id if mat else None,
                "previous_check_ids": {n: v[0] for n, v in state["checks"].items()},
                "missing_mat": mat is None,
                "missing_checks": missing,
            }
        )
    return {
        "kind": "anns_d_event_plan",
        "version": 1,
        "instance_identity": identity,
        "entries": pending,
        "counts": {
            "files": len(entries),
            "rows": sum(e["rows"] for e in entries),
            "materializations": sum(e["missing_mat"] for e in pending),
            "checks": sum(len(e["missing_checks"]) for e in pending),
            "records_returned": budget.returned,
        },
    }
