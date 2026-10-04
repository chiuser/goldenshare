import json
import multiprocessing
import time
from dataclasses import replace

import pytest

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
    AnnouncementWindowBudget,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_source import (
    AnnouncementProcessCall,
    announcement_request,
    capture_announcement_day,
)
from tests.anns_d_process_support import (
    exited_worker,
    sleeping_worker,
    successful_worker,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row


def capture_context(store):
    cp = AnnouncementCheckpoint(store.directory / "capture.json", {"day": "2023-06-09"})
    budget = AnnouncementWindowBudget(
        store.directory / "window.json", "window", store.policy
    )
    return cp, budget


def test_request_has_no_object_filters(archive):
    assert announcement_request("2023-06-09", 2000, archive.policy) == {
        "ann_date": "20230609",
        "limit": 2000,
        "offset": 2000,
    }
    with pytest.raises(AnnouncementError):
        announcement_request("2023-06-09", -1, archive.policy)


def test_full_page_then_tail_persisted_and_complete_reused(archive):
    cp, budget = capture_context(archive)
    calls = []
    full = [source_row(title=str(i)) for i in range(2000)]

    def call(params, control):
        calls.append(params["offset"])
        return (
            full if params["offset"] == 0 else [source_row(title="tail")]
        ), ANNOUNCEMENT_FIELDS

    result = capture_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    assert calls == [0, 2000] and result.rows == 2001 and result.last_page_rows == 1
    reread = capture_announcement_day(
        "2023-06-09",
        lambda *_: pytest.fail("no refetch"),
        archive,
        cp,
        archive.control,
        budget,
        archive.policy,
    )
    assert reread == result and json.loads(budget.path.read_text())["requests"] == 2


def test_exact_full_page_needs_empty_tail(archive):
    cp, budget = capture_context(archive)

    def call(params, control):
        return (
            [source_row(title=str(i)) for i in range(2000)]
            if params["offset"] == 0
            else []
        ), ANNOUNCEMENT_FIELDS

    result = capture_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    assert (
        result.rows == 2000
        and result.last_offset == 2000
        and result.last_page_rows == 0
    )


def test_repeated_full_page_cannot_appear_complete(archive):
    cp, budget = capture_context(archive)
    with pytest.raises(AnnouncementError, match="repeated_page"):
        capture_announcement_day(
            "2023-06-09",
            lambda *_: ([source_row()] * 2000, ANNOUNCEMENT_FIELDS),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    assert not cp.document["capture_complete"]


def test_invalid_response_retains_evidence_and_no_candidate(archive):
    cp, budget = capture_context(archive)
    with pytest.raises(AnnouncementError, match="response_schema"):
        capture_announcement_day(
            "2023-06-09",
            lambda *_: ([], ()),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    assert (
        list(archive.directory.glob("capture-*/offset-0.json"))
        and not archive.target("2023-06-09").exists()
    )


def test_mid_page_cancel_restart_from_zero_keeps_old_attempt(archive):
    cp, budget = capture_context(archive)
    cancel = [False]
    archive.control.cancelled = lambda: cancel[0]

    def emit(event):
        if event.get("rows_captured") == 2000:
            cancel[0] = True

    archive.control.emit = emit
    with pytest.raises(AnnouncementCancelled):
        capture_announcement_day(
            "2023-06-09",
            lambda *_: ([source_row()] * 2000, ANNOUNCEMENT_FIELDS),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )
    cancel[0] = False
    archive.control.emit = lambda *_: None
    calls = []

    def retry(params, control):
        calls.append(params["offset"])
        return [source_row()], ANNOUNCEMENT_FIELDS

    result = capture_announcement_day(
        "2023-06-09", retry, archive, cp, archive.control, budget, archive.policy
    )
    assert (
        calls == [0]
        and result.rows == 1
        and len(list(archive.directory.glob("capture-*"))) == 2
    )
    assert json.loads(budget.path.read_text())["day_requests"]["2023-06-09"] == 2


def test_retry_counts_and_budget_persist_across_instances(archive):
    cp, budget = capture_context(archive)
    count = [0]

    def call(params, control):
        count[0] += 1
        if count[0] == 1:
            raise AnnouncementError("announcement_source_call_failed")
        return [], ANNOUNCEMENT_FIELDS

    result = capture_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    assert result.requests == 2
    shared = AnnouncementWindowBudget(
        budget.path, "window", replace(archive.policy, max_window_requests=2)
    )
    with pytest.raises(AnnouncementError, match="window_budget"):
        shared.claim(archive.control, "2023-06-10")


def test_shared_day_budget_survives_capture_restart(archive):
    _cp, budget = capture_context(archive)
    budget.policy = replace(archive.policy, max_day_requests=1)
    budget.claim(archive.control, "2023-06-09")
    budget.finish()
    with pytest.raises(AnnouncementError, match="day_budget"):
        budget.claim(archive.control, "2023-06-09")
    budget.claim(archive.control, "2023-06-10")
    budget.finish()


def test_cooldown_and_inflight_recovery(archive):
    _cp, budget = capture_context(archive)
    budget.policy = replace(archive.policy, interval_seconds=0.12)
    budget.claim(archive.control, "2023-06-09")
    with pytest.raises(AnnouncementError, match="in_flight"):
        budget.claim(archive.control, "2023-06-10")
    budget.recover_interrupted()
    started = time.monotonic()
    budget.claim(archive.control, "2023-06-10")
    assert time.monotonic() - started >= 0.1
    assert json.loads(budget.path.read_text())["requests"] == 2


@pytest.mark.parametrize(
    "worker,expected",
    [
        (successful_worker, None),
        (sleeping_worker, "source_timeout"),
        (exited_worker, "process_exit"),
    ],
)
def test_spawn_call_bounds_and_no_live_child(tmp_path, worker, expected):
    policy = replace(
        __import__(
            "orchestrator.defs.run_contracts.anns_d", fromlist=["AnnouncementPolicy"]
        ).AnnouncementPolicy(),
        call_timeout=0.7,
        cancel_grace=0.5,
    )
    before = {p.pid for p in multiprocessing.active_children()}
    call = AnnouncementProcessCall("fake-token", tmp_path, policy, worker=worker)
    if expected:
        with pytest.raises(AnnouncementError, match=expected):
            call({}, AnnouncementControl())
    else:
        assert call({}, AnnouncementControl()) == ([], ANNOUNCEMENT_FIELDS)
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_cancel_releases_process_within_grace(tmp_path):
    from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

    policy = replace(AnnouncementPolicy(), call_timeout=30, cancel_grace=0.5)
    started = time.monotonic()
    control = AnnouncementControl(cancelled=lambda: time.monotonic() - started > 0.2)
    with pytest.raises(AnnouncementCancelled):
        AnnouncementProcessCall("fake", tmp_path, policy, worker=sleeping_worker)(
            {}, control
        )
    assert time.monotonic() - started < 1.5


archive = _archive_fixture


def test_today_and_future_requests_are_rejected(archive):
    with pytest.raises(AnnouncementError):
        announcement_request("2099-01-01", 0, archive.policy)


def test_captured_pages_changed_block_resume(archive):
    cp, budget = capture_context(archive)
    result = capture_announcement_day(
        "2023-06-09",
        lambda *_: ([source_row()], ANNOUNCEMENT_FIELDS),
        archive,
        cp,
        archive.control,
        budget,
        archive.policy,
    )
    result.pages[0].write_bytes(b"bad")
    with pytest.raises(AnnouncementError, match="capture_changed"):
        capture_announcement_day(
            "2023-06-09",
            lambda *_: pytest.fail("must not refetch"),
            archive,
            cp,
            archive.control,
            budget,
            archive.policy,
        )


def test_window_expiry_does_not_claim_new_request(archive):
    _, budget = capture_context(archive)
    budget.claim(archive.control, "2023-06-09")
    budget.finish()
    document = json.loads(budget.path.read_text())
    document["deadline"] = 0
    budget.path.write_text(json.dumps(document))
    with pytest.raises(AnnouncementError, match="window_budget"):
        budget.claim(archive.control, "2023-06-10")
    assert json.loads(budget.path.read_text())["requests"] == 1


def test_business_progress_is_monotone_within_capture_attempt(archive):
    cp, budget = capture_context(archive)
    events = []
    archive.control.emit = events.append

    def call(params, control):
        return (
            [source_row(title=str(i)) for i in range(2000)]
            if params["offset"] == 0
            else [source_row(title="tail")]
        ), ANNOUNCEMENT_FIELDS

    capture_announcement_day(
        "2023-06-09", call, archive, cp, archive.control, budget, archive.policy
    )
    rows = [event["rows_captured"] for event in events if "rows_captured" in event]
    assert rows == sorted(rows) and rows[-1] == 2001
    assert all(
        "last_business_progress_at" in event
        for event in events
        if "rows_captured" in event
    )


def test_transport_na_is_serializable_and_stored_null(archive):
    from pandas import NA

    cp, budget = capture_context(archive)
    result = capture_announcement_day(
        "2023-06-09",
        lambda *_: ([source_row(url=NA)], ANNOUNCEMENT_FIELDS),
        archive,
        cp,
        archive.control,
        budget,
        archive.policy,
    )
    assert archive.build_day("2023-06-09", result.pages)["missing_url"] == 1
