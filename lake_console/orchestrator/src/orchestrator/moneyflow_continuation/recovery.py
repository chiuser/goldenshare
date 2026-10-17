"""Explicit parent-bound recoveries; unknown failures remain terminal."""

import os
import re
from uuid import UUID

from orchestrator.moneyflow_continuation.contract import (
    POLICY,
    REPO,
    file_hash,
    read_json,
    require,
    safe_path,
)

ACTION = "silver_reexecution"
RAW_ACTION = "raw_reexecution"
RECOVERY_ACTIONS = frozenset({ACTION, RAW_ACTION})
REEXECUTE = """mutation($parentRunId:String!){launchRun:launchRunReexecution(reexecutionParams:{parentRunId:$parentRunId,strategy:ALL_STEPS,useParentRunTags:true}){__typename ... on LaunchRunSuccess{run{runId status}}}}"""


def action_layer(action):
    return {ACTION: "silver", RAW_ACTION: "raw"}.get(action, action)


def descriptor(plan, unit, layer):
    value = plan.get("launch_recovery" if layer == "silver" else "collection_recovery")
    return value if matches(value, unit) else None


def recovery_actions(plan, unit):
    return tuple(
        a for a in (RAW_ACTION, ACTION) if descriptor(plan, unit, action_layer(a))
    )


def validate_collection_descriptor(value, root_units):
    if value is None:
        return
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "dataset",
            "trade_date",
            "layer",
            "failed_run_id",
            "first_round_sha256",
            "evidence",
        },
        "collection_recovery_descriptor",
        2,
    )
    require(
        value["dataset"] == "moneyflow"
        and value["trade_date"] == "2026-10-13"
        and value["layer"] == "raw"
        and value["failed_run_id"] == "ca3d12ad-717e-4291-a87f-6c2a3d37204a",
        "collection_recovery_scope",
        2,
    )
    validate_descriptor(
        {
            **{k: v for k, v in value.items() if k != "first_round_sha256"},
            "layer": "silver",
            "raw_sha256": value["first_round_sha256"],
        },
        root_units,
    )
    require(len(root_units) == 47, "collection_recovery_root", 2)


def collection_evidence_path(path):
    from pathlib import Path

    path = safe_path(path)
    require(
        any(
            root in path.parents
            for root in (Path("/private/tmp"), REPO / "lake_console/reports")
        ),
        "collection_evidence_location",
        2,
    )
    return path


def collection_evidence(value):
    ref = value["evidence"]
    path = collection_evidence_path(ref["path"])
    require(file_hash(path) == ref["sha256"], "recovery_evidence_hash")
    evidence = read_json(path, POLICY.action_bytes)
    require(
        evidence.get("run_id") == value["failed_run_id"]
        and evidence.get("status") == "FAILURE"
        and evidence.get("candidate_sha256") == value["first_round_sha256"]
        and evidence.get("source_file")
        == "defs/source_readiness/moneyflow_daily.py:91",
        "collection_recovery_evidence",
    )
    return evidence


def validate_descriptor(value, root_units):
    if value is None:
        return
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "dataset",
            "trade_date",
            "layer",
            "failed_run_id",
            "raw_sha256",
            "evidence",
        },
        "recovery_descriptor",
        2,
    )
    require(
        value["layer"] == "silver"
        and any(matches(value, u) for u in root_units)
        and re.fullmatch(r"[0-9a-f]{64}", value["raw_sha256"] or "")
        and re.fullmatch(r"[0-9a-f-]{36}", value["failed_run_id"] or ""),
        "recovery_identity",
        2,
    )
    require(
        str(UUID(value["failed_run_id"])) == value["failed_run_id"],
        "recovery_parent",
        2,
    )
    ref = value["evidence"]
    require(
        isinstance(ref, dict)
        and set(ref) == {"path", "sha256"}
        and isinstance(ref["path"], str)
        and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"] or ""),
        "recovery_evidence_reference",
        2,
    )


def matches(value, unit):
    return value is not None and all(
        value[k] == unit[k] for k in ("dataset", "trade_date")
    )


def request(value, unit, raw_sha):
    require(matches(value, unit), "recovery_scope")
    if value["layer"] == "silver":
        require(value["raw_sha256"] == raw_sha, "recovery_scope")
    return {"query": REEXECUTE, "variables": {"parentRunId": value["failed_run_id"]}}


def event_facts(records):
    """Bounded producer-shaped evidence, excluding stacks and credentials."""
    require(0 < len(records) <= 20, "recovery_events_truncated")
    facts = []
    for record in records:
        entry = record.event_log_entry
        event = entry.dagster_event
        require(event is not None, "recovery_non_dagster_event")
        error = getattr(event.event_specific_data, "error", None)
        errors = []
        while error is not None:
            require(len(errors) < 8, "recovery_error_depth")
            errors.append({"class": error.cls_name, "message": error.message})
            error = error.cause
        facts.append(
            {
                "event": event.event_type_value,
                "message": entry.message,
                "errors": errors,
            }
        )
    return facts


