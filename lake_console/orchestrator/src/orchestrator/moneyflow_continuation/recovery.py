"""Explicit single Silver launch recovery; business failures remain terminal."""

import os
import re
from uuid import UUID

from orchestrator.moneyflow_continuation.contract import (
    POLICY,
    file_hash,
    read_json,
    require,
    safe_path,
)

ACTION = "silver_reexecution"
REEXECUTE = """mutation($parentRunId:String!){launchRun:launchRunReexecution(reexecutionParams:{parentRunId:$parentRunId,strategy:ALL_STEPS,useParentRunTags:true}){__typename ... on LaunchRunSuccess{run{runId status}}}}"""


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
    require(matches(value, unit) and value["raw_sha256"] == raw_sha, "recovery_scope")
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


def effective_runs(backend, journal, unit, runs):
    """Keep the parent visible while selecting at most one explicitly linked child."""
    value = journal.plan.get("launch_recovery")
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
    original = journal.read(unit, "silver")
    require(
        "response" in original and "send_intent" in original,
        "recovery_original_journal",
    )
    require(
        original["request"]["raw_sha256"] == value["raw_sha256"],
        "recovery_raw_revision",
    )
    backend.validate_run(parent, unit, "silver", original["request"]["body"])
    backend.check_response(
        original["response"]["value"], "silver", {"run_id": parent.run_id}
    )
    records = backend.instance.event_log_storage.get_records_for_run(
        parent.run_id, limit=21, ascending=True
    ).records
    facts = event_facts(records)
    pid = validate_failure(facts)
    ref = value["evidence"]
    require(file_hash(ref["path"]) == ref["sha256"], "recovery_evidence_hash")
    require(
        read_json(ref["path"], POLICY.action_bytes)
        == {"failed_run_id": parent.run_id, "events": facts},
        "recovery_evidence_changed",
    )
    worker_absent(pid)
    directory = safe_path(
        backend.staging
        / "moneyflow"
        / parent.run_id
        / unit["dataset"]
        / unit["trade_date"]
    )
    require(not directory.exists(), "recovery_parent_candidate")
    children = [r for r in runs if r.run_id != parent.run_id]
    if not children:
        require(
            not safe_path(unit["silver"]["target"]).exists(), "recovery_existing_silver"
        )
    else:
        child = children[0]
        require(
            child.parent_run_id == parent.run_id and child.root_run_id == parent.run_id,
            "recovery_child_parent",
        )
        backend.validate_run(child, unit, "silver", original["request"]["body"])
        files = journal.read(unit, ACTION)
        require("send_intent" in files, "unrecorded_native_action")
        if "response" in files:
            backend.check_response(
                files["response"]["value"], ACTION, {"run_id": child.run_id}
            )
    return children, {
        "run_id": parent.run_id,
        "status": parent.status.value,
        "reason": "launch_failed_before_execution",
    }
