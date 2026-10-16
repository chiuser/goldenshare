import json

import pytest

from orchestrator.defs.io.stock_period_raw import PeriodCancelled
from orchestrator.defs.run_contracts.stock_period import FIELDS, StockPeriodPolicy
from orchestrator.defs.stock_period_source import capture_unit


def body(days):
    return json.dumps(
        {
            "code": 0,
            "data": {
                "fields": list(FIELDS),
                "items": [
                    ["000001.SZ", d, "20261015", "week"] + [1.25] * 17 for d in days
                ],
            },
        }
    ).encode()


def test_paging_and_saved_pages_not_requested_again(tmp_path):
    calls = []
    policy = StockPeriodPolicy(page_limit=1)

    def transport(params):
        calls.append(params)
        return body(["20261016"] if params["offset"] == 0 else [])

    args = {
        "work": tmp_path,
        "request_id": "source-fixture",
        "freq": "week",
        "code": "000001.SZ",
        "listed": {"000001.SZ"},
        "aliases": {},
        "policy": policy,
    }
    result = capture_unit(**args, transport=transport)
    assert [p["offset"] for p in calls] == [0, 1] and result["rows"] == 1
    result2 = capture_unit(
        **args, transport=lambda _: pytest.fail("successful page requested again")
    )
    assert result2 == result


def test_repeated_page_empty_and_failure_do_not_complete(tmp_path):
    for index, transport in enumerate(
        [lambda _: body(["20261016"]), lambda _: body([]), lambda _: b"{}"]
    ):
        with pytest.raises(ValueError):
            capture_unit(
                request_id="source-fixture",
                work=tmp_path / str(index),
                freq="week",
                code="000001.SZ",
                listed={"000001.SZ"},
                aliases={},
                policy=StockPeriodPolicy(page_limit=1),
                transport=transport,
            )
        assert not list((tmp_path / str(index)).glob("*/complete.json"))


def test_cancel_after_page_reuses_saved_page(tmp_path):
    cancelled = False
    calls = []

    def progress(event):
        nonlocal cancelled
        cancelled = True

    def transport(params):
        calls.append(params["offset"])
        return body(["20261016"] if params["offset"] == 0 else [])

    args = {
        "work": tmp_path,
        "request_id": "source-fixture",
        "freq": "week",
        "code": "000001.SZ",
        "listed": {"000001.SZ"},
        "aliases": {},
        "policy": StockPeriodPolicy(page_limit=1),
        "transport": transport,
    }
    with pytest.raises(PeriodCancelled):
        capture_unit(**args, cancel=lambda: cancelled, progress=progress)
    capture_unit(**args)
    assert calls == [0, 1]


@pytest.fixture
def http_server():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    gate = threading.Event()
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(request)
            if self.path == "/hang":
                gate.wait(10)
            payload = body(["20261016"])
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", observed
    finally:
        gate.set()
        server.shutdown()
        server.server_close()
        thread.join()


