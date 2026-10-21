from dataclasses import FrozenInstanceError

import pytest

from orchestrator.tushare_download import DownloadError, DownloadTask
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadProgressEvent as E
from orchestrator.tushare_download import DownloadStatus as S
from orchestrator.tushare_download.download_models import AttemptFailure

from .fixtures import build, contract, rows


def golden_source(request, attempt):
    p = dict(request.params)
    if p["trade_date"] == "20261013":
        return ()
    if p["offset"] == 0:
        return rows("20261012", count=6000)
    return (
        AttemptFailure(C.TRANSIENT_SOURCE)
        if attempt == 1
        else rows("20261012", count=100)
    )


def test_independent_four_request_six_event_two_result_6100_row_example():
    downloader, calls, _, _ = build(golden_source, definition=contract(limit=6000))
    seen, summaries = [], []
    session = None

    def observer(event):
        seen.append(event)
        summaries.append(session.summary)

    session = downloader.download(
        DownloadTask(
            "fixture.daily@1", M.BY_POINT, points=("2026-10-13", "2026-10-12")
        ),
        on_progress=observer,
    )
    with session:
        results = list(session)
    assert [e.event for e in seen] == [
        E.PAGE_COMPLETED,
        E.RETRY_SCHEDULED,
        E.PAGE_COMPLETED,
        E.UNIT_COMPLETED,
        E.PAGE_COMPLETED,
        E.UNIT_COMPLETED,
    ]
    assert [e.sequence for e in seen] == [1, 2, 3, 4, 5, 6]
    assert [e.unit_row_count for e in seen] == [6000, 6000, 6100, 6100, 0, 0]
    assert [e.completed_units for e in seen] == [0, 0, 0, 1, 1, 2]
    assert [e.delivered_units for e in seen] == [0, 0, 0, 0, 1, 1]
    assert [e.progress_percent for e in seen] == [0, 0, 0, 50, 50, 100]
    assert [len(r.records) for r in results] == [6100, 0]
    assert len(calls) == 4 and session.summary.retry_count == 1
    assert session.summary.row_count == session.summary.completed_row_count == 6100
    assert (
        session.summary.status == S.SUCCEEDED
        and session.summary.successful_response_count == 3
    )
    assert summaries[3].status == S.RUNNING and summaries[3].delivered_units == 0
    assert session.poll_progress().delivered_units == 1
    assert seen[3].page_position is None and seen[3].attempt_number is None
    assert seen[3].retry_count == 1 and seen[3].error_code is None
    with pytest.raises(FrozenInstanceError):
        seen[0].current_scope.point = "changed"


@pytest.mark.parametrize(
    "event", [E.PAGE_COMPLETED, E.RETRY_SCHEDULED, E.UNIT_COMPLETED]
)
def test_each_ordinary_observer_error_does_not_repeat_source_or_drop_results(event):
    def bad(progress):
        if progress.event == event:
            raise RuntimeError("observer-only token must not be stored")

    task = DownloadTask(
        "fixture.daily@1", M.BY_POINT, points=("2026-10-12", "2026-10-13")
    )
    downloader, calls, _, _ = build(golden_source, definition=contract(limit=6000))
    with downloader.download(task, on_progress=bad) as session:
        results = list(session)
    assert len(calls) == 4 and [len(x.records) for x in results] == [6100, 0]
    assert session.summary.progress_error_count > 0
    assert session.summary.last_progress_error_type == "RuntimeError"
    assert "observer-only" not in repr(session.summary)


@pytest.mark.parametrize("operation", ["next", "close", "exit"])
def test_observer_reentry_is_rejected_without_closing_or_extra_requests(operation):
    downloader, calls, transports, _ = build(lambda r, a: rows())
    session = None

    def observer(event):
        assert session.poll_progress() is event
        if operation == "next":
            next(session)
        elif operation == "close":
            session.close()
        else:
            session.__exit__(None, None, None)

    session = downloader.download(
        DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=observer
    )
    with session:
        results = list(session)
    assert len(calls) == len(results) == 1
    assert session.summary.progress_error_count == 2 and transports[0].closed == 1
    assert session.summary.status == S.SUCCEEDED


def test_slow_retry_callback_uses_remaining_wait_and_records_callback_time():
    downloader, calls, _, clock = build(
        lambda request, attempt: (
            AttemptFailure(C.TRANSIENT_SOURCE) if attempt == 1 else ()
        )
    )

    def observer(event):
        if event.event == E.RETRY_SCHEDULED:
            clock.seconds += 2

    with downloader.download(
        DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=observer
    ) as session:
        results = list(session)
    assert len(calls) == 2 and clock.waits == []
    assert session.summary.callback_elapsed_seconds == 2
    assert results[0].statistics.waiting_seconds == 0


def test_zero_units_produces_no_events_and_no_request():
    downloader, calls, _, _ = build()
    events = []
    with downloader.download(
        DownloadTask("fixture.daily@1", M.BY_POINT, points=()),
        on_progress=events.append,
    ) as session:
        assert list(session) == []
    assert events == calls == [] and session.summary.download_complete


def test_async_or_wrong_signature_observers_rejected_without_network():
    async def async_observer(event):
        return None

    for observer in (async_observer, lambda: None, object()):
        downloader, calls, _, _ = build()
        with (
            pytest.raises(DownloadError) as caught,
            downloader.download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=observer
            ),
        ):
            pass
        assert caught.value.code == C.INPUT and calls == []


def test_unstarted_coroutine_return_is_not_run_and_is_observation_only():
    executed = []

    async def pending():
        executed.append(True)

    downloader, calls, _, _ = build()
    with downloader.download(
        DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=lambda event: pending()
    ) as session:
        results = list(session)
    assert len(results) == 1 and len(calls) == 1 and not executed
    assert session.summary.progress_error_count == 2
