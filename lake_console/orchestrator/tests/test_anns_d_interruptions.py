"""Cancellation evidence uses actual temporary capture/build/promote paths.

Source transport is replaced with literal six-field rows. Native exception
objects, file IO, durable checkpoints and window recovery remain real.
"""

import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from dagster._core.errors import DagsterExecutionInterruptedError

from orchestrator.defs import anns_d_window as window
from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_source import AnnouncementProcessCall
from orchestrator.defs.anns_d_window import announcement_window_tags
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_process_support import sleeping_worker
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_window import run_window, state_for

archive = _archive_fixture
DAYS = ("2023-06-08", "2023-06-09")
ROW = {
    "ann_date": "20230608",
    "ts_code": "155162.SH",
    "name": "19津投04",
    "title": "literal interruption sample",
    "url": None,
    "rec_time": None,
}


@pytest.mark.parametrize(
    "boundary,expected_calls,completed",
    [
        ("source", ["20230608"], []),
        ("day_promoted", ["20230608"], [DAYS[0]]),
        ("file_promoted", ["20230608"], [DAYS[0]]),
        ("startup_save", [], []),
        ("startup_log", [], []),
        ("final_save", ["20230608", "20230609"], list(DAYS)),
        ("final_log", ["20230608", "20230609"], list(DAYS)),
    ],
)
def test_native_interrupt_records_cancelled_at_every_active_window_boundary(
    archive, monkeypatch, boundary, expected_calls, completed
):
    tags = announcement_window_tags(f"native-{boundary}", DAYS[0], DAYS[-1])
    interruption = DagsterExecutionInterruptedError()
    fired, calls, cancelled_saves = [], [], []
    original_save, original_json = (
        window._save_execution,
        window.announcement_atomic_json,
    )

    def interrupt():
        fired.append(True)
        raise interruption

    def source(params, control):
        calls.append(params["ann_date"])
        if boundary == "source" and not fired:
            interrupt()
        return [{**ROW, "ann_date": params["ann_date"]}], ANNOUNCEMENT_FIELDS

    def emit(event):
        phase = {
            "day_promoted": "promoted",
            "file_promoted": "file_promoted",
            "startup_log": "files_running",
            "final_log": "files_completed",
        }.get(boundary)
        if phase is not None and event.get("phase") == phase and not fired:
            interrupt()

    def save(path, state, budget):
        if not fired and (
            (
                boundary == "startup_save"
                and state["phase"] == "running"
                and state["current_day"] is None
            )
            or (boundary == "final_save" and state["phase"] == "files_completed")
        ):
            interrupt()
        return original_save(path, state, budget)

    def atomic_json(path, document):
        if Path(path).name == "execution.json" and document["phase"] == "cancelled":
            cancelled_saves.append(Path(path))
        return original_json(path, document)

    archive.control.emit = emit
    monkeypatch.setattr(window, "_save_execution", save)
    monkeypatch.setattr(window, "announcement_atomic_json", atomic_json)
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        run_window(archive, DAYS, tags, source)
    assert caught.value is interruption and len(fired) == 1
    state = state_for(archive, tags["anns_d/window_id"])
    assert state["phase"] == "cancelled"
    assert state["files_completed"] == completed
    assert state["requests"] == len(expected_calls) and calls == expected_calls
    assert len(cancelled_saves) == 1
    for day in completed:
        record = state["days"][day]
        assert record["phase"] == "promoted"
        checkpoint = json.loads(Path(record["checkpoint"]).read_text())
        assert checkpoint["phase"] == "promoted"
        assert checkpoint["delivery"]["fingerprint"] == record["fingerprint"]
    if boundary == "source":
        checkpoint = json.loads(Path(state["days"][DAYS[0]]["checkpoint"]).read_text())
        assert checkpoint["phase"] == "cancelled"
        assert state["unattempted_days"] == [DAYS[1]]
    original_identity = state["identity"]
    file_evidence = {
        day: (
            archive.target(day).stat().st_ino,
            archive.target(day).stat().st_mtime_ns,
            hashlib.sha256(archive.target(day).read_bytes()).hexdigest(),
        )
        for day in completed
    }
    archive.control.emit = lambda _: None
    result = run_window(archive, DAYS, tags, source)
    restored = state_for(archive, tags["anns_d/window_id"])
    assert tuple(result) == DAYS and restored["phase"] == "files_completed"
    assert restored["identity"] == original_identity and restored["failed_days"] == []
    assert restored["requests"] == (3 if boundary == "source" else 2)
    assert calls == expected_calls + [
        day.replace("-", "") for day in DAYS if day not in completed
    ]
    for day, evidence in file_evidence.items():
        target = archive.target(day)
        assert (
            target.stat().st_ino,
            target.stat().st_mtime_ns,
            hashlib.sha256(target.read_bytes()).hexdigest(),
        ) == evidence
    assert len(cancelled_saves) == 1


