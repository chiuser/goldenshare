"""Real owned processes/SDK/loopback; never requests the formal Tushare host.

The worker command seam only redirects the installed SDK URL in a child. Body
fields come from the independent 20-field public fixture, not the transport.
"""

import contextlib
import http.server
import json
import os
import select
import signal
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.source_readiness import moneyflow_transport as transport
from orchestrator.defs.tushare_request_policy import classify_tushare_error
from tests.test_moneyflow_moneyflow import FIELDS, row

TOKEN = "isolated-dummy-token"
PARAMS = {"trade_date": "20260930", "limit": 2000, "offset": 0}


@pytest.fixture
def workers(monkeypatch):
    owned = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        if args[0][0] == sys.executable:
            owned.append(process)
            assert TOKEN not in repr(args)
            assert not {"DAGSTER_HOME", "TUSHARE_TOKEN", "PGPASSWORD"} & set(
                kwargs["env"]
            )
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", launch)
    yield owned
    assert owned and all(process.poll() is not None for process in owned)
    assert all(process.stdin.closed and process.stdout.closed for process in owned)


@contextlib.contextmanager
def local_sdk_server(slow=False, rows=1):
    received, disconnected = [], threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                if slow:
                    # Continuous bytes never hit SDK's 30s socket-idle timeout.
                    for _ in range(2000):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.04)
                else:
                    self.wfile.write(
                        json.dumps(
                            {
                                "code": 0,
                                "data": {
                                    "fields": list(FIELDS),
                                    "items": [
                                        [row(f"{i + 1:06d}.SZ")[f] for f in FIELDS]
                                        for i in range(rows)
                                    ],
                                },
                            }
                        ).encode()
                    )
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, disconnected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def sdk_command(url, deadline):
    # The hook runs only when the worker imports the SDK, after its OS timer.
    script = f"""import builtins,runpy,sys
original=builtins.__import__
def load(name,*args,**kwargs):
    module=original(name,*args,**kwargs)
    if name=="tushare" and hasattr(module,"pro_api"):
        from tushare.pro.client import DataApi
        DataApi._DataApi__http_url={url!r}
    return module
builtins.__import__=load
sys.argv=["worker",{str(deadline)!r}]
runpy.run_module("orchestrator.defs.source_readiness.moneyflow_request_worker",run_name="__main__")
"""
    return [sys.executable, "-B", "-c", script]


def call(command=None, **kwargs):
    return transport.call_moneyflow_source(
        SimpleNamespace(token=TOKEN),
        "moneyflow",
        PARAMS,
        FIELDS,
        deadline=time.perf_counter() + 300,
        _command=command,
        **kwargs,
    )


def test_installed_sdk_round_trip_and_normal_30s_stream_deadline(workers):
    # One normal worker and one full-duration adverse request only.
    with local_sdk_server() as (url, requests, _):
        result = call(lambda deadline: sdk_command(url, deadline))
        assert tuple(result.columns) == FIELDS and result.rows == [row()]
        assert len(requests) == 1
        request = requests[0]
        assert request["api_name"] == "moneyflow" and request["fields"] == ",".join(
            FIELDS
        )
        assert request["params"] == {**PARAMS, "ts_type_name": url}
    with local_sdk_server(slow=True) as (url, requests, disconnected):
        started = time.perf_counter()
        with pytest.raises(
            MoneyflowContractError, match="source_total_deadline|source_worker_failed"
        ):
            call(lambda deadline: sdk_command(url, deadline))
        elapsed = time.perf_counter() - started
        assert 27 <= elapsed < 30
        assert len(requests) == 1 and disconnected.wait(1)
    assert len(workers) == 2


@pytest.mark.parametrize(
    "category,retryable",
    [
        ("source_or_data_contract", False),
        ("non_retryable", False),
        ("source_permission_or_parameter", False),
        ("rate_limit", True),
        ("transient", True),
        ("source_response_unclassified", True),
    ],
)
def test_remote_error_classification_keeps_original_policy(category, retryable):
    error = transport.source_error({"category": category, "retryable": retryable})
    assert classify_tushare_error(error) == (category, retryable)
    with pytest.raises(MoneyflowContractError):
        transport.source_error({"category": category, "retryable": not retryable})


