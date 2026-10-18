"""Controller restart, native failure, expired scope and stop semantics."""

import json
import os
import signal
import threading
from datetime import timedelta

import pytest

from orchestrator.moneyflow_continuation.contract import ContinuationError
from orchestrator.moneyflow_continuation.execution import (
    Progress,
    StopSignals,
    apply,
    wait_run,
)
from orchestrator.moneyflow_continuation.submission import Journal, submit_once
from tests.test_moneyflow_continuation_plan import AT, NAMES, plan_for
from tests.test_moneyflow_continuation_submission import FakeNative


def test_full_controller_and_repeat_has_zero_new_writes(tmp_path):
    plan, native, reports = plan_for(), FakeNative(), []
    code, report = apply(
        native, plan, root=tmp_path, output=reports.append, clock=lambda: AT
    )
    assert code == 0 and report["complete"] and report["completed"] == 1
    assert len(native.posts) == 3 and len(native.native) == 2
    code, second = apply(
        native, plan, root=tmp_path, output=reports.append, clock=lambda: AT
    )
    assert code == 0 and second["complete"] and len(native.posts) == 3
    completed = [json.loads(line)["completed"] for line in reports]
    assert completed == sorted(completed)


def test_reconnect_response_lost_raw_then_only_silver(tmp_path):
    plan, native = plan_for(), FakeNative()
    unit = plan["units"][0]
    native.registered.add((unit["dataset"], unit["trade_date"]))
    native.lose_response = True
    with pytest.raises(OSError):
        submit_once(native, Journal(plan, tmp_path), unit, "raw", AT)
    native.lose_response = False
    code, report = apply(
        native, plan, root=tmp_path, output=lambda _: None, clock=lambda: AT
    )
    assert code == 0 and report["complete"]
    assert len(native.posts) == 2 and len(native.native) == 2


@pytest.mark.parametrize("raw_already_succeeded", [False, True])
def test_resume_keeps_spent_raw_budget_and_observes_existing_run(
    tmp_path, raw_already_succeeded
):
    # Real 10-09 stop/resume evidence: Raw was submitted once, then the
    # submission-stage counter reached 40. That counter must remain spent;
    # observing its existing run uses the independently persistent poll budget.
    from orchestrator.moneyflow_continuation.submission import write_json

    plan, native = plan_for(), FakeNative()
    unit, journal = plan["units"][0], Journal(plan_for(), tmp_path)
    native.registered.add((unit["dataset"], unit["trade_date"]))
    original = submit_once(native, journal, unit, "raw", AT)
    if raw_already_succeeded:
        next(iter(native.native.values()))["status"] = "SUCCESS"
    raw_budget = unit["dataset"] + ":" + unit["trade_date"] + ":raw"
    write_json(journal.directory / "budgets.json", {raw_budget: 40})
    code, report = apply(
        native, plan, root=tmp_path, output=lambda _: None, clock=lambda: AT
    )
    assert code == 0 and report["complete"]
    assert len(native.posts) == 2  # The existing Raw and exactly one new Silver.
    assert len(native.native) == 2
    assert native.native[(unit["dataset"], unit["trade_date"], "raw")]["run_id"] == original["run_id"]
    assert json.loads((journal.directory / "budgets.json").read_text())[raw_budget] == 40


@pytest.mark.parametrize("expired", [False, True])
def test_existing_pending_is_observed_before_drift_blocks_next_write(tmp_path, expired):
    plan, native = plan_for(), FakeNative()
    unit = plan["units"][0]
    native.registered.add((unit["dataset"], unit["trade_date"]))
    submitted_at = AT.replace(hour=23, minute=59) if expired else AT
    submit_once(native, Journal(plan, tmp_path), unit, "raw", submitted_at)
    native.fail_guard = not expired
    code, report = apply(
        native,
        plan,
        root=tmp_path,
        output=lambda _: None,
        clock=lambda: submitted_at + (timedelta(minutes=2) if expired else timedelta()),
    )
    assert code == 3 and report["complete"] is False
    assert next(iter(native.native.values()))["status"] == "SUCCESS"
    assert len(native.posts) == 1


def test_failure_stops_entire_batch_without_skip_retry_or_deletion(tmp_path):
    plan, native = plan_for(days=("2026-10-08", "2026-10-09")), FakeNative()
    unit = plan["units"][0]
    native.registered.add((unit["dataset"], unit["trade_date"]))
    submit_once(native, Journal(plan, tmp_path), unit, "raw", AT)
    next(iter(native.native.values()))["status"] = "FAILURE"
    code, report = apply(
        native, plan, root=tmp_path, output=lambda _: None, clock=lambda: AT
    )
    assert code == 3 and report["reason"] == "native_run_failed"
    assert len(native.posts) == 1 and len(native.registered) == 1
    assert Journal(plan, tmp_path).read(unit, "raw")["send_intent"]


def test_observation_timeout_persists_background_not_false_failure(tmp_path):
    plan, native = plan_for(), FakeNative()
    unit, journal = plan["units"][0], Journal(plan, tmp_path)
    native.registered.add((unit["dataset"], unit["trade_date"]))
    run = submit_once(native, journal, unit, "raw", AT)
    native.pending = True
    journal.observe(unit, "raw", {"polls": 120})
    for _ in range(2):
        with pytest.raises(ContinuationError, match="background_run_observation_limit"):
            wait_run(
                native,
                Journal(plan, tmp_path),
                unit,
                "raw",
                run,
                threading.Event(),
                Progress(1, lambda _: None),
                clock=lambda: AT,
            )
    assert (
        next(iter(native.native.values()))["status"] == "QUEUED"
        and len(native.posts) == 1
    )


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_actual_stop_signal_no_next_native_action(tmp_path, number):
    native, plan = FakeNative(), plan_for()
    with StopSignals() as stop:
        os.kill(os.getpid(), number)
        assert stop.wait(1)
        code, report = apply(
            native,
            plan,
            root=tmp_path,
            stop=stop,
            output=lambda _: None,
            clock=lambda: AT,
        )
    assert code == 130 and report["complete"] is False and native.posts == []


def test_49_units_controller_progress_metadata_only(tmp_path):
    days = tuple(f"2026-10-{i:02d}" for i in range(8, 15))
    plan, native = plan_for(NAMES, days), FakeNative()
    code, report = apply(
        native, plan, root=tmp_path, output=lambda _: None, clock=lambda: AT
    )
    assert code == 0 and report["completed"] == 49 and len(native.posts) == 147
    assert Journal(plan, tmp_path).size() < 16 * 1024**2


def test_unknown_unit_is_not_clean_absence_or_a_write_permission():
    from orchestrator.moneyflow_continuation.execution import unit_decisions
    from tests.test_moneyflow_continuation_state import snapshot

    value = snapshot()
    value.update(unknown=True, error="unread_storage")
    result = unit_decisions([value])[0]
    assert result["next"] == "unknown" and result["reason"] == "unread_storage"