def test_native_interrupt_during_new_commit_proof_is_still_cancelled(
    archive, monkeypatch
):
    tags = announcement_window_tags("native-proof", DAYS[0], DAYS[-1])
    interruption, calls = DagsterExecutionInterruptedError(), []

    def source(params, control):
        calls.append(params["ann_date"])
        return [{**ROW, "ann_date": params["ann_date"]}], ANNOUNCEMENT_FIELDS

    def emit(event):
        if event.get("phase") == "promoted":
            raise RuntimeError("temporary progress-report failure")

    archive.control.emit = emit

    # Only the window's extra proof hash is interrupted. The producer's actual
    # page/candidate/target hashes and real committed checkpoint are unchanged.
    def interrupt_proof(_):
        raise interruption

    monkeypatch.setattr(window, "announcement_file_fingerprint", interrupt_proof)
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        run_window(archive, DAYS, tags, source)
    assert caught.value is interruption
    state = state_for(archive, "native-proof")
    assert state["phase"] == "cancelled"
    assert state["days"][DAYS[0]]["phase"] == "cancelled"
    assert state["unattempted_days"] == [DAYS[1]]
    assert archive.target(DAYS[0]).exists() and not archive.target(DAYS[1]).exists()
    assert calls == ["20230608"] and state["requests"] == 1


@pytest.mark.parametrize(
    "error", [SystemExit("stop"), GeneratorExit(), RuntimeError("ordinary failure")]
)
def test_other_base_and_ordinary_errors_are_not_recorded_as_cancellation(
    archive, error
):
    tags = announcement_window_tags(
        f"ordinary-{type(error).__name__}", DAYS[0], DAYS[-1]
    )
    calls = []

    def source(params, control):
        calls.append(params["ann_date"])
        raise error

    with pytest.raises(type(error)) as caught:
        run_window(archive, DAYS, tags, source)
    assert caught.value is error
    state = state_for(archive, tags["anns_d/window_id"])
    assert state["phase"] == "failed" and state["failed_days"] == [DAYS[0]]
    assert state["unattempted_days"] == [DAYS[1]] and calls == ["20230608"]


@pytest.mark.parametrize("kind", ["keyboard", "control"])
def test_keyboard_and_original_control_cancellation_still_stop_before_next_day(
    archive, kind
):
    tags = announcement_window_tags(f"original-{kind}", DAYS[0], DAYS[-1])
    calls = []

    def source(params, control):
        calls.append(params["ann_date"])
        if kind == "keyboard":
            raise KeyboardInterrupt()
        archive.control.cancelled = lambda: True
        return [{**ROW, "ann_date": params["ann_date"]}], ANNOUNCEMENT_FIELDS

    with pytest.raises(
        KeyboardInterrupt if kind == "keyboard" else AnnouncementCancelled
    ):
        run_window(archive, DAYS, tags, source)
    state = state_for(archive, tags["anns_d/window_id"])
    assert state["phase"] == "cancelled" and state["requests"] == 1
    assert state["unattempted_days"] == [DAYS[1]] and calls == ["20230608"]


def test_whitelisted_schema_failure_still_attempts_next_day(archive):
    tags = announcement_window_tags("schema-still-continues", DAYS[0], DAYS[-1])
    calls = []

    def source(params, control):
        calls.append(params["ann_date"])
        if params["ann_date"] == "20230608":
            return [], ANNOUNCEMENT_FIELDS[:-1]
        return [{**ROW, "ann_date": params["ann_date"]}], ANNOUNCEMENT_FIELDS

    with pytest.raises(AnnouncementError, match="announcement_window_failed"):
        run_window(archive, DAYS, tags, source)
    state = state_for(archive, tags["anns_d/window_id"])
    assert state["phase"] == "failed" and state["failed_days"] == [DAYS[0]]
    assert state["files_completed"] == [DAYS[1]]
    assert state["requests"] == 2 and calls == ["20230608", "20230609"]


def test_native_interrupt_releases_the_actual_spawned_source_process(tmp_path):
    interruption = DagsterExecutionInterruptedError()
    before = {process.pid for process in multiprocessing.active_children()}
    policy = replace(AnnouncementPolicy(), call_timeout=30, cancel_grace=0.5)
    control = AnnouncementControl()

    def interrupt_check():
        raise interruption

    control.check = interrupt_check
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        AnnouncementProcessCall("unused", tmp_path, policy, worker=sleeping_worker)(
            {}, control
        )
    assert caught.value is interruption
    assert {process.pid for process in multiprocessing.active_children()} == before


