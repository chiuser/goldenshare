"""Raw parent identity from retained native evidence; isolated control/files only.

Controller tests replace candidate SQL, covered independently below with real
20-column Parquet. Neither group uses formal files or claims formal PG acceptance.
"""

import copy
import json
import tempfile
import weakref
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from orchestrator.moneyflow_continuation import recovery
from orchestrator.moneyflow_continuation.contract import (
    DATASETS,
    ContinuationError,
    digest,
    file_hash,
)
from orchestrator.moneyflow_continuation.execution import apply
from orchestrator.moneyflow_continuation.plan import make_plan, validate_plan
from orchestrator.moneyflow_continuation.recovery import (
    RAW_ACTION,
    REEXECUTE,
    effective_runs,
)
from orchestrator.moneyflow_continuation.state import NativeBackend, next_action
from orchestrator.moneyflow_continuation.submission import (
    Journal,
    submit_once,
    write_json,
)
from tests.test_moneyflow_continuation_plan import AT
from tests.test_moneyflow_continuation_state import native_run, snapshot
from tests.test_moneyflow_continuation_submission import FakeNative

PARENT = "ca3d12ad-717e-4291-a87f-6c2a3d37204a"
pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")
CHILD = "22222222-2222-4222-8222-222222222222"
SHA = "b" * 64
DAYS = (
    "2026-10-08",
    "2026-10-09",
    "2026-10-12",
    "2026-10-13",
    "2026-10-14",
    "2026-10-15",
    "2026-10-16",
)
REPORT = (
    Path(__file__).resolve().parents[2]
    / "reports/moneyflow_p4_continuation_recovery_20261017/moneyflow-oct13-failure.json"
)


def full_parent():
    entries = [
        {"dataset": d, "trade_date": day}
        for d in DATASETS
        for day in DAYS
        if (d, day)
        not in {("moneyflow_mkt_dc", DAYS[0]), ("moneyflow_mkt_dc", DAYS[1])}
    ]
    return make_plan(
        entries,
        set(DAYS),
        AT,
        {"path": "/private/tmp/proof.json", "sha256": "a" * 64},
        {},
        [],
    )


def native_records(evidence):
    records = []
    for item in evidence["native_events"]["events"]:
        error = None
        for part in reversed(item["error"]):
            error = NS(
                cls_name=part["class"],
                message=part["message"],
                cause=error,
                stack=[
                    '  File "defs/source_readiness/moneyflow_daily.py", line 91, in collect_daily_moneyflow\n    sleep_fn(min(1, MONEYFLOW_STABILITY_SECONDS - (clock() - first_end)))\n'
                ],
            )
        records.append(
            NS(
                storage_id=item["id"],
                event_log_entry=NS(
                    message=item["message"],
                    dagster_event=NS(
                        event_type_value=item["event"],
                        event_specific_data=NS(error=error),
                    ),
                ),
            )
        )
    return records


def evidence_path(monkeypatch):
    workspace = tempfile.TemporaryDirectory(
        prefix="moneyflow-evidence-", dir="/private/tmp"
    )
    weakref.finalize(monkeypatch, workspace.cleanup)
    return Path(workspace.name) / "failure.json"


