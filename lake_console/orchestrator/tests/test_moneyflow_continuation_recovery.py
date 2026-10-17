"""Literal 2026-10-14 launch evidence; SDK boundary is replaced, never formal resources."""

import copy
import json
from types import SimpleNamespace as NS

import pytest

from orchestrator.moneyflow_continuation.contract import (
    ContinuationError,
    digest,
    file_hash,
)
from orchestrator.moneyflow_continuation.execution import apply
from orchestrator.moneyflow_continuation.plan import make_plan, validate_plan
from orchestrator.moneyflow_continuation.recovery import (
    ACTION,
    REEXECUTE,
    effective_runs,
    event_facts,
    request,
    validate_failure,
)
from orchestrator.moneyflow_continuation.state import NativeBackend, next_action
from orchestrator.moneyflow_continuation.submission import (
    Journal,
    submit_once,
    write_json,
)
from tests.test_moneyflow_continuation_plan import AT, plan_for
from tests.test_moneyflow_continuation_state import snapshot
from tests.test_moneyflow_continuation_submission import FakeNative

PARENT = "656aa7d0-94c5-477e-a72e-452a48618d2c"
CHILD = "11111111-1111-4111-8111-111111111111"
SHA = "b" * 64


def facts():
    # Independent literal reduced from failure-last-events.json + engine cause.
    values = [
        ("ASSET_MATERIALIZATION_PLANNED", "planned"),
        ("ASSET_CHECK_EVALUATION_PLANNED", "planned"),
        ("PIPELINE_ENQUEUED", ""),
        ("PIPELINE_STARTING", ""),
        ("ENGINE_EVENT", "Unexpected error in IPC client"),
        (
            "ENGINE_EVENT",
            "Caught an unrecoverable error while dequeuing the run. Marking the run as failed and dropping it from the queue",
        ),
        (
            "PIPELINE_FAILURE",
            "This run has been marked as failed from outside the execution context.",
        ),
        ("ENGINE_EVENT", "Started process for run (pid: 3228)."),
        (
            "ENGINE_EVENT",
            "Ignoring a run worker that started after the run had already finished.",
        ),
        ("ENGINE_EVENT", "Process for run exited (pid: 3228)."),
    ]
    result = [{"event": e, "message": m, "errors": []} for e, m in values]
    result[4]["errors"] = [
        {
            "class": "DagsterUserCodeUnreachableError",
            "message": "Could not reach user code server",
        },
        {"class": "_InactiveRpcError", "message": "Stream removed"},
    ]
    return result


def setup(tmp_path, monkeypatch):
    from orchestrator.moneyflow_continuation import recovery

    monkeypatch.setattr(recovery, "worker_absent", lambda pid: None)
    plan = plan_for(("moneyflow_ths",), ("2026-10-14",))
    evidence = tmp_path / "failure.json"
    write_json(evidence, {"failed_run_id": PARENT, "events": facts()})
    plan["launch_recovery"] = {
        "dataset": "moneyflow_ths",
        "trade_date": "2026-10-14",
        "layer": "silver",
        "failed_run_id": PARENT,
        "raw_sha256": SHA,
        "evidence": {"path": str(evidence), "sha256": file_hash(evidence)},
    }
    unit = plan["units"][0]
    journal = Journal(plan, tmp_path / "journal")
    files = journal.prepare(unit, "silver", AT, SHA, {})
    directory = journal.action_dir(unit, "silver")
    write_json(
        directory / "send_intent.json", {"request_sha256": digest(files["request"])}
    )
    write_json(
        directory / "response.json",
        {
            "request_sha256": digest(files["request"]),
            "value": {
                "data": {
                    "launchRun": {
                        "__typename": "LaunchRunSuccess",
                        "run": {"runId": PARENT},
                    }
                }
            },
        },
    )
    origin = NS(
        job_name="silver_moneyflow_ths_update_job",
        repository_origin=NS(
            repository_name="__repository__",
            code_location_origin=NS(location_name="orchestrator"),
        ),
    )
    parent = NS(
        run_id=PARENT,
        parent_run_id=None,
        root_run_id=None,
        status=NS(value="FAILURE"),
        job_name="silver_moneyflow_ths_update_job",
        run_config={},
        remote_job_origin=origin,
        tags={
            "dagster/partition": "2026-10-14",
            "dagster/partition_set": "silver_moneyflow_ths_update_job_partition_set",
            "dagster/run_key": "silver_moneyflow_ths:2026-10-14:" + SHA,
        },
        asset_selection=None,
        asset_check_selection=None,
        resolved_op_selection=None,
        op_selection=None,
        step_keys_to_execute=[
            "silver_moneyflow_ths",
            "silver_moneyflow_ths_silver_moneyflow_ths_standardization_check",
        ],
    )
    records = []
    for f in facts():
        cause = None
        for error in reversed(f["errors"]):
            cause = NS(cls_name=error["class"], message=error["message"], cause=cause)
        records.append(
            NS(
                event_log_entry=NS(
                    message=f["message"],
                    dagster_event=NS(
                        event_type_value=f["event"], event_specific_data=NS(error=cause)
                    ),
                )
            )
        )
    backend = NativeBackend(
        NS(
            event_log_storage=NS(
                get_records_for_run=lambda *a, **k: NS(records=records)
            )
        )
    )
    backend.staging = tmp_path / "staging"
    child = copy.deepcopy(parent)
    child.run_id, child.parent_run_id, child.root_run_id, child.status = (
        CHILD,
        PARENT,
        PARENT,
        NS(value="SUCCESS"),
    )
    return plan, unit, journal, backend, parent, child, records


