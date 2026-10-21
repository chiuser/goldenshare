from dataclasses import replace

import pytest

from orchestrator.tushare_download import (
    DownloadCancelled,
    DownloadControl,
    DownloadError,
    DownloadTask,
)
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadProgressEvent as E
from orchestrator.tushare_download import DownloadStatus as S
from orchestrator.tushare_download.download_models import AttemptFailure

from .fixtures import ScriptTransport, build, contract, rows

TASK = DownloadTask("fixture.daily@1", M.BY_POINT, points=("2018-07-17", "2018-07-18"))


@pytest.mark.parametrize("raise_cancel", [False, True])
@pytest.mark.parametrize("last", [False, True])
@pytest.mark.parametrize("next_again", [False, True])
def test_completion_callback_cancel_delivers_current_once_then_uses_confirmed_terminal(
    raise_cancel, last, next_again
):
    downloader, calls, transports, _ = build(
        lambda request, attempt: rows(dict(request.params)["trade_date"])
    )
    task = replace(TASK, points=("2018-07-18",)) if last else TASK
    session = None

    def observer(event):
        if event.event == E.UNIT_COMPLETED:
            if raise_cancel:
                raise DownloadCancelled()
            session.cancel()

    session = downloader.download(task, on_progress=observer)
    with session:
        result = next(session)
        assert len(result.records) == 1
        assert session.summary.completed_units == session.summary.delivered_units == 1
        if next_again:
            with pytest.raises(StopIteration if last else DownloadCancelled):
                next(session)
    assert session.summary.status == (S.SUCCEEDED if last else S.CANCELLED)
    assert len(calls) == 1 and transports[0].closed == 1
    assert len(result.records) == 1  # Closing cannot invalidate business-owned data.


@pytest.mark.parametrize("event", [E.PAGE_COMPLETED, E.RETRY_SCHEDULED])
def test_incomplete_unit_cancel_stops_before_next_source_attempt(event):
    def source(request, attempt):
        return (
            rows(count=2)
            if event == E.PAGE_COMPLETED
            else AttemptFailure(C.TRANSIENT_SOURCE)
        )

    downloader, calls, _, _ = build(source)
    session = None
    seen = []

    def observer(progress):
        seen.append(progress.event)
        if progress.event == event:
            session.cancel()

    session = downloader.download(TASK, on_progress=observer)
    with pytest.raises(DownloadCancelled), session:
        next(session)
    assert len(calls) == 1 and seen == [event]
    assert session.summary.retry_count == session.summary.delivered_units == 0
    assert session.summary.status == S.CANCELLED


def test_last_result_does_not_recheck_business_cancellation():
    calls_to_check = []
    done = [False]

    def check():
        assert not done[0], "checker must not run after all results delivered"
        calls_to_check.append(True)
        return False

    downloader, _, _, _ = build()
    with downloader.download(
        replace(TASK, points=("2018-07-18",)), control=DownloadControl(check)
    ) as session:
        next(session)
        done[0] = True
        with pytest.raises(StopIteration):
            next(session)
    assert calls_to_check and session.summary.status == S.SUCCEEDED


def test_prepare_failure_never_releases_another_active_session():
    downloader, _, transports, _ = build()
    with downloader.download(TASK) as first:
        second = downloader.download(TASK)
        with pytest.raises(DownloadError) as caught:
            second.__enter__()
        assert caught.value.code == C.INPUT
        assert downloader._active_session is first
        assert len(list(first)) == 2
    assert transports[0].closed == 1 and downloader._active_session is None


def test_business_error_keeps_original_and_stops_subsequent_unit():
    downloader, calls, transports, _ = build()
    failure = ValueError("business save failed")
    session = downloader.download(TASK)
    with pytest.raises(ValueError) as caught, session:
        for _ in session:
            raise failure
    assert caught.value is failure and len(calls) == 1
    assert session.summary.status == S.FAILED and transports[0].closed == 1


