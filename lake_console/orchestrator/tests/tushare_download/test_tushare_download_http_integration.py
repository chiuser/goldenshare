"""Real localhost socket verification, never a Tushare/live dataset acceptance test."""

import http.client
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread, get_ident

import pytest

from orchestrator.tushare_download import (
    DownloadCancelled,
    DownloadControl,
    DownloadError,
    DownloadTask,
    TushareDownloader,
    configuration,
    download_api,
)
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadProgressEvent as E
from orchestrator.tushare_download import DownloadStatus as S
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.dataset_transport_mapping import (
    DatasetTransportMapping,
    TransportBinding,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.source_transport import (
    SystemClock,
    transport_factory,
)

from .fixtures import FakeClock, contract, small_config


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    extra_length: int = 0
    wait: Event | None = None
    headers: tuple[tuple[str, str], ...] = ()
    keep_alive: bool = False


def success(items=()):
    return Reply(
        200,
        json.dumps(
            {"code": 0, "data": {"fields": ["ts_code", "trade_date"], "items": items}}
        ).encode(),
    )


@contextmanager
def localhost_source(responder):
    requests, waits = [], []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(raw, parse_float=Decimal)
            requests.append((self.path, payload, raw))
            reply = responder(payload, len(requests))
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header(
                "Content-Length", str(len(reply.body) + reply.extra_length)
            )
            self.send_header(
                "Connection", "keep-alive" if reply.keep_alive else "close"
            )
            for key, value in reply.headers:
                self.send_header(key, value)
            self.end_headers()
            if reply.wait is not None:
                waits.append(reply.wait)
                reply.wait.wait(2)
            try:
                self.wfile.write(reply.body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when the client times out/cancels in a fault case.
            self.close_connection = not reply.keep_alive

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/fixture", requests
    finally:
        for gate in waits:
            gate.set()
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def downloader_at(url, *, definition=None, clock=None, **changes):
    config = replace(
        small_config(),
        base_url=url,
        connect_timeout_seconds=0.05,
        read_timeout_seconds=0.1,
        request_timeout_seconds=0.5,
        poll_interval_seconds=0.005,
        retry_backoff_seconds=(0, 0, 0),
    )
    config = replace(config, **changes)
    definition = definition or contract()
    registry = ContractRegistry((definition,))
    bindings = DatasetTransportMapping(
        (TransportBinding(definition.dataset_id, definition.source_api_name),)
    )
    return _build_downloader(
        config,
        registry,
        bindings,
        transport_factory,
        clock or SystemClock(),
        time.sleep,
    )


@pytest.mark.parametrize("business_thread", [False, True])
def test_real_http_pagination_retry_notifications_and_business_owned_thread(
    business_thread,
):
    attempts = []

    def source(payload, number):
        params = payload["params"]
        if params["trade_date"] == "20180718":
            return success()
        if params["offset"] == 0:
            return success([["A", "20180717"], ["B", "20180717"]])
        attempts.append(True)
        return (
            Reply(503, b"server busy")
            if len(attempts) == 1
            else success([["C", "20180717"]])
        )

    with localhost_source(source) as (url, requests):
        results, events, ids, failures, summaries = [], [], [], [], []

        def run():
            try:
                ids.append(get_ident())
                downloader = downloader_at(url)

                def observer(event):
                    ids.append(get_ident())
                    events.append(event)

                with downloader.download(
                    DownloadTask(
                        "fixture.daily@1",
                        M.BY_POINT,
                        points=("2018-07-18", "2018-07-17"),
                    ),
                    on_progress=observer,
                ) as session:
                    results.extend(session)
                ids.append(get_ident())
                summaries.append(session.summary)
            except BaseException as error:  # noqa: BLE001 - business test thread returns errors to its owner.
                failures.append(error)

        if business_thread:
            thread = Thread(target=run)
            thread.start()
            main_marker = "main continues"
            thread.join(3)
            assert not thread.is_alive() and main_marker == "main continues"
        else:
            run()
        assert failures == []
        assert len(set(ids)) == 1
        assert (ids[0] != get_ident()) == business_thread
        assert [len(r.records) for r in results] == [3, 0]
        assert [e.event for e in events] == [
            E.PAGE_COMPLETED,
            E.RETRY_SCHEDULED,
            E.PAGE_COMPLETED,
            E.UNIT_COMPLETED,
            E.PAGE_COMPLETED,
            E.UNIT_COMPLETED,
        ]
        assert (
            len(requests) == 4
            and summaries[0].request_count == 4
            and summaries[0].retry_count == 1
        )
        assert all(
            path == "/fixture"
            and p["fields"].split(",") == list(contract().field_names)
            for path, p, raw in requests
        )
        assert [p["params"]["offset"] for path, p, raw in requests] == [0, 2, 2, 0]


def test_source_error_without_data_retries_before_success_schema_checks():
    def source(payload, number):
        return (
            Reply(200, b'{"code":9,"msg":"rate limit","data":null}')
            if number == 1
            else success()
        )

    with localhost_source(source) as (url, requests):
        events = []
        with downloader_at(url).download(
            DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=events.append
        ) as session:
            results = list(session)
        assert len(requests) == 2 and len(results) == 1
        assert [e.event for e in events] == [
            E.RETRY_SCHEDULED,
            E.PAGE_COMPLETED,
            E.UNIT_COMPLETED,
        ]
        assert events[0].error_code == C.RATE_LIMIT and session.summary.retry_count == 1


@pytest.mark.parametrize(
    "response,expected",
    [
        (Reply(403, b"timeout 429"), C.PERMISSION_OR_PARAMETER),
        (
            Reply(200, b'{"code":9,"msg":"permission denied","data":null}'),
            C.PERMISSION_OR_PARAMETER,
        ),
        (
            Reply(200, b'{"code":0,"data":{"fields":["a","b"],"items":[[1]]}}'),
            C.SOURCE_PROTOCOL,
        ),
    ],
)
def test_permanent_failures_do_not_retry(response, expected):
    with localhost_source(lambda payload, number: response) as (url, requests):
        with (
            pytest.raises(DownloadError) as caught,
            downloader_at(url).download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT)
            ) as session,
        ):
            next(session)
        assert caught.value.code == expected and len(requests) == 1
        assert caught.value.__context__ is None