def test_sigint_in_owned_native_job_child_preserves_the_committed_file(tmp_path):
    location = tmp_path / "native-signal-child"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DAGSTER_HOME", "TUSHARE_TOKEN"}
    }
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "tests.anns_d_interrupt_support", str(location)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((location / "report.json").read_text())
    assert report["source_interrupt"] == {
        "run_status": "CANCELED",
        "phase": "cancelled",
        "day_phase": "cancelled",
        "files_completed": [],
        "requests": 1,
        "source_calls": [{"ann_date": "20230609", "limit": 2000, "offset": 0}],
        "materializations": 0,
        "checks": 0,
        "error_sources": ["INTERRUPT"],
    }
    assert report["signal_self_pid"] == [report["pid"]]
    assert report["run_status"] == "CANCELED" and not report["success"]
    assert report["native_interrupt"] and report["error_sources"] == ["INTERRUPT"]
    assert report["materializations"] == report["checks"] == 0
    assert report["source_calls"] == [
        {"ann_date": "20230609", "limit": 2000, "offset": 0}
    ]
    state, checkpoint = report["state"], report["day_checkpoint"]
    assert state["phase"] == "cancelled" and state["files_completed"] == ["2023-06-09"]
    assert state["requests"] == 1 and state["day_requests"] == {"2023-06-09": 1}
    assert state["days"]["2023-06-09"]["failure_phase"] == "cancelled"
    assert (
        checkpoint["phase"] == "promoted" and checkpoint["failure_phase"] == "cancelled"
    )
    assert checkpoint["delivery"]["fingerprint"] == report["fingerprint"]


def test_history_capture_and_stage_share_the_native_cancellation_classification(
    archive,
):
    from orchestrator.defs.bootstrap.anns_d_history import capture_announcement_month
    from orchestrator.defs.bootstrap.anns_d_history_execution import (
        announcement_history_store,
        announcement_month_checkpoint,
        run_announcement_history_stage,
    )
    from tests.test_anns_d_history_plan import month_plan

    interruption = DagsterExecutionInterruptedError()

    class InterruptedSource:
        def batches(self, month, upper, control, on_plan):
            on_plan({"expected_rows": 1, "month_start": month, "upper_id": str(upper)})
            raise interruption

    plan = month_plan(
        archive, inventory=[{"day": "2023-06-09", "rows": 1, "upper_id": 1}]
    )
    month = plan["months"][0]
    store = announcement_history_store(plan, month, archive.control)
    checkpoint = announcement_month_checkpoint(plan, month, store)
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        capture_announcement_month(
            month["month"],
            InterruptedSource(),
            month["upper_id"],
            store,
            checkpoint,
            archive.control,
        )
    assert caught.value is interruption and checkpoint.document["phase"] == "cancelled"
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        run_announcement_history_stage(
            "capture",
            plan,
            plan["months"][0],
            archive.control,
            source=InterruptedSource(),
        )
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    checkpoint = announcement_month_checkpoint(plan, plan["months"][0], store)
    assert caught.value is interruption and checkpoint.document["phase"] == "cancelled"


def test_history_stage_build_records_native_cancel_without_capture_handler(archive):
    from orchestrator.defs.bootstrap.anns_d_history_execution import (
        announcement_history_store,
        announcement_month_checkpoint,
        run_announcement_history_stage,
    )
    from tests.test_anns_d_history_execution import FrozenSource
    from tests.test_anns_d_history_plan import month_plan

    plan = month_plan(
        archive, inventory=[{"day": "2023-06-09", "rows": 1, "upper_id": 1}]
    )
    month = plan["months"][0]
    source = FrozenSource(rows=[{**ROW, "ann_date": "20230609"}], expected=1)
    run_announcement_history_stage(
        "capture", plan, month, archive.control, source=source
    )
    interruption = DagsterExecutionInterruptedError()

    def emit(event):
        if event.get("phase") == "building" and event.get("days_completed") == 1:
            raise interruption

    archive.control.emit = emit
    with pytest.raises(DagsterExecutionInterruptedError) as caught:
        run_announcement_history_stage("build", plan, month, archive.control)
    store = announcement_history_store(plan, month, archive.control)
    checkpoint = announcement_month_checkpoint(plan, month, store)
    assert caught.value is interruption and checkpoint.document["phase"] == "cancelled"
    assert len(checkpoint.document["deliveries"]) == 1 and source.calls == 1
    assert not list(archive.root.rglob("*.parquet"))