def test_final_business_error_keeps_download_complete_fact():
    downloader, _, _, _ = build()
    session = downloader.download(replace(TASK, points=("2018-07-18",)))
    with pytest.raises(ValueError), session:
        next(session)
        raise ValueError("save")
    assert session.summary.status == S.FAILED and session.summary.download_complete


def test_early_break_cancel_before_enter_and_idempotent_close():
    downloader, calls, transports, _ = build()
    session = downloader.download(TASK)
    with pytest.raises(DownloadError):
        next(session)
    with session:
        next(session)
    assert session.summary.status == S.STOPPED
    before = session.summary
    session.close()
    assert session.summary is before and transports[0].closed == 1
    unentered = downloader.download(TASK)
    unentered.cancel()
    unentered.close()
    assert unentered.summary.status == S.CANCELLED
    assert len(calls) == 1


def test_unexpected_stopiteration_from_business_checker_is_a_visible_failure():
    downloader, _, _, _ = build()
    failure = StopIteration("business checker exhausted")

    def check():
        raise failure

    session = downloader.download(TASK, control=DownloadControl(check))
    with pytest.raises(RuntimeError) as caught, session:
        next(session)
    assert caught.value.__cause__ is failure
    assert session.summary.status == S.FAILED


def test_restart_of_incomplete_unit_starts_at_first_page():
    fail = [True]

    def source(request, attempt):
        offset = dict(request.params)["offset"]
        if offset == 0:
            return rows(count=2)
        return AttemptFailure(C.PERMISSION_OR_PARAMETER) if fail[0] else rows()

    downloader, calls, _, _ = build(source)
    with (
        pytest.raises(DownloadError),
        downloader.download(replace(TASK, points=("2018-07-18",))) as session,
    ):
        next(session)
    fail[0] = False
    with downloader.download(replace(TASK, points=("2018-07-18",))) as resumed:
        results = list(resumed)
    assert len(results[0].records) == 3
    assert [dict(r.params)["offset"] for r in calls] == [0, 2, 0, 2]


def test_cancel_after_valid_response_keeps_success_count_but_sends_no_page_event():
    cancelled = [False]
    events = []

    def source(request, attempt):
        cancelled[0] = True
        return rows(count=2)

    downloader, calls, _, _ = build(source)
    with (
        pytest.raises(DownloadCancelled),
        downloader.download(
            TASK,
            control=DownloadControl(lambda: cancelled[0]),
            on_progress=events.append,
        ) as session,
    ):
        next(session)
    assert len(calls) == session.summary.successful_response_count == 1
    assert events == [] and session.summary.delivered_units == 0


def test_sorting_cancellation_discards_complete_unsorted_unit_and_closes():
    events = []
    downloader, calls, transports, _ = build(
        lambda request, attempt: rows(count=2), definition=contract(strategy=1)
    )
    session = None

    def check():
        return session._control.error_location().stage.name == "ORDERING"

    session = downloader.download(
        TASK, control=DownloadControl(check), on_progress=events.append
    )
    with pytest.raises(DownloadCancelled), session:
        next(session)
    assert len(calls) == 1 and transports[0].closed == 1
    assert session.summary.completed_units == session.summary.delivered_units == 0
    assert [e.event for e in events] == [E.PAGE_COMPLETED]


@pytest.mark.parametrize("business_failure", [False, True])
def test_close_failure_does_not_hide_original_business_failure_or_retry(
    business_failure,
):
    calls = []

    class BrokenClose(ScriptTransport):
        def close(self):
            super().close()
            raise OSError("local close failed 429")

    downloader, _, transports, _ = build(
        factory=lambda binding, clock: BrokenClose(
            lambda request, attempt: rows(), calls
        )
    )
    failure = ValueError("business save failed")
    with (
        pytest.raises(ValueError if business_failure else DownloadError) as caught,
        downloader.download(TASK) as session,
    ):
        next(session)
        if business_failure:
            raise failure
    assert len(calls) == 1 and transports[0].closed == 1
    assert session.summary.status == S.FAILED and session.summary.cleanup_errors
    if business_failure:
        assert caught.value is failure
    else:
        assert caught.value.code == C.CLEANUP