def test_valid_json_that_is_shorter_than_declared_body_is_not_accepted():
    reply = replace(success([["A", "20180718"]]), extra_length=50)
    with localhost_source(lambda payload, number, response=reply: response) as (
        url,
        requests,
    ):
        downloader = downloader_at(url, max_retries=0, retry_backoff_seconds=())
        events = []
        with (
            pytest.raises(DownloadError) as caught,
            downloader.download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=events.append
            ) as session,
        ):
            next(session)
        assert caught.value.code == C.TRANSIENT_SOURCE and caught.value.retry_exhausted
        assert (
            len(requests) == 1 and events == [] and session.summary.delivered_units == 0
        )


def test_read_timeout_and_oversized_response_are_bounded_without_partial_delivery():
    for reply, expected, changes in (
        (replace(success(), wait=Event()), C.TRANSIENT_SOURCE, {}),
        (Reply(200, b"X" * 2000), C.CAPACITY, {"max_response_bytes": 1000}),
    ):
        with localhost_source(lambda payload, number, response=reply: response) as (
            url,
            requests,
        ):
            downloader = downloader_at(
                url, max_retries=0, retry_backoff_seconds=(), **changes
            )
            with (
                pytest.raises(DownloadError) as caught,
                downloader.download(
                    DownloadTask("fixture.daily@1", M.SNAPSHOT)
                ) as session,
            ):
                next(session)
            assert caught.value.code == expected and len(requests) == 1
            assert session.summary.delivered_units == 0