def setup(tmp_path, monkeypatch):
    evidence = json.loads(REPORT.read_text())
    path = evidence_path(monkeypatch)
    write_json(path, evidence)
    parent = full_parent()
    value = {
        "dataset": "moneyflow",
        "trade_date": "2026-10-13",
        "layer": "raw",
        "failed_run_id": PARENT,
        "first_round_sha256": evidence["candidate_sha256"],
        "evidence": {"path": str(path), "sha256": file_hash(path)},
    }
    full = make_plan(
        [
            {"dataset": u["dataset"], "trade_date": u["trade_date"]}
            for u in parent["units"]
        ],
        set(DAYS),
        AT,
        parent["verification"],
        {},
        [],
        parent,
        digest(parent),
        collection_recovery=value,
    )
    plan = make_plan(
        [{"dataset": "moneyflow", "trade_date": "2026-10-13"}],
        set(DAYS),
        AT,
        full["verification"],
        {},
        [],
        full,
        digest(full),
    )
    unit = plan["units"][0]
    journal = Journal(plan, tmp_path / "journal")
    files = journal.prepare(unit, "raw", AT, None, {})
    write_json(
        journal.action_dir(unit, "raw") / "send_intent.json",
        {"request_sha256": digest(files["request"])},
    )
    write_json(
        journal.action_dir(unit, "raw") / "response.json",
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
    values = vars(native_run(unit))
    values["tags"] = {
        t["key"]: t["value"]
        for t in files["request"]["body"]["variables"]["executionParams"][
            "executionMetadata"
        ]["tags"]
    }
    old = NS(
        **values,
        run_id=PARENT,
        status=NS(value="FAILURE"),
        parent_run_id=None,
        root_run_id=None,
    )
    child = copy.deepcopy(old)
    child.run_id, child.status.value, child.parent_run_id, child.root_run_id = (
        CHILD,
        "SUCCESS",
        PARENT,
        PARENT,
    )
    records = native_records(evidence)
    backend = NativeBackend(
        NS(
            event_log_storage=NS(
                get_records_for_run=lambda *a, **k: NS(records=records)
            )
        )
    )
    backend.staging = tmp_path / "staging"
    backend.staging.mkdir()
    real_safe = recovery.safe_path
    monkeypatch.setattr(
        recovery,
        "safe_path",
        lambda p: (
            tmp_path
            / ("formal-raw" if str(p) == unit["raw"]["target"] else "formal-silver")
            if str(p) in {unit["raw"]["target"], unit["silver"]["target"]}
            else real_safe(p)
        ),
    )
    monkeypatch.setattr(recovery, "worker_absent", lambda _: None)
    monkeypatch.setattr(recovery, "validate_collection_candidate", lambda *_: None)
    return plan, unit, journal, backend, old, child, records


def test_full_parent_and_immutable_inheritance(tmp_path, monkeypatch):
    plan, *_ = setup(tmp_path, monkeypatch)
    assert (
        plan["root_scope_digest"]
        == "79c34e4ed75be094554311d6b46d29f5be11ae2d1310303a85f5f32dc39628d0"
    )
    assert len(plan["root_units"]) == 47 and len(plan["units"]) == 1
    altered = copy.deepcopy(plan["collection_recovery"])
    altered["first_round_sha256"] = SHA
    with pytest.raises(ContinuationError, match="parent_changed"):
        make_plan(
            [{"dataset": "moneyflow", "trade_date": "2026-10-13"}],
            set(DAYS),
            AT,
            plan["verification"],
            {},
            [],
            plan,
            digest(plan),
            collection_recovery=altered,
        )
    for key, value in (
        ("layer", "silver"),
        ("trade_date", "2026-10-14"),
        ("failed_run_id", CHILD),
        ("first_round_sha256", "bad"),
    ):
        bad = copy.deepcopy(plan)
        bad["collection_recovery"][key] = value
        with pytest.raises(ContinuationError):
            validate_plan(bad)


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "wrong_parent",
        "wrong_key",
        "partial",
        "third",
        "new_error",
        "too_many_events",
        "parent_running",
    ],
)
def test_explicit_raw_parent_child_and_error_boundary(tmp_path, monkeypatch, damage):
    _plan, unit, journal, backend, old, child, records = setup(tmp_path, monkeypatch)
    files = journal.prepare(unit, RAW_ACTION, AT, None, {})
    write_json(
        journal.action_dir(unit, RAW_ACTION) / "send_intent.json",
        {"request_sha256": digest(files["request"])},
    )
    runs = [old, child]
    if damage == "wrong_parent":
        child.parent_run_id = CHILD
    if damage == "wrong_key":
        child.tags["dagster/run_key"] = "different"
    if damage == "partial":
        child.step_keys_to_execute = [unit["raw"]["asset"]]
    if damage == "third":
        runs.append(child)
    if damage == "new_error":
        records[
            13
        ].event_log_entry.dagster_event.event_specific_data.error.cause.message = (
            "ValueError: other\n"
        )
    if damage == "too_many_events":
        records.extend(records * 4)
    if damage == "parent_running":
        old.status.value = "STARTED"
    if damage:
        with pytest.raises(ContinuationError):
            effective_runs(backend, journal, unit, runs, "raw")
    else:
        selected, failed = effective_runs(backend, journal, unit, runs, "raw")
        assert selected == [child] and failed["run_id"] == PARENT
        monkeypatch.setattr(
            recovery,
            "worker_absent",
            lambda _: (_ for _ in ()).throw(AssertionError("recycled unrelated pid")),
        )
        assert effective_runs(backend, journal, unit, runs, "raw")[0] == [child]