def test_full_reexecution_request_validates_installed_graphql_schema(
    tmp_path, monkeypatch
):
    from dagster_graphql.schema import create_schema
    from graphql import get_variable_values, parse, validate

    plan, unit, *_ = setup(tmp_path, monkeypatch)
    body = request(plan["launch_recovery"], unit, SHA)
    assert body == {"query": REEXECUTE, "variables": {"parentRunId": PARENT}}
    assert "strategy:ALL_STEPS,useParentRunTags:true" in body["query"]
    assert "executionParams" not in body["variables"]
    schema, doc = create_schema().graphql_schema, parse(body["query"])
    assert validate(schema, doc) == []
    assert get_variable_values(
        schema, doc.definitions[0].variable_definitions, body["variables"]
    ) == {"parentRunId": PARENT}


@pytest.mark.parametrize(
    "damage",
    ["none", "layer", "dataset", "date", "hash", "parent", "multiple", "evidence"],
)
def test_descriptor_is_explicit_single_scope(tmp_path, monkeypatch, damage):
    plan, *_ = setup(tmp_path, monkeypatch)
    value = plan["launch_recovery"]
    if damage == "layer":
        value["layer"] = "raw"
    if damage == "dataset":
        value["dataset"] = "moneyflow"
    if damage == "date":
        value["trade_date"] = "2026-10-15"
    if damage == "hash":
        value["raw_sha256"] = "bad"
    if damage == "parent":
        value["failed_run_id"] = "bad"
    if damage == "multiple":
        plan["launch_recovery"] = [value, value]
    if damage == "evidence":
        value["evidence"] = {}
    if damage == "none":
        validate_plan(plan)
    else:
        with pytest.raises((ContinuationError, ValueError)):
            validate_plan(plan)


@pytest.mark.parametrize(
    "kind",
    [
        "PIPELINE_START",
        "STEP_START",
        "STEP_SUCCESS",
        "ASSET_MATERIALIZATION",
        "ASSET_CHECK_EVALUATION",
        "STEP_FAILURE",
        "UNKNOWN",
    ],
)
def test_business_or_unknown_event_is_not_launch_only(kind):
    value = facts()
    value.insert(6, {"event": kind, "message": "", "errors": []})
    with pytest.raises(ContinuationError):
        validate_failure(value)


@pytest.mark.parametrize(
    "damage",
    [
        "none",
        "active",
        "parent_chain",
        "candidate",
        "target",
        "events",
        "raw",
        "response",
        "partial",
        "origin",
        "evidence",
        "third",
        "unowned_child",
        "wrong_parent",
        "wrong_root",
        "wrong_key",
    ],
)
def test_parent_and_child_boundary(tmp_path, monkeypatch, damage):
    from orchestrator.moneyflow_continuation import recovery

    plan, unit, journal, backend, parent, child, records = setup(tmp_path, monkeypatch)
    # Replace just the formal target existence boundary with an isolated path.
    real_safe = recovery.safe_path
    monkeypatch.setattr(
        recovery,
        "safe_path",
        lambda p: (
            tmp_path / "silver.parquet"
            if str(p) == unit["silver"]["target"]
            else real_safe(p)
        ),
    )
    runs = [parent]
    if damage == "active":
        parent.status.value = "STARTED"
    if damage == "parent_chain":
        parent.parent_run_id = CHILD
    if damage == "candidate":
        (backend.staging / "moneyflow" / PARENT / "moneyflow_ths" / "2026-10-14").mkdir(
            parents=True
        )
    if damage == "target":
        (tmp_path / "silver.parquet").write_bytes(b"candidate")
    if damage == "events":
        records.extend(records * 2)
    if damage == "raw":
        plan["launch_recovery"]["raw_sha256"] = "c" * 64
    if damage == "response":
        path = journal.action_dir(unit, "silver") / "response.json"
        v = json.loads(path.read_text())
        v["value"]["data"]["launchRun"]["run"]["runId"] = CHILD
        write_json(path, v)
    if damage == "partial":
        parent.step_keys_to_execute = ["silver_moneyflow_ths"]
    if damage == "origin":
        parent.remote_job_origin.job_name = "bad"
    if damage == "evidence":
        records[-1].event_log_entry.message = "changed"
    if damage == "third":
        runs = [parent, child, child]
    if damage in {"unowned_child", "wrong_parent", "wrong_root", "wrong_key"}:
        runs = [parent, child]
        if damage != "unowned_child":
            f = journal.prepare(unit, ACTION, AT, SHA, {})
            write_json(
                journal.action_dir(unit, ACTION) / "send_intent.json",
                {"request_sha256": digest(f["request"])},
            )
        if damage == "wrong_parent":
            child.parent_run_id = CHILD
        if damage == "wrong_root":
            child.root_run_id = CHILD
        if damage == "wrong_key":
            child.tags["dagster/run_key"] = "bad"
    if damage == "none":
        effective, failed = effective_runs(backend, journal, unit, runs)
        assert effective == [] and failed["run_id"] == PARENT
        assert event_facts(records) == facts()
    else:
        with pytest.raises(ContinuationError):
            effective_runs(backend, journal, unit, runs)