def test_process_http_envelope_and_cancel_exits_worker(http_server):
    import os
    import time

    from orchestrator.defs.stock_period_source import HttpPage

    url, observed = http_server
    events = []
    client = HttpPage(
        token="offline",
        base_url=url,
        policy=StockPeriodPolicy(retries=0, timeout_seconds=5),
        progress=events.append,
    )
    assert (
        json.loads(
            client({"freq": "week", "ts_code": "000001.SZ", "limit": 6000, "offset": 0})
        )["code"]
        == 0
    )
    assert observed[0]["api_name"] == "stk_week_month_adj" and observed[0][
        "fields"
    ] == ",".join(FIELDS)
    events.clear()
    started = time.monotonic()
    client = HttpPage(
        token="offline",
        base_url=url + "/hang",
        policy=StockPeriodPolicy(retries=0, timeout_seconds=5),
        cancel=lambda: time.monotonic() - started > 1,
        progress=events.append,
    )
    with pytest.raises(PeriodCancelled):
        client({"freq": "week", "offset": 0})
    assert time.monotonic() - started < 4
    pid = next(e["worker_pid"] for e in events if e["stage"] == "source_worker_started")
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("signal_name", ["TERM", "KILL"])
def test_process_parent_exit_stops_own_worker_and_releases_lock(
    tmp_path, http_server, signal_name
):
    import os
    import signal
    import subprocess
    import sys
    import time

    from orchestrator.defs.bootstrap.stock_period_history import writer

    url, _ = http_server
    script = tmp_path / "coordinator.py"
    pidfile = tmp_path / "worker.json"
    staging = tmp_path / "staging"
    script.write_text("""from pathlib import Path
from orchestrator.defs.stock_period_source import HttpPage
from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy
from orchestrator.defs.io.stock_period_raw import atomic_json
from orchestrator.defs.bootstrap.stock_period_history import writer
import sys
if __name__=='__main__':
    with writer(Path(sys.argv[2])):
        def progress(p):
            if p['stage']=='source_worker_started':atomic_json(Path(sys.argv[3]),p)
        HttpPage(token='offline',base_url=sys.argv[1],policy=StockPeriodPolicy(retries=0,timeout_seconds=30),progress=progress)({'freq':'week','offset':0})
""")
    process = subprocess.Popen(
        [sys.executable, "-B", str(script), url + "/hang", str(staging), str(pidfile)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 8
        while not pidfile.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.05)
        assert pidfile.exists()
        pid = json.loads(pidfile.read_text())["worker_pid"]
        ppid = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "ppid="], text=True
        ).strip()
        assert ppid == str(process.pid)
        os.kill(process.pid, getattr(signal, "SIG" + signal_name))
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.05)
        else:
            pytest.fail("owned worker survived parent exit")
        with writer(staging):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_more_than_three_pages_and_terminal_empty_are_not_truncated(tmp_path):
    from datetime import date, timedelta

    calls = []

    def transport(params):
        offset = params["offset"]
        calls.append(offset)
        return (
            body([(date(2026, 10, 16) - timedelta(days=7 * offset)).strftime("%Y%m%d")])
            if offset < 6
            else body([])
        )

    result = capture_unit(
        request_id="source-fixture",
        work=tmp_path,
        freq="week",
        code="000001.SZ",
        listed={"000001.SZ"},
        aliases={},
        transport=transport,
        policy=StockPeriodPolicy(page_limit=1),
    )
    assert calls == list(range(7)) and result["rows"] == 6


def test_truncated_payload_and_response_budget_refuse_without_completion(tmp_path):
    for index, (payload, policy) in enumerate(
        [
            (body(["20261016"])[:-3], StockPeriodPolicy()),
            (body(["20261016"]), StockPeriodPolicy(response_bytes=64)),
        ]
    ):
        with pytest.raises(ValueError):
            capture_unit(
                request_id="source-fixture",
                work=tmp_path / str(index),
                freq="week",
                code="000001.SZ",
                listed={"000001.SZ"},
                aliases={},
                transport=lambda _, payload=payload: payload,
                policy=policy,
            )
        assert not list((tmp_path / str(index)).glob("*/complete.json"))


def test_current_response_excludes_delisted_and_rejects_retired_active_alias(tmp_path):
    def envelope(code):
        return json.dumps(
            {
                "code": 0,
                "data": {
                    "fields": list(FIELDS),
                    "items": [
                        [code, "20261016", "20261015", "week"] + [1.25] * 17,
                        ["000001.SZ", "20261016", "20261015", "week"] + [1.25] * 17,
                    ],
                },
            }
        ).encode()

    result = capture_unit(
        request_id="source-fixture",
        work=tmp_path / "a",
        freq="week",
        period="2026-10-16",
        listed={"000001.SZ"},
        aliases={},
        transport=lambda _: envelope("000002.SZ"),
    )
    assert result["rows"] == 1 and result["excluded_rows"] == 1
    with pytest.raises(ValueError, match="retired_alias"):
        capture_unit(
            request_id="source-fixture",
            work=tmp_path / "b",
            freq="week",
            period="2026-10-16",
            listed={"000001.SZ", "920000.BJ"},
            aliases={"832000.BJ": "920000.BJ"},
            transport=lambda _: envelope("832000.BJ"),
        )


def test_process_http_oversize_retains_bounded_prefix(tmp_path, http_server):
    from pathlib import Path

    from orchestrator.defs.stock_period_source import HttpPage

    url, _ = http_server
    policy = StockPeriodPolicy(response_bytes=64, retries=0)
    client = HttpPage(token="offline", base_url=url, policy=policy)
    with pytest.raises(ValueError, match="response_budget"):
        capture_unit(
            work=tmp_path,
            request_id="http-oversize",
            freq="week",
            code="000001.SZ",
            listed={"000001.SZ"},
            aliases={},
            policy=policy,
            transport=client,
        )
    failure = json.loads(next(tmp_path.glob("*/attempts/*.failure.json")).read_text())
    assert failure["truncated"] is True
    assert Path(failure["body"]).read_bytes() == body(["20261016"])[:64]
    assert not list(tmp_path.glob("*/complete.json"))