class RawRecoveryNative(FakeNative):
    def snapshots(self, units, journal=None):
        result = []
        for unit in units:
            state = snapshot()
            state.update(
                dataset=unit["dataset"], trade_date=unit["trade_date"], registered=True
            )
            state["raw"]["action"] = RAW_ACTION
            state["raw"]["preserved_failure"] = {"run_id": PARENT, "status": "FAILURE"}
            for layer, action in (("raw", RAW_ACTION), ("silver", "silver")):
                item = self.native.get((unit["dataset"], unit["trade_date"], action))
                if item:
                    state[layer].update(
                        ready=item["status"] == "SUCCESS",
                        active=item["status"] == "QUEUED",
                        failed=item["status"] == "FAILURE",
                        owned="send_intent" in journal.read(unit, action),
                        runs=[{"run_id": item["run_id"], "status": item["status"]}],
                        reason="ready"
                        if item["status"] == "SUCCESS"
                        else "missing_materialization",
                        sha256=SHA if item["status"] == "SUCCESS" else None,
                    )
            result.append(state)
        return result

    def mutate(self, body):
        if body["query"] != REEXECUTE:
            return super().mutate(body)
        assert body["variables"] == {"parentRunId": PARENT}
        self.posts.append(body)
        self.native[("moneyflow", "2026-10-13", RAW_ACTION)] = {
            "run_id": CHILD,
            "status": "QUEUED",
            "body": body,
        }
        if self.lose_response:
            raise OSError("isolated lost response")
        return {
            "data": {
                "launchRun": {"__typename": "LaunchRunSuccess", "run": {"runId": CHILD}}
            }
        }


@pytest.mark.parametrize("lost", [False, True])
def test_raw_reexecution_then_ordinary_silver_resume_and_zero_repeat(
    tmp_path, monkeypatch, lost
):
    plan, unit, journal, *_ = setup(tmp_path, monkeypatch)
    native = RawRecoveryNative()
    before = {p.name: p.read_bytes() for p in journal.action_dir(unit, "raw").iterdir()}
    journal.budget("old-spent", 1)
    native.lose_response = lost
    if lost:
        with pytest.raises(OSError):
            submit_once(native, journal, unit, RAW_ACTION, AT)
    native.lose_response = False
    for _ in range(2):
        code, report = apply(
            native, plan, root=journal.root, clock=lambda: AT, output=lambda _: None
        )
        assert code == 0, report
        assert report["completed"] == 1
    assert len(native.posts) == 2
    assert native.posts[0]["query"] == REEXECUTE
    assert (
        native.posts[1]["variables"]["executionParams"]["selector"]["jobName"]
        == "silver_moneyflow_update_job"
    )
    assert {
        p.name: p.read_bytes() for p in journal.action_dir(unit, "raw").iterdir()
    } == before
    assert (
        json.loads((journal.directory / "budgets.json").read_text())["old-spent"] == 1
    )
    assert next_action(native.snapshots([unit], journal)[0]) == "complete"


def test_raw_reexecution_failure_is_not_retried(tmp_path, monkeypatch):
    plan, unit, journal, *_ = setup(tmp_path, monkeypatch)
    native = RawRecoveryNative()
    submit_once(native, journal, unit, RAW_ACTION, AT)
    native.native[("moneyflow", "2026-10-13", RAW_ACTION)]["status"] = "FAILURE"
    code, report = apply(
        native, plan, root=journal.root, clock=lambda: AT, output=lambda _: None
    )
    assert (
        code == 3 and report["reason"] == "native_run_failed" and len(native.posts) == 1
    )