@pytest.mark.parametrize("retry", [False, True])
def test_cancellation_from_page_or_retry_callback_sends_no_next_request(retry):
    response = (
        Reply(503, b"busy")
        if retry
        else success([["A", "20180718"], ["B", "20180718"]])
    )
    with localhost_source(lambda payload, number: response) as (url, requests):
        session = None

        def observer(event):
            session.cancel()

        session = downloader_at(url).download(
            DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=observer
        )
        with pytest.raises(DownloadCancelled), session:
            next(session)
        assert len(requests) == 1 and session.summary.retry_count == 0
        assert session.summary.status == S.CANCELLED


def test_real_connection_refused_is_source_failure_without_partial_delivery():
    # Own the temporary local port, then close it; no external address is probed.
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    downloader = downloader_at(
        f"http://127.0.0.1:{port}", max_retries=0, retry_backoff_seconds=()
    )
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session,
    ):
        next(session)
    assert caught.value.code == C.TRANSIENT_SOURCE and caught.value.retry_exhausted
    assert session.summary.request_count == 1 and session.summary.delivered_units == 0


def test_cancel_after_real_read_block_never_delivers_incomplete_unit(monkeypatch):
    read1 = http.client.HTTPResponse.read1
    cancelled = [False]

    def read_and_cancel(response, size):
        block = read1(response, size)
        cancelled[0] = True
        return block

    monkeypatch.setattr(http.client.HTTPResponse, "read1", read_and_cancel)
    with localhost_source(lambda payload, number: success([["A", "20180718"]])) as (
        url,
        requests,
    ):
        with (
            pytest.raises(DownloadCancelled),
            downloader_at(url).download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT),
                control=DownloadControl(lambda: cancelled[0]),
            ) as session,
        ):
            next(session)
        assert len(requests) == 1 and session.summary.delivered_units == 0
        assert session.summary.status == S.CANCELLED


def test_successful_http_response_with_close_failure_counts_success_without_retry(
    monkeypatch,
):
    real_close = http.client.HTTPConnection.close
    closes = []

    def fail_first_close(connection):
        closes.append(True)
        if len(closes) == 1:
            raise OSError("local close failure 429")
        return real_close(connection)

    monkeypatch.setattr(http.client.HTTPConnection, "close", fail_first_close)
    # A persistent connection avoids HTTPConnection closing internally while it
    # reads response headers. The injected failure belongs to component cleanup
    # after successful parsing, rather than to getresponse().
    with localhost_source(
        lambda payload, number: replace(success(), keep_alive=True)
    ) as (url, requests):
        events = []
        with (
            pytest.raises(DownloadError) as caught,
            downloader_at(url).download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=events.append
            ) as session,
        ):
            next(session)
        assert caught.value.code == C.CLEANUP and len(requests) == 1
        assert session.summary.successful_response_count == 1
        assert (
            session.summary.retry_count == session.summary.delivered_units == 0
            and events == []
        )
        assert len(closes) == 2


def test_public_load_extraction_values_reach_real_http_request_without_business_overrides(
    monkeypatch,
):
    with localhost_source(lambda payload, number: success()) as (url, requests):
        reads = []

        def read(environ):
            reads.append(True)
            return "only-test-credential", url

        definition = contract()
        monkeypatch.setattr(configuration, "read_tushare_connection", read)
        # Replace the two definition constants only for this isolated test. The
        # production registries remain empty and gain no source acceptance claim.
        monkeypatch.setattr(download_api, "CONTRACTS", (definition,))
        monkeypatch.setattr(
            download_api,
            "BINDINGS",
            (TransportBinding(definition.dataset_id, definition.source_api_name),),
        )
        downloader = TushareDownloader.load()
        with downloader.download(
            DownloadTask("fixture.daily@1", M.SNAPSHOT)
        ) as session:
            assert len(list(session)) == 1
        assert reads == [True] and len(requests) == 1
        assert requests[0][1]["token"] == "only-test-credential"
        assert requests[0][1]["fields"].split(",") == list(definition.field_names)


