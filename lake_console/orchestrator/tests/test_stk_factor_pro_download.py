import json
from dataclasses import replace
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.io.stk_factor_pro_candidates import (
    release_stk_factor_pro_day_source,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    build_stk_factor_pro_run_control,
    download_stk_factor_pro_day,
)
from orchestrator.tushare_download import (
    DownloadError,
    DownloadProgressEvent,
    DownloadStatus,
)
from orchestrator.tushare_download.download_errors import DownloadErrorCode
from tests.stk_factor_pro_test_support import (
    NAMES,
    Downloader,
    connection,
    contract,
    identity,
    result,
    row,
    summary,
)
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
)


def test_single_day_retained_only_after_close_and_uses_standard_callback(tmp_path):
    value = result((row(),))
    loader = Downloader(value)
    events = []
    with connection(tmp_path) as conn:

        def check():
            assert loader.closed
            assert conn.execute("SHOW TABLES").fetchall() == []

        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=loader,
            check_cancel=check,
            on_progress=events.append,
        )
        assert source.unit_result is value
        task, kwargs = loader.calls[0]
        assert (
            task.points == ("2026-10-16",)
            and task.objects is None
            and task.filters is None
        )
        assert kwargs["on_progress"].__self__ is events
        release_stk_factor_pro_day_source(conn)


@pytest.mark.parametrize(
    "kind",
    [
        "close",
        "extra",
        "stopped",
        "cancelled",
        "failed",
        "rows",
        "units",
        "boolean",
        "task",
        "unit",
        "termination",
        "cancel_after_close",
        "contract",
    ],
)
def test_invalid_final_state_never_builds_u(tmp_path, kind):
    value, final = result((row(),)), summary(1)
    close_error = None
    extra = None
    kwargs = {}
    if kind == "close":
        close_error = DownloadError(DownloadErrorCode.CLEANUP)
    elif kind == "extra":
        extra = value
    elif kind in ("stopped", "cancelled", "failed"):
        final = replace(final, status=getattr(DownloadStatus, kind.upper()))
    elif kind == "rows":
        final = replace(final, completed_row_count=0)
    elif kind == "units":
        final = replace(final, delivered_units=0)
    elif kind == "boolean":
        final = replace(final, total_units=True)
    elif kind == "task":
        final = replace(final, task_id="other-session")
    elif kind == "unit":
        value = replace(value, unit=replace(value.unit, unit_id="bad-unit"))
    elif kind == "termination":
        value = replace(
            value, termination=replace(value.termination, all_scopes_complete=False)
        )
    elif kind == "contract":
        kwargs["contract"] = replace(contract(), contract_content_digest="a" * 64)
    loader = Downloader(value, final=final, close_error=close_error, extra=extra)

    def check():
        if kind == "cancel_after_close":
            raise dg.Failure("已取消", allow_retries=False)

    with connection(tmp_path) as conn:
        with pytest.raises((ValueError, DownloadError, dg.Failure)):
            download_stk_factor_pro_day(
                conn,
                identity=identity(),
                contract=kwargs.get("contract", contract()),
                downloader=loader,
                check_cancel=check,
            )
        assert conn.execute("SHOW TABLES").fetchall() == []
    assert loader.closed


def test_empty_source_is_complete_without_file_or_fake_failure(tmp_path):
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result()),
            check_cancel=lambda: None,
        )
        assert source.summary.download_complete
        assert (
            conn.execute("SELECT count(*) FROM stk_factor_pro_day_source").fetchone()[0]
            == 0
        )
        release_stk_factor_pro_day_source(conn)


@pytest.mark.parametrize(
    "initial", [dg.DagsterRunStatus.STARTED, dg.DagsterRunStatus.STARTING]
)
def test_cancel_control_throttles_forces_and_latches(initial):
    reads, current = [], [initial]
    clock = [0.0]

    def get(run_id):
        reads.append(run_id)
        return SimpleNamespace(run_id=run_id, status=current[0])

    control, force = build_stk_factor_pro_run_control(
        SimpleNamespace(get_run_by_id=get),
        identity=identity(),
        phase="day",
        monotonic=lambda: clock[0],
    )
    assert all(control.is_cancelled() is False for _ in range(100))
    assert len(reads) == 1
    force()
    assert len(reads) == 2
    clock[0] = 1.0
    current[0] = dg.DagsterRunStatus.CANCELING
    assert control.is_cancelled() is True
    current[0] = dg.DagsterRunStatus.STARTED
    assert control.is_cancelled() is True and len(reads) == 3
    with pytest.raises(dg.Failure):
        force()


@pytest.mark.parametrize(
    "kind", ["missing", "wrong_id", "success", "failure", "queued", "read_error"]
)
def test_cancel_control_read_error_never_becomes_false_or_source_retry(kind):
    def get(run_id):
        if kind == "read_error":
            raise OSError("synthetic")
        if kind == "missing":
            return None
        return SimpleNamespace(
            run_id="other" if kind == "wrong_id" else run_id,
            status={
                "success": dg.DagsterRunStatus.SUCCESS,
                "failure": dg.DagsterRunStatus.FAILURE,
                "queued": dg.DagsterRunStatus.QUEUED,
            }.get(kind, dg.DagsterRunStatus.STARTED),
        )

    control, _ = build_stk_factor_pro_run_control(
        SimpleNamespace(get_run_by_id=get), identity=identity(), phase="day"
    )
    with pytest.raises(dg.Failure) as error:
        control.is_cancelled()
    assert error.value.allow_retries is False


def test_real_component_http_to_day_adapter_progress_and_retry(tmp_path, monkeypatch):
    """Actual public registry/session/HTTP adapter; only upstream server is local."""
    notifications = []

    def respond(payload, number):
        assert payload["api_name"] == "stk_factor_pro"
        assert payload["fields"].split(",") == list(NAMES)
        assert payload["params"] == {
            "trade_date": "20261016",
            "limit": 10000,
            "offset": 0,
        }
        if number == 1:
            return Reply(503, b"temporarily unavailable")
        values = {
            "ts_code": "000001.SZ",
            "trade_date": "20261016",
            "close": 12.5,
            "macd_bfq": -1.25,
        }
        return Reply(
            200,
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": NAMES,
                        "items": [[values.get(name) for name in NAMES]],
                    },
                }
            ).encode(),
        )

    def observe(progress):
        notifications.append(progress.event)
        if progress.event is DownloadProgressEvent.PAGE_COMPLETED:
            raise RuntimeError("synthetic observation error")

    with localhost_source(respond) as (url, requests):
        monkeypatch.setenv("TUSHARE_TOKEN", "isolated-only")
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        with connection(tmp_path) as conn:
            source = download_stk_factor_pro_day(
                conn,
                identity=identity(),
                contract=contract(),
                check_cancel=lambda: None,
                on_progress=observe,
            )
            assert source.summary.request_count == 2 and source.summary.retry_count == 1
            assert source.summary.progress_error_count == 1
            assert set(notifications) == {
                DownloadProgressEvent.RETRY_SCHEDULED,
                DownloadProgressEvent.PAGE_COMPLETED,
                DownloadProgressEvent.UNIT_COMPLETED,
            }
            assert conn.execute(
                "SELECT close,macd_bfq,pe FROM stk_factor_pro_day_source"
            ).fetchone() == (12.5, -1.25, None)
            release_stk_factor_pro_day_source(conn)
        assert len(requests) == 2
