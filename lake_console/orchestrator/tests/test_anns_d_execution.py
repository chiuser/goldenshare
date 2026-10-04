import json

import pytest

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementWindowBudget,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_execution import (
    update_announcement_day,
    verify_announcement_delivery,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row


def context(store):
    return AnnouncementCheckpoint(
        store.directory / "day.json", {"day": "2023-06-09"}
    ), AnnouncementWindowBudget(store.directory / "window.json", "window", store.policy)


def test_daily_replay_readback_and_file_event_failure(archive):
    cp, budget = context(archive)
    calls = []

    def call(params, control):
        calls.append(params)
        return [source_row()], ANNOUNCEMENT_FIELDS

    delivery = update_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    assert verify_announcement_delivery(archive, "2023-06-09", cp) == delivery
    assert (
        update_announcement_day(
            "2023-06-09",
            lambda *_: pytest.fail("no source call"),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
        == delivery
    )
    assert len(calls) == 1

    def fail(event):
        raise OSError("event reporting unavailable")

    archive.control.emit = fail
    with pytest.raises(OSError):
        update_announcement_day(
            "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
        )
    assert archive.target("2023-06-09").exists()
    archive.control.emit = lambda *_: None
    update_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    assert len(calls) == 1 and cp.document["phase"] == "promoted"


def test_cancel_and_failed_terminal_state(archive):
    cp, budget = context(archive)
    archive.control.cancelled = lambda: True
    with pytest.raises(AnnouncementCancelled):
        update_announcement_day(
            "2023-06-09",
            lambda *_: None,
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    assert json.loads(cp.path.read_text())["phase"] == "cancelled"
    archive.control.cancelled = lambda: False
    with pytest.raises(AnnouncementError):
        update_announcement_day(
            "2023-06-09",
            lambda *_: ([], ()),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    assert (
        cp.document["phase"] == "failed" and not archive.target("2023-06-09").exists()
    )


def test_file_changed_invalidates_delivery(archive):
    cp, budget = context(archive)
    update_announcement_day(
        "2023-06-09",
        lambda *_: ([source_row()], ANNOUNCEMENT_FIELDS),
        archive,
        cp,
        archive.control,
        budget,
        archive.policy,
    )
    archive.target("2023-06-09").write_bytes(b"bad")
    with pytest.raises(AnnouncementError, match="file_changed"):
        verify_announcement_delivery(archive, "2023-06-09", cp)


archive = _archive_fixture


@pytest.mark.parametrize("mode", ["capture", "rename"])
def test_abrupt_process_exit_resumes_from_durable_evidence(tmp_path, mode):
    import subprocess
    import sys
    from dataclasses import replace

    from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
    from orchestrator.defs.anns_d_io import AnnouncementStore
    from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

    run = subprocess.run(
        [sys.executable, "-B", "-m", "tests.anns_d_exit_support", str(tmp_path), mode],
        timeout=10,
        check=False,
    )
    assert run.returncode == 17
    policy = replace(AnnouncementPolicy(), interval_seconds=0)
    store = AnnouncementStore(
        tmp_path / "lake",
        tmp_path / "staging",
        "exit-run",
        policy,
        AnnouncementControl(),
    )
    cp, budget = context(store)
    calls = []

    def call(params, control):
        calls.append(params["offset"])
        return [source_row()], ANNOUNCEMENT_FIELDS

    result = update_announcement_day(
        "2023-06-09", call, store, cp, store.control, budget, policy
    )
    assert result["written_rows"] == 1
    assert calls == ([0] if mode == "capture" else [])
    assert verify_announcement_delivery(store, "2023-06-09", cp)["written_rows"] == 1


def test_keyboard_interrupt_records_cancelled_and_keeps_commits(archive):
    cp, budget = context(archive)

    def interrupt(*_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        update_announcement_day(
            "2023-06-09",
            interrupt,
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    assert cp.document["phase"] == "cancelled"


def test_changed_source_evidence_prevents_green_delivery(archive):
    cp, budget = context(archive)
    delivery = update_announcement_day(
        "2023-06-09",
        lambda *_: ([source_row()], ANNOUNCEMENT_FIELDS),
        archive,
        cp,
        archive.control,
        budget,
        archive.policy,
    )
    from pathlib import Path

    Path(delivery["source_pages"][0]["path"]).write_bytes(b"bad")
    with pytest.raises(AnnouncementError, match="delivery_source_changed"):
        verify_announcement_delivery(archive, "2023-06-09", cp)
