import pytest

from orchestrator.tushare_download import (
    DownloadControl,
    DownloadError,
    DownloadMode,
    DownloadStatus,
    DownloadTask,
)
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadProgressEvent as E
from orchestrator.tushare_download.download_models import AttemptFailure, CleanupIssue
from orchestrator.tushare_download.retry_policy import retry_after_at

from .fixtures import FakeClock, build, rows

TASK = DownloadTask("fixture.daily@1", DownloadMode.BY_POINT, points=("2018-07-18",))


@pytest.mark.parametrize(
    "code", [C.RATE_LIMIT, C.TRANSIENT_SOURCE, C.NO_VALID_RESPONSE]
)
def test_four_attempts_keep_same_page_and_do_not_deliver_failed_unit(code):
    downloader, calls, _, clock = build(lambda request, attempt: AttemptFailure(code))
    events = []
    session = downloader.download(TASK, on_progress=events.append)
    with pytest.raises(DownloadError) as error, session:
        list(session)
    assert error.value.code == code and error.value.retry_exhausted
    assert len(calls) == 4 and len(set(calls)) == 1
    assert session.summary.request_count == 4 and session.summary.retry_count == 3
    assert (
        session.summary.delivered_units == 0
        and session.summary.status == DownloadStatus.FAILED
    )
    assert [x.event for x in events] == [E.RETRY_SCHEDULED] * 3
    assert sum(clock.waits) == pytest.approx(7)
    assert error.value.current_scope.point == "2018-07-18"
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "code", [C.PERMISSION_OR_PARAMETER, C.SOURCE_PROTOCOL, C.UNCLASSIFIED_SOURCE]
)
def test_known_nonretryable_failures_only_send_once(code):
    downloader, calls, _, _ = build(lambda request, attempt: AttemptFailure(code))
    session = downloader.download(TASK)
    with pytest.raises(DownloadError) as error, session:
        next(session)
    assert len(calls) == 1 and not error.value.retry_exhausted


def test_successful_first_page_is_not_downloaded_again_on_second_page_retry():
    def source(request, attempt):
        if dict(request.params)["offset"] == 0:
            return rows(count=2)
        return AttemptFailure(C.TRANSIENT_SOURCE) if attempt == 1 else rows(count=1)

    downloader, calls, _, _ = build(source)
    with downloader.download(TASK) as session:
        results = list(session)
        assert len(results) == 1
        result = results[0]
    assert [dict(r.params)["offset"] for r in calls] == [0, 2, 2]
    assert len(result.records) == 3 and result.statistics.retry_count == 1


def test_cleanup_failure_disables_source_retry():
    failure = AttemptFailure(
        C.TRANSIENT_SOURCE, cleanup_errors=(CleanupIssue("http_response", "OSError"),)
    )
    downloader, calls, _, _ = build(lambda request, attempt: failure)
    with pytest.raises(DownloadError) as error, downloader.download(TASK) as session:
        next(session)
    assert (
        len(calls) == 1
        and error.value.cleanup_errors
        and not error.value.retry_exhausted
    )


def test_business_cancellation_check_timeout_is_original_and_not_a_source_retry():
    failure = TimeoutError("business check timeout 429")

    def check():
        raise failure

    downloader, calls, _, _ = build()
    with (
        pytest.raises(TimeoutError) as caught,
        downloader.download(TASK, control=DownloadControl(check)) as session,
    ):
        next(session)
    assert caught.value is failure and calls == []


def test_retry_after_date_seconds_and_invalid_values():
    clock = FakeClock()
    assert retry_after_at("10", clock) == 10
    assert retry_after_at("Thu, 22 Oct 2026 00:00:10 GMT", clock) == 10
    assert retry_after_at("Wed, 21 Oct 2026 23:59:59 GMT", clock) == 0
    for value in ("bad", "-1", "NaN", "inf"):
        assert retry_after_at(value, clock) is None