def validate_failure(events):
    allowed = {
        "ASSET_MATERIALIZATION_PLANNED",
        "ASSET_CHECK_EVALUATION_PLANNED",
        "PIPELINE_ENQUEUED",
        "PIPELINE_STARTING",
        "ENGINE_EVENT",
        "PIPELINE_FAILURE",
    }
    kinds = [e["event"] for e in events]
    require(
        set(kinds) <= allowed
        and all(kinds.count(k) == 1 for k in allowed - {"ENGINE_EVENT"}),
        "recovery_business_or_unknown_event",
    )
    ipc = [
        i
        for i, e in enumerate(events)
        if e["event"] == "ENGINE_EVENT"
        and e["message"] == "Unexpected error in IPC client"
    ]
    failed = kinds.index("PIPELINE_FAILURE")
    late = [
        i
        for i, e in enumerate(events)
        if e["message"]
        == "Ignoring a run worker that started after the run had already finished."
    ]
    exits = [
        i
        for i, e in enumerate(events)
        if re.fullmatch(r"Process for run exited \(pid: [0-9]+\)\.", e["message"])
    ]
    require(
        len(ipc) == len(late) == len(exits) == 1
        and ipc[0] < failed < late[0] < exits[0] == len(events) - 1,
        "recovery_launch_sequence",
    )
    error = events[ipc[0]]["errors"]
    require(
        any(e["class"] == "DagsterUserCodeUnreachableError" for e in error)
        and any("Stream removed" in e["message"] for e in error),
        "recovery_launch_error",
    )
    pid = int(re.search(r"pid: ([0-9]+)", events[exits[0]]["message"])[1])
    require(
        any(
            e["message"] == f"Started process for run (pid: {pid})."
            for e in events[failed + 1 : late[0]]
        ),
        "recovery_worker_identity",
    )
    return pid