def test_child_selection_keeps_failure_and_old_files(tmp_path, monkeypatch):
    _plan, unit, journal, backend, parent, child, _ = setup(tmp_path, monkeypatch)
    before = {
        p.name: p.read_bytes() for p in journal.action_dir(unit, "silver").iterdir()
    }
    f = journal.prepare(unit, ACTION, AT, SHA, {})
    write_json(
        journal.action_dir(unit, ACTION) / "send_intent.json",
        {"request_sha256": digest(f["request"])},
    )
    selected, failed = effective_runs(backend, journal, unit, [child, parent])
    assert selected == [child] and failed["status"] == "FAILURE"
    assert {
        p.name: p.read_bytes() for p in journal.action_dir(unit, "silver").iterdir()
    } == before
    assert parent.status.value == "FAILURE"


def test_without_descriptor_old_failed_behavior_still_stops(tmp_path):
    plan = plan_for()
    unit = plan["units"][0]
    with pytest.raises(ContinuationError):
        Journal(plan, tmp_path).prepare(unit, ACTION, AT, SHA, {})
    s = snapshot()
    s["silver"].update(failed=True, runs=[{"run_id": PARENT, "status": "FAILURE"}])
    with pytest.raises(ContinuationError, match="native_run_failed"):
        next_action(s)


class RecoveryFake(FakeNative):
    """Controller-only boundary; parent audit is covered separately above."""

    def snapshots(self, units, journal=None):
        result = []
        for unit in units:
            s = snapshot()
            s.update(
                dataset=unit["dataset"], trade_date=unit["trade_date"], registered=True
            )
            s["raw"].update(ready=True, reason="ready", sha256=SHA)
            item = self.native.get((unit["dataset"], unit["trade_date"], ACTION))
            s["silver"].update(
                action=ACTION, failed_launch={"run_id": PARENT, "status": "FAILURE"}
            )
            if item:
                s["silver"].update(
                    ready=item["status"] == "SUCCESS",
                    active=item["status"] == "QUEUED",
                    failed=item["status"] == "FAILURE",
                    owned="send_intent" in journal.read(unit, ACTION),
                    runs=[{"run_id": item["run_id"], "status": item["status"]}],
                    reason="ready"
                    if item["status"] == "SUCCESS"
                    else "missing_materialization",
                )
            result.append(s)
        return result

    def mutate(self, body):
        assert body == {"query": REEXECUTE, "variables": {"parentRunId": PARENT}}
        self.posts.append(body)
        key = ("moneyflow_ths", "2026-10-14", ACTION)
        assert key not in self.native
        self.native[key] = {"run_id": CHILD, "status": "QUEUED", "body": body}
        if self.lose_response:
            raise OSError("response lost after creation")
        return {
            "data": {
                "launchRun": {"__typename": "LaunchRunSuccess", "run": {"runId": CHILD}}
            }
        }


@pytest.mark.parametrize("lost_response", [False, True])
def test_controller_one_reexecution_restart_repeat_preserves_old_budget(
    tmp_path, monkeypatch, lost_response
):
    plan, unit, journal, *_ = setup(tmp_path, monkeypatch)
    native = RecoveryFake()
    old = journal.action_dir(unit, "silver")
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    journal.budget("original-spent", 1)
    native.lose_response = lost_response
    if lost_response:
        with pytest.raises(OSError):
            submit_once(native, journal, unit, ACTION, AT, SHA)
    native.lose_response = False
    for _ in range(2):
        code, report = apply(
            native, plan, root=journal.root, output=lambda _: None, clock=lambda: AT
        )
        assert code == 0 and report["complete"]
    assert len(native.posts) == 1 and len(native.native) == 1
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    assert (
        json.loads((journal.directory / "budgets.json").read_text())["original-spent"]
        == 1
    )