@pytest.mark.parametrize("keep_alive", [False, True])
def test_real_response_reads_use_remaining_deadline_after_headers(
    monkeypatch, keep_alive
):
    clock, observed = FakeClock(), []
    body = json.dumps(
        {
            "code": 0,
            "data": {"fields": ["ts_code", "trade_date"], "items": [["A", "20180718"]]},
            "attachment": "x" * 70000,
        }
    ).encode()

    def read_block(response, size):
        if response.fp is not None:
            # Test-only inspection of the actual receiving socket provides an
            # independent check: a local copy of the timeout number is not enough.
            observed.append(response.fp.raw._sock.gettimeout())
        block = response.read(size)
        if block:
            clock.seconds += 20
        return block

    # Use real socket reads of a known size to avoid OS packet splitting changing
    # the fake-clock steps. No actual 20-second waits or memory measurements.
    monkeypatch.setattr(http.client.HTTPResponse, "read1", read_block)
    with localhost_source(
        lambda payload, number: Reply(200, body, keep_alive=keep_alive)
    ) as (url, requests):
        downloader = downloader_at(
            url,
            clock=clock,
            unit_memory_limit_bytes=12 * 1024 * 1024,
            max_response_bytes=100000,
            connect_timeout_seconds=5,
            read_timeout_seconds=30,
            request_timeout_seconds=45,
        )
        with downloader.download(
            DownloadTask("fixture.daily@1", M.SNAPSHOT)
        ) as session:
            results = list(session)
        assert len(requests) == 1 and len(results) == 1
        assert results[0].records[0].values == ("A", "20180718")
        assert observed == [30.0, 25.0]
        assert session.summary.status == S.SUCCEEDED


def test_nested_cell_is_protocol_failure_without_retry_or_partial_delivery():
    body = (
        b'{"code":0,"data":{"fields":["a"],"items":[['
        + b"[" * 550
        + b"0"
        + b"]" * 550
        + b"]]}}"
    )
    with localhost_source(lambda payload, number: Reply(200, body)) as (url, requests):
        events = []
        with (
            pytest.raises(DownloadError) as caught,
            downloader_at(url).download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=events.append
            ) as session,
        ):
            next(session)
        assert caught.value.code == C.SOURCE_PROTOCOL
        assert caught.value.__context__ is caught.value.__cause__ is None
        assert len(requests) == 1 and session.summary.retry_count == 0
        assert session.summary.delivered_units == 0 and events == []


@pytest.mark.parametrize("total_field", [b"", b',"total":null'])
@pytest.mark.parametrize("missing_offset", [0, 2])
def test_total_only_ending_requires_metadata_before_requesting_another_page(
    total_field,
    missing_offset,
):
    definition = contract()
    definition = replace(
        definition,
        pagination=replace(
            definition.pagination,
            short_page_ends=False,
            empty_page_ends=False,
            reliable_total_path=("total",),
        ),
    )
    body = b'{"code":0,"data":{"fields":["ts_code"],"items":[]}' + total_field + b"}"

    def source(payload, number):
        if payload["params"]["offset"] < missing_offset:
            return Reply(
                200,
                b'{"code":0,"data":{"fields":["ts_code"],"items":[["A"],["B"]]},"total":3}',
            )
        return Reply(200, body)

    with localhost_source(source) as (url, requests):
        # The bounded test guard stops a broken implementation after four sends.
        # Correct behavior fails on the first missing total, without the guard.
        downloader = downloader_at(url, definition=definition)
        with (
            pytest.raises(DownloadError) as caught,
            downloader.download(
                DownloadTask(definition.contract_name, M.SNAPSHOT),
                control=DownloadControl(lambda: len(requests) >= 4),
            ) as session,
        ):
            next(session)
        assert caught.value.code == C.SOURCE_PROTOCOL
        assert len(requests) == (1 if missing_offset == 0 else 2)
        assert session.summary.retry_count == 0
        assert session.summary.delivered_units == 0