@pytest.mark.parametrize(
    "output", [b"", struct.pack("!Q", 2**40), struct.pack("!Q", 2) + b"{}"]
)
def test_truncated_and_oversized_frames_never_become_empty_success(workers, output):
    code = f"import sys;sys.stdin.buffer.readline();sys.stdout.buffer.write({output!r});sys.stdout.buffer.flush()"
    with pytest.raises(MoneyflowContractError, match="source_worker_result"):
        call([sys.executable, "-B", "-c", code])


def test_cancel_kills_owned_worker_even_if_term_is_ignored(workers):
    started = time.perf_counter()

    def canceled():
        if time.perf_counter() - started > 0.2:
            raise KeyboardInterrupt("isolated cancellation")

    code = (
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(10)"
    )
    with pytest.raises(KeyboardInterrupt):
        call([sys.executable, "-B", "-c", code], check_cancel=canceled)
    assert time.perf_counter() - started < 2


def test_budget_rejection_precedes_worker_creation():
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        transport.call_moneyflow_source(
            SimpleNamespace(token=TOKEN),
            "moneyflow",
            PARAMS,
            FIELDS,
            deadline=time.perf_counter() + 29,
        )


def test_missing_capability_and_unresolved_token_reject_before_worker(monkeypatch):
    monkeypatch.setattr(transport.os, "access", lambda *_: False)
    with pytest.raises(MoneyflowContractError, match="source_worker_platform"):
        call()
    with pytest.raises(MoneyflowContractError, match="source_worker_token"):
        transport.call_moneyflow_source(
            SimpleNamespace(),
            "moneyflow",
            PARAMS,
            FIELDS,
            deadline=time.perf_counter() + 300,
        )


def test_installed_sdk_single_page_capacity_cost(workers, caplog, record_property):
    import logging

    with local_sdk_server(rows=2000) as (url, requests, _):
        started = time.perf_counter()
        with caplog.at_level(logging.INFO, logger=transport.__name__):
            result = call(lambda deadline: sdk_command(url, deadline))
        elapsed = time.perf_counter() - started
        assert len(result.rows) == 2000 and len(requests) == 1
        assert result.rows[0] == row("000001.SZ") and result.rows[-1] == row(
            "002000.SZ"
        )
        assert elapsed <= 2
        metric = next(r.args for r in caplog.records if r.name == transport.__name__)
        assert 0 < metric[2] < metric[3] <= 768 * 1024 * 1024
        record_property("sdk_page2000_metrics", json.dumps({"rows": 2000, "wall_seconds": elapsed, "request_elapsed_ms": metric[1], "child_peak_rss_bytes": metric[2], "pair_peak_upper_bytes": metric[3], "loopback_only": True}))


def test_rss_observation_failure_ends_owned_request(workers, monkeypatch):
    def unavailable(_):
        raise MoneyflowContractError("source_worker_rss_unavailable")

    monkeypatch.setattr(transport, "_pair_rss", unavailable)
    with pytest.raises(MoneyflowContractError, match="rss_unavailable"):
        call([sys.executable, "-B", "-c", "import time;time.sleep(10)"])


def test_parent_death_closes_real_inflight_sdk_request():
    with local_sdk_server(slow=True) as (url, requests, disconnected):
        script = f"""import subprocess,sys
from tests.test_moneyflow_transport import call,sdk_command
from orchestrator.defs.source_readiness import moneyflow_transport as transport
original=subprocess.Popen
def owned(*args,**kwargs):
    process=original(*args,**kwargs)
    if args[0][0]==sys.executable: print(process.pid,flush=True)
    return process
transport.subprocess.Popen=owned
call(lambda deadline:sdk_command({url!r},deadline))
"""
        parent = subprocess.Popen(
            [sys.executable, "-B", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=transport._environment(),
            start_new_session=True,
        )
        child_pid = None
        try:
            assert select.select([parent.stdout], [], [], 10)[0]
            child_pid = int(parent.stdout.readline())
            deadline = time.monotonic() + 10
            while not requests and time.monotonic() < deadline:
                time.sleep(0.02)
            assert len(requests) == 1
            parent.kill()
            parent.wait(timeout=2)
            assert disconnected.wait(2), (
                "child must close the in-flight socket on parent EOF"
            )
            state = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(child_pid)],
                capture_output=True,
                timeout=1,
                check=False,
            ).stdout.strip()
            assert not state or state.startswith(b"Z"), state
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=2)
            parent.stdout.close()
            if child_pid is not None:
                try:
                    if os.getpgid(child_pid) == parent.pid:
                        os.killpg(parent.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