def test_uncertain_reexecution_without_native_cannot_send_again(tmp_path, monkeypatch):
    _plan, unit, journal, *_ = setup(tmp_path, monkeypatch)
    f = journal.prepare(unit, ACTION, AT, SHA, {})
    write_json(
        journal.action_dir(unit, ACTION) / "send_intent.json",
        {"request_sha256": digest(f["request"])},
    )
    native = RecoveryFake()
    with pytest.raises(ContinuationError, match="uncertain_submission"):
        submit_once(native, journal, unit, ACTION, AT, SHA)
    assert native.posts == []


def test_child_plan_cannot_change_recovery_parent(tmp_path, monkeypatch):
    parent, *_ = setup(tmp_path, monkeypatch)
    entries = [{"dataset": "moneyflow_ths", "trade_date": "2026-10-14"}]
    child = make_plan(
        entries,
        {"2026-10-14"},
        AT,
        parent["verification"],
        {},
        [],
        parent,
        digest(parent),
    )
    assert child["launch_recovery"] == parent["launch_recovery"]
    wrong = copy.deepcopy(parent["launch_recovery"])
    wrong["failed_run_id"] = CHILD
    with pytest.raises(ContinuationError, match="recovery_parent_changed"):
        make_plan(
            entries,
            {"2026-10-14"},
            AT,
            parent["verification"],
            {},
            [],
            parent,
            digest(parent),
            wrong,
        )


def test_worker_presence_and_missing_exit_refused(monkeypatch):
    from orchestrator.moneyflow_continuation import recovery

    monkeypatch.setattr(recovery.os, "kill", lambda *a: None)
    with pytest.raises(ContinuationError, match="worker_still_present"):
        recovery.worker_absent(3228)
    value = facts()[:-1]
    with pytest.raises(ContinuationError):
        validate_failure(value)


def test_recovery_child_failure_stops_without_second_submission(tmp_path, monkeypatch):
    plan, unit, journal, *_ = setup(tmp_path, monkeypatch)
    native = RecoveryFake()
    submit_once(native, journal, unit, ACTION, AT, SHA)
    next(iter(native.native.values()))["status"] = "FAILURE"
    code, report = apply(
        native, plan, root=journal.root, output=lambda _: None, clock=lambda: AT
    )
    assert code == 3 and report["reason"] == "native_run_failed"
    assert len(native.posts) == 1


def test_recovery_request_rejects_changed_raw_or_date(tmp_path, monkeypatch):
    plan, unit, *_ = setup(tmp_path, monkeypatch)
    with pytest.raises(ContinuationError):
        request(plan["launch_recovery"], unit, "c" * 64)
    other = copy.deepcopy(unit)
    other["trade_date"] = "2026-10-15"
    with pytest.raises(ContinuationError):
        request(plan["launch_recovery"], other, SHA)


def test_native_reconcile_requires_exact_child_and_pinned_raw(tmp_path, monkeypatch):
    from orchestrator.moneyflow_continuation import recovery, state

    plan, unit, journal, backend, parent, child, _ = setup(tmp_path, monkeypatch)
    original_safe = recovery.safe_path
    monkeypatch.setattr(
        recovery,
        "safe_path",
        lambda p: (
            tmp_path / "silver.parquet"
            if str(p) == unit["silver"]["target"]
            else original_safe(p)
        ),
    )
    backend.recovery_journal = journal
    backend.runs = lambda *a: [parent]
    monkeypatch.setattr(state, "file_hash", lambda _: SHA)
    body = request(plan["launch_recovery"], unit, SHA)
    assert backend.reconcile(unit, ACTION, body) is None
    files = journal.prepare(unit, ACTION, AT, SHA, {})
    write_json(
        journal.action_dir(unit, ACTION) / "send_intent.json",
        {"request_sha256": digest(files["request"])},
    )
    backend.runs = lambda *a: [child, parent]
    assert backend.reconcile(unit, ACTION, body) == {
        "run_id": CHILD,
        "status": "SUCCESS",
    }
    monkeypatch.setattr(state, "file_hash", lambda _: "c" * 64)
    with pytest.raises(ContinuationError, match="raw_revision"):
        backend.reconcile(unit, ACTION, body)
    bad = copy.deepcopy(body)
    bad["variables"]["parentRunId"] = CHILD
    with pytest.raises(ContinuationError, match="request_changed"):
        backend.reconcile(unit, ACTION, bad)