def worker_absent(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    require(False, "recovery_worker_still_present")


def effective_runs(backend, journal, unit, runs, layer="silver"):
    """Keep the parent visible while selecting at most one explicitly linked child."""
    value = descriptor(journal.plan, unit, layer)
    require(matches(value, unit), "recovery_scope")
    require(1 <= len(runs) <= 2, "duplicate_native_runs")
    parents = [r for r in runs if r.run_id == value["failed_run_id"]]
    require(len(parents) == 1, "recovery_parent_missing")
    parent = parents[0]
    require(
        parent.status.value == "FAILURE"
        and parent.parent_run_id is None
        and parent.root_run_id is None,
        "recovery_parent_state",
    )
    original = journal.read(unit, layer)
    require(
        "response" in original and "send_intent" in original,
        "recovery_original_journal",
    )
    if layer == "silver":
        require(
            original["request"]["raw_sha256"] == value["raw_sha256"],
            "recovery_raw_revision",
        )
    backend.validate_run(parent, unit, layer, original["request"]["body"])
    backend.check_response(
        original["response"]["value"], layer, {"run_id": parent.run_id}
    )
    if layer == "silver":
        records = backend.instance.event_log_storage.get_records_for_run(
            parent.run_id, limit=21, ascending=True
        ).records
        facts = event_facts(records)
        pids = [validate_failure(facts)]
        ref = value["evidence"]
        require(file_hash(ref["path"]) == ref["sha256"], "recovery_evidence_hash")
        require(
            read_json(ref["path"], POLICY.action_bytes)
            == {"failed_run_id": parent.run_id, "events": facts},
            "recovery_evidence_changed",
        )
    else:
        pids = validate_collection_failure(backend, parent, value)
    directory = safe_path(
        backend.staging
        / "moneyflow"
        / parent.run_id
        / unit["dataset"]
        / unit["trade_date"]
    )
    if layer == "silver":
        require(not directory.exists(), "recovery_parent_candidate")
    else:
        validate_collection_candidate(backend, directory, unit, value)
    children = [r for r in runs if r.run_id != parent.run_id]
    if not children:
        for pid in pids:
            worker_absent(pid)
        require(
            not safe_path(unit[layer]["target"]).exists(), "recovery_existing_" + layer
        )
        if layer == "raw":
            require(
                not safe_path(unit["silver"]["target"]).exists(),
                "recovery_existing_silver",
            )
    else:
        child = children[0]
        require(
            child.parent_run_id == parent.run_id and child.root_run_id == parent.run_id,
            "recovery_child_parent",
        )
        backend.validate_run(child, unit, layer, original["request"]["body"])
        action = ACTION if layer == "silver" else RAW_ACTION
        files = journal.read(unit, action)
        require("send_intent" in files, "unrecorded_native_action")
        if "response" in files:
            backend.check_response(
                files["response"]["value"], action, {"run_id": child.run_id}
            )
    return children, {
        "run_id": parent.run_id,
        "status": parent.status.value,
        "reason": "launch_failed_before_execution"
        if layer == "silver"
        else "collection_wait_boundary_failed",
    }


def validate_collection_failure(backend, parent, value):
    evidence = collection_evidence(value)
    records = backend.instance.event_log_storage.get_records_for_run(
        parent.run_id, limit=61, ascending=True
    ).records
    require(0 < len(records) <= 60, "collection_recovery_events_truncated")
    native, failures, pids = [], [], set()
    for record in records:
        entry, errors = record.event_log_entry, []
        event = entry.dagster_event
        if event is None:
            continue  # Ordinary log messages cannot contain Dagster business events.
        error = getattr(event.event_specific_data, "error", None)
        while error is not None:
            require(len(errors) < 8, "recovery_error_depth")
            errors.append({"class": error.cls_name, "message": error.message})
            if (
                event.event_type_value == "STEP_FAILURE"
                and error.cls_name == "ValueError"
            ):
                require(
                    error.message.strip()
                    == "ValueError: sleep length must be non-negative"
                    and any(
                        "moneyflow_daily.py" in frame
                        and "line 91" in frame
                        and "sleep_fn" in frame
                        for frame in error.stack
                    ),
                    "collection_recovery_error",
                )
                failures.append(True)
            error = error.cause
        native.append(
            {
                "id": record.storage_id,
                "event": event.event_type_value,
                "message": entry.message,
                "error": errors,
            }
        )
        if event.event_type_value == "ENGINE_EVENT":
            match = re.fullmatch(
                r"Process for run exited \(pid: ([0-9]+)\)\.", entry.message
            )
            if match:
                pids.add(int(match[1]))
        if event.event_type_value == "LOGS_CAPTURED":
            match = re.search(r"process \(pid: ([0-9]+)\)", entry.message)
            if match:
                pids.add(int(match[1]))
    require(
        native == evidence.get("native_events", {}).get("events"),
        "recovery_evidence_changed",
    )
    kinds = [item["event"] for item in native]
    allowed = {
        "ASSET_MATERIALIZATION_PLANNED",
        "ASSET_CHECK_EVALUATION_PLANNED",
        "PIPELINE_ENQUEUED",
        "PIPELINE_STARTING",
        "PIPELINE_START",
        "ENGINE_EVENT",
        "STEP_WORKER_STARTING",
        "STEP_WORKER_STARTED",
        "RESOURCE_INIT_STARTED",
        "RESOURCE_INIT_SUCCESS",
        "LOGS_CAPTURED",
        "STEP_START",
        "STEP_FAILURE",
        "PIPELINE_FAILURE",
    }
    require(
        set(kinds) <= allowed
        and len(failures) == kinds.count("STEP_FAILURE") == 1
        and kinds.count("STEP_START")
        == kinds.count("PIPELINE_START")
        == kinds.count("PIPELINE_FAILURE")
        == 1
        and kinds.index("PIPELINE_START")
        < kinds.index("STEP_START")
        < kinds.index("STEP_FAILURE")
        < kinds.index("PIPELINE_FAILURE")
        and native[-1]["event"] == "ENGINE_EVENT"
        and re.fullmatch(
            r"Process for run exited \(pid: [0-9]+\)\.", native[-1]["message"]
        )
        and pids,
        "collection_recovery_failure_sequence",
    )
    return pids


def validate_collection_candidate(backend, directory, unit, value):
    from orchestrator.defs.checks.moneyflow_daily import audit_daily_moneyflow_file

    evidence = collection_evidence(value)
    require(
        directory.is_dir()
        and {p.name for p in directory.iterdir()}
        == {"round-1", "raw.parquet", "receipt.json"},
        "collection_recovery_candidate",
    )
    backend.run_disk_size(directory)
    require(
        str(directory / "raw.parquet") == evidence["candidate_path"]
        and file_hash(directory / "raw.parquet") == value["first_round_sha256"],
        "collection_recovery_candidate_hash",
    )
    receipt = read_json(directory / "receipt.json", POLICY.action_bytes)
    require(
        receipt
        == evidence["receipt"]
        == {"dataset": "moneyflow", "stage": "collecting", "trade_date": "2026-10-13"},
        "collection_recovery_receipt",
    )
    pages = evidence.get("first_round_pages", [])
    page_directory = directory / "round-1" / "scope-1"
    require(
        len(pages) == 3
        and {p.name for p in (directory / "round-1").iterdir()} == {"scope-1"}
        and {p.name for p in page_directory.iterdir()}
        == {"page-0.json", "page-2000.json", "page-4000.json"}
        and [p["rows"] for p in pages] == [2000, 2000, 1574]
        and [p["file"] for p in pages]
        == ["page-0.json", "page-2000.json", "page-4000.json"],
        "collection_recovery_pages",
    )
    for page in pages:
        require(
            file_hash(page_directory / page["file"]) == page["sha256"],
            "collection_recovery_page_hash",
        )
    proof = (
        unit["dataset"],
        unit["trade_date"],
        value["failed_run_id"],
        value["evidence"]["sha256"],
        value["first_round_sha256"],
        file_hash(directory / "receipt.json"),
    )
    if getattr(backend, "_collection_candidate_audit", None) == proof:
        return
    with backend.connection() as connection:
        count = audit_daily_moneyflow_file(
            connection,
            directory / "raw.parquet",
            unit["trade_date"],
            dataset="moneyflow",
        )
    require(
        count == evidence.get("first_round_rows") == 5574
        and evidence.get("first_round_schema_columns") == 20,
        "collection_recovery_candidate_count",
    )
    backend._collection_candidate_audit = proof
