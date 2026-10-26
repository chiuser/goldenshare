"""Request accounting, initialization crash boundaries and manual/CLI resume identity."""

import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.anns_d_checkpoint import announcement_file_fingerprint
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_STARTED_TAG,
    ANNOUNCEMENT_WINDOW_TAG,
    announcement_manual_window_tags,
    announcement_restore_window_tags,
    announcement_window_tags,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_window import DAYS, run_window, state_for

archive = _archive_fixture


def test_same_manual_root_resumes_but_new_intent_refetches(archive, monkeypatch):
    clock = [datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    first = announcement_manual_window_tags(
        "root-one", DAYS[0], DAYS[-1], archive.staging, archive.policy
    )
    # LLD §3.3 exact preimage: anns_d:manual:2:root-one:2023-06-08:2023-06-10.
    assert first[ANNOUNCEMENT_WINDOW_TAG] == "c4b43cfa05b9a1d191092a20dc57cf02"
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    run_window(archive, DAYS, first, call)
    clock[0] += 2 * 86400
    resumed = announcement_manual_window_tags(
        "root-one", DAYS[0], DAYS[-1], archive.staging, archive.policy
    )
    assert resumed == first
    run_window(archive, DAYS, resumed, call)
    assert len(calls) == 3
    second = announcement_manual_window_tags(
        "root-two", DAYS[0], DAYS[-1], archive.staging, archive.policy
    )
    assert second[ANNOUNCEMENT_WINDOW_TAG] != first[ANNOUNCEMENT_WINDOW_TAG]
    run_window(archive, DAYS, second, call)
    assert len(calls) == 6


def test_frozen_input_and_policy_cannot_change(archive):
    tags = announcement_window_tags("frozen", DAYS[0], DAYS[-1])
    run_window(archive, DAYS, tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    for first, last, policy in [
        (DAYS[1], DAYS[-1], archive.policy),
        (DAYS[0], DAYS[-1], replace(archive.policy, interval_seconds=1)),
    ]:
        with pytest.raises(AnnouncementError):
            announcement_restore_window_tags(
                "frozen", first, last, archive.staging, policy
            )


def test_budget_first_initialization_crash_restores_frozen_identity(
    archive, monkeypatch
):
    import orchestrator.defs.anns_d_window as window

    clock = [datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    tags = announcement_window_tags("initialization", DAYS[0], DAYS[-1])
    atomic = window.announcement_atomic_json

    def crash(path, document):
        if path.name == "execution.json":
            raise RuntimeError("stopped between the two atomic writes")
        atomic(path, document)

    monkeypatch.setattr(window, "announcement_atomic_json", crash)
    with pytest.raises(RuntimeError, match="two atomic writes"):
        run_window(
            archive, DAYS, tags,
            lambda *_: pytest.fail("source before execution was durable"),
        )
    directory = archive.staging / "anns_d/windows/initialization"
    assert (directory / "budget.json").exists()
    assert not (directory / "execution.json").exists()
    assert json.loads((directory / "budget.json").read_text())["requests"] == 0
    clock[0] += 86400
    frozen = announcement_restore_window_tags(
        "initialization", DAYS[0], DAYS[-1], archive.staging, archive.policy
    )
    assert frozen == tags
    monkeypatch.setattr(window, "announcement_atomic_json", atomic)
    run_window(archive, DAYS, frozen, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    state = state_for(archive, "initialization")
    assert state["identity"]["started_at"] == float(tags[ANNOUNCEMENT_STARTED_TAG])


@pytest.mark.parametrize("corruption", ["missing", "invalid_json", "wrong_counts"])
def test_existing_execution_never_resets_missing_or_corrupt_budget(archive, corruption):
    tags = announcement_window_tags("accounting", DAYS[0], DAYS[-1])
    run_window(archive, DAYS, tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    path = archive.staging / "anns_d/windows/accounting/budget.json"
    if corruption == "missing":
        path.unlink()  # Deliberate corruption of this test's temporary execution only.
    elif corruption == "invalid_json":
        path.write_text("{broken")
    else:
        document = json.loads(path.read_text())
        document["requests"] += 1
        path.write_text(json.dumps(document))
    baseline = path.read_bytes() if path.exists() else None
    with pytest.raises(AnnouncementError):
        run_window(
            archive, DAYS, tags, lambda *_: pytest.fail("invalid accounting read source")
        )
    assert (path.read_bytes() if path.exists() else None) == baseline


def test_consumed_budget_without_execution_is_not_zero_initialized(archive):
    tags = announcement_window_tags("missing-execution", DAYS[0], DAYS[-1])
    run_window(archive, DAYS, tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    path = archive.staging / "anns_d/windows/missing-execution/execution.json"
    path.unlink()
    with pytest.raises(AnnouncementError, match="legacy_execution"):
        run_window(archive, DAYS, tags, lambda *_: pytest.fail("source"))


def test_complete_capture_can_build_after_request_allowance_is_used(archive, monkeypatch):
    archive.policy = replace(archive.policy, max_day_requests=1, max_window_requests=1)
    tags = announcement_window_tags("capture", DAYS[0], DAYS[0])
    original = AnnouncementStore.build_day

    def crash(*_args, **_kwargs):
        raise RuntimeError("capture complete before candidate build")

    monkeypatch.setattr(AnnouncementStore, "build_day", crash)
    with pytest.raises(RuntimeError, match="capture complete"):
        run_window(archive, DAYS[:1], tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    monkeypatch.setattr(AnnouncementStore, "build_day", original)
    run_window(
        archive, DAYS[:1], tags, None,
        factory=lambda *_: pytest.fail("complete capture requested source"),
    )
    budget = json.loads((
        archive.staging / "anns_d/windows/capture/budget.json"
    ).read_text())
    assert budget["requests"] == 1
    assert archive.target(DAYS[0]).exists()


def test_committed_file_recovery_does_not_need_request_allowance(archive):
    archive.policy = replace(archive.policy, max_day_requests=1, max_window_requests=1)
    tags = announcement_window_tags("committed", DAYS[0], DAYS[0])
    run_window(archive, DAYS[:1], tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    before = announcement_file_fingerprint(archive.target(DAYS[0]))
    run_window(
        archive, DAYS[:1], tags, None,
        factory=lambda *_: pytest.fail("committed file created source"),
    )
    assert announcement_file_fingerprint(archive.target(DAYS[0])) == before


def test_request_allowance_is_not_renewed_by_resume(archive):
    archive.policy = replace(archive.policy, max_window_requests=2)
    days = (*DAYS, "2023-06-11")
    tags = announcement_window_tags("exhausted", days[0], days[-1])
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    for _ in range(2):
        with pytest.raises(AnnouncementError, match="window_budget"):
            run_window(archive, days, tags, call)
    assert calls == ["20230608", "20230609"]
    state = state_for(archive, "exhausted")
    assert state["requests"] == 2
    assert state["files_completed"] == list(DAYS[:2])
    assert state["unattempted_days"] == ["2023-06-11"]


def test_missing_promoted_day_evidence_does_not_refetch(archive):
    tags = announcement_window_tags("lost-proof", DAYS[0], DAYS[-1])
    run_window(archive, DAYS, tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    state = state_for(archive, "lost-proof")
    Path(state["days"][DAYS[0]]["checkpoint"]).unlink()
    with pytest.raises(AnnouncementError, match="delivery_missing"):
        run_window(archive, DAYS, tags, lambda *_: pytest.fail("lost proof refetched"))


def test_completed_file_progress_does_not_regress_during_resume(archive):
    tags = announcement_window_tags("progress", DAYS[0], DAYS[-1])
    run_window(archive, DAYS, tags, lambda *_: ([], ANNOUNCEMENT_FIELDS))
    events = []
    archive.control.emit = events.append
    archive.control.progress(active_run_id="resuming-run")
    run_window(
        archive, DAYS, tags, None,
        factory=lambda *_: pytest.fail("completed file requested source"),
    )
    observed = [e["files_completed"] for e in events if "files_completed" in e]
    assert observed and set(observed) == {3}
    assert state_for(archive, "progress")["active_run_id"] == "resuming-run"


@pytest.mark.parametrize(
    "error,failure_phase",
    [
        (RuntimeError("post-submit log failed"), "failed"),
        (AnnouncementCancelled("announcement_cancelled"), "cancelled"),
    ],
)
@pytest.mark.parametrize("failure_event", ["promoted", "file_promoted"])
def test_post_promote_progress_failure_keeps_proof_and_resumes_without_source(
    archive, error, failure_phase, failure_event
):
    day = DAYS[0]
    tags = announcement_window_tags("post-promote", day, day)
    calls, events = [], []

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    def emit(event):
        if event.get("phase") == failure_event:
            raise error
        events.append(event)

    archive.control.emit = emit
    with pytest.raises(type(error)):
        run_window(archive, (day,), tags, call)
    fingerprint = announcement_file_fingerprint(archive.target(day))
    assert fingerprint is not None
    state = state_for(archive, "post-promote")
    record = state["days"][day]
    assert state["files_completed"] == [day]
    assert state["failed_days"] == ([day] if failure_phase == "failed" else [])
    assert record["phase"] == "promoted" and record["failure_phase"] == failure_phase
    assert record["fingerprint"] == fingerprint
    saved_checkpoint = record["checkpoint"]
    assert Path(saved_checkpoint).exists()
    day_checkpoint = json.loads(Path(saved_checkpoint).read_text())
    assert day_checkpoint["phase"] == "promoted"
    assert day_checkpoint["delivery"]["fingerprint"] == fingerprint
    if failure_event == "promoted":
        assert day_checkpoint["failure_phase"] == failure_phase
        assert day_checkpoint["reason"] == record["reason"]
    else:
        assert "failure_phase" not in day_checkpoint
    summary = events[-1]
    assert summary["phase"] == failure_phase
    assert summary["files_completed_dates"] == [day]
    assert summary["failed_days"] == state["failed_days"]
    assert summary["failure_reasons"][day] == record["reason"]
    archive.control.emit = events.append
    run_window(
        archive, (day,), tags, None,
        factory=lambda *_: pytest.fail("committed day refetched after log failure"),
    )
    recovered = state_for(archive, "post-promote")
    assert calls == ["20230608"]
    assert announcement_file_fingerprint(archive.target(day)) == fingerprint
    assert recovered["phase"] == "files_completed" and recovered["failed_days"] == []
    assert recovered["days"][day]["checkpoint"] == saved_checkpoint
    assert recovered["days"][day]["fingerprint"] == fingerprint
    assert "failure_phase" not in recovered["days"][day]
    assert "reason" not in recovered["days"][day]
    recovered_day = json.loads(Path(saved_checkpoint).read_text())
    assert recovered_day["phase"] == "promoted"
    assert "failure_phase" not in recovered_day and "reason" not in recovered_day


@pytest.mark.parametrize("failure_event", ["promoted", "file_promoted"])
def test_post_promote_progress_failure_stops_later_days(archive, failure_event):
    tags = announcement_window_tags("post-promote-stop", DAYS[0], DAYS[-1])
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    def emit(event):
        if event.get("phase") == failure_event:
            # Even a source-shaped reason here is a post-commit observation failure.
            raise AnnouncementError("announcement_source_timeout")

    archive.control.emit = emit
    with pytest.raises(AnnouncementError, match="source_timeout"):
        run_window(archive, DAYS, tags, call)
    state = state_for(archive, "post-promote-stop")
    assert calls == ["20230608"]
    assert state["files_completed"] == [DAYS[0]]
    assert state["failed_days"] == [DAYS[0]]
    assert state["unattempted_days"] == list(DAYS[1:])
    assert all(not archive.target(day).exists() for day in DAYS[1:])


def test_zero_request_execution_also_requires_its_budget(archive):
    tags = announcement_window_tags("zero-evidence", DAYS[0], DAYS[-1])

    def fail_before_first_day(event):
        if event.get("phase") == "files_running":
            raise RuntimeError("interrupted before requesting source")

    archive.control.emit = fail_before_first_day
    with pytest.raises(RuntimeError, match="before requesting source"):
        run_window(archive, DAYS, tags, lambda *_: pytest.fail("no source"))
    path = archive.staging / "anns_d/windows/zero-evidence/budget.json"
    assert json.loads(path.read_text())["requests"] == 0
    path.unlink()
    archive.control.emit = lambda _: None
    with pytest.raises(AnnouncementError, match="window_budget_missing"):
        run_window(archive, DAYS, tags, lambda *_: pytest.fail("missing budget source"))
    assert not path.exists()


def test_old_execution_is_not_automatically_migrated(archive):
    tags = announcement_window_tags("old-window", DAYS[0], DAYS[-1])
    directory = archive.staging / "anns_d/windows/old-window"
    directory.mkdir(parents=True)
    path = directory / "admission.json"
    path.write_text('{"completed":[]}')
    with pytest.raises(AnnouncementError, match="legacy_execution"):
        run_window(archive, DAYS, tags, lambda *_: pytest.fail("old execution source"))
    assert path.read_text() == '{"completed":[]}'
    assert not (directory / "execution.json").exists()
    assert not (directory / "budget.json").exists()


def test_cli_resume_reads_frozen_time_and_plan_is_zero_write(
    archive, monkeypatch, capsys
):
    import orchestrator.defs.anns_d_cli as cli

    clock = [datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(archive.root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging))
    monkeypatch.setenv("TUSHARE_TOKEN", "isolated-announcement-test")
    monkeypatch.setattr(cli, "TushareResource", lambda **kw: SimpleNamespace(**kw))
    calls, failing = [], [True]

    def factory(*_args):
        def call(params, control):
            calls.append(params["ann_date"])
            if params["ann_date"] == "20230609" and failing[0]:
                return [], ()
            return [], ANNOUNCEMENT_FIELDS
        return call

    monkeypatch.setattr(cli, "AnnouncementProcessCall", factory)
    args = [
        "--start-date", DAYS[0], "--end-date", DAYS[-1],
        "--interval-seconds", "0", "--window-id", "cli-resume",
    ]
    with pytest.raises(AnnouncementError, match="window_failed"):
        cli.announcement_cli(["run", *args])
    before = state_for(archive, "cli-resume")["identity"]
    clock[0] += 2 * 86400
    capsys.readouterr()
    files_before = {str(p): p.read_bytes() for p in archive.staging.rglob("*") if p.is_file()}
    assert cli.announcement_cli(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["started_at"] == before["started_at"]
    assert {str(p): p.read_bytes() for p in archive.staging.rglob("*") if p.is_file()} == files_before
    failing[0] = False
    assert cli.announcement_cli(["run", *args]) == 0
    assert calls == ["20230608", "20230609", "20230610", "20230609"]
    assert state_for(archive, "cli-resume")["identity"] == before