def test_first_round_real_parquet_and_hash_bound_sql_reuse(tmp_path, monkeypatch):
    from orchestrator.defs.io.moneyflow_daily_raw_writer import (
        build_daily_moneyflow_raw_candidate,
    )
    from tests.test_moneyflow_moneyflow import Clock, Source, round_pages, row

    staging = tmp_path / "staging"
    staging.mkdir()
    source = Source(
        round_pages(
            [dict(row(f"{i:06d}.SZ"), trade_date="20261013") for i in range(5574)]
        )
    )
    clock = Clock()
    directory = staging / "moneyflow" / PARENT / "moneyflow" / "2026-10-13"

    def stopped_wait(seconds):
        if (directory / "raw.parquet").exists():
            raise ValueError("isolated failure after first round")
        clock.sleep(seconds)  # Page rate limiting occurs before the stability wait.

    with pytest.raises(ValueError, match="isolated failure"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset="moneyflow",
            staging_root=staging,
            operation_id=PARENT,
            trade_date="2026-10-13",
            clock=clock,
            sleep_fn=stopped_wait,
        )
    directory = staging / "moneyflow" / PARENT / "moneyflow" / "2026-10-13"
    evidence = json.loads(REPORT.read_text())
    evidence.update(
        candidate_path=str(directory / "raw.parquet"),
        candidate_sha256=file_hash(directory / "raw.parquet"),
    )
    for page in evidence["first_round_pages"]:
        page["sha256"] = file_hash(directory / "round-1" / "scope-1" / page["file"])
    path = evidence_path(monkeypatch)
    write_json(path, evidence)
    value = {
        "dataset": "moneyflow",
        "trade_date": "2026-10-13",
        "layer": "raw",
        "failed_run_id": PARENT,
        "first_round_sha256": evidence["candidate_sha256"],
        "evidence": {"path": str(path), "sha256": file_hash(path)},
    }
    backend = NativeBackend(None)
    backend.staging = staging
    unit = next(
        u
        for u in full_parent()["units"]
        if u["dataset"] == "moneyflow" and u["trade_date"] == "2026-10-13"
    )
    recovery.validate_collection_candidate(backend, directory, unit, value)
    reads = backend.meter.count
    assert reads > 0
    recovery.validate_collection_candidate(backend, directory, unit, value)
    assert backend.meter.count == reads  # All input hashes still checked.
    old = directory / "round-1" / "scope-1" / "page-0.json"
    old.write_bytes(old.read_bytes() + b" ")
    with pytest.raises(ContinuationError, match="page_hash"):
        recovery.validate_collection_candidate(backend, directory, unit, value)


def test_collecting_parent_cost_is_charged_without_rewriting_receipt(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from orchestrator.moneyflow_continuation import state

    plan, _unit, journal, backend, *_ = setup(tmp_path, monkeypatch)
    directory = backend.staging / "moneyflow" / PARENT / "moneyflow" / "2026-10-13"
    directory.mkdir(parents=True)
    receipt = directory / "receipt.json"
    receipt.write_text(
        json.dumps(
            {"dataset": "moneyflow", "stage": "collecting", "trade_date": "2026-10-13"}
        )
    )
    before = receipt.read_bytes()
    backend.control = journal.root
    monkeypatch.setattr(
        state, "POLICY", replace(state.POLICY, raw_activity_seconds=299)
    )
    monkeypatch.setattr(
        state, "raw_moneyflow_path", lambda *_: tmp_path / "missing-raw"
    )
    monkeypatch.setattr(
        state, "silver_moneyflow_path", lambda *_: tmp_path / "missing-silver"
    )
    with pytest.raises(ContinuationError, match="session_disk_or_raw_activity_budget"):
        backend.disk_budget(plan)
    assert receipt.read_bytes() == before


def test_evidence_location_rejected_before_reading_arbitrary_file(tmp_path):
    with pytest.raises(ContinuationError, match="collection_evidence_location"):
        recovery.collection_evidence_path(tmp_path / "outside-reports.json")
    assert recovery.collection_evidence_path(
        Path("/private/tmp/moneyflow-proof.json")
    ) == Path("/private/tmp/moneyflow-proof.json")
