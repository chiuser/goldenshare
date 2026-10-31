"""HC01/02/05/06/09/19: literal expectations and real fixed-source workers.

Source modules come from the two commits named by the approved LLD. Bars and
expected events below are hand written; no market reader or product import.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from scripts.research.index_market.xxm import r4_history_worker as worker


ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / "scripts/research/index_market/xxm/r4_history_worker.py"
PYTHON = Path(sys.executable).resolve()


@pytest.fixture(scope="module")
def sources():
    # Fixed Git objects are the real producer, not a fixture inferred from the
    # consumer. Only source text is read; no algorithms are written to disk.
    entries = [(worker.OLD_COMMIT, *item) for item in worker.PRODUCT_MODULES + worker.RESEARCH_MODULES]
    entries += [(worker.CURRENT_COMMIT, *item) for item in worker.PRODUCT_MODULES]
    requested = "".join(f"{commit}:{path}\n" for commit, name, path in entries).encode()
    raw = subprocess.run(["/usr/bin/git", "cat-file", "--batch"], input=requested,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
                         timeout=2, check=True).stdout
    offset, result = 0, {"OLD_PAIR": [], "CURRENT": []}
    for index, (commit, name, path) in enumerate(entries):
        newline = raw.index(b"\n", offset)
        _oid, kind, size_text = raw[offset:newline].split()
        assert kind == b"blob"
        size = int(size_text)
        source = raw[newline + 1:newline + 1 + size].decode("utf-8")
        assert raw[newline + 1 + size:newline + 2 + size] == b"\n"
        result["OLD_PAIR" if index < 8 else "CURRENT"].append(dict(name=name, path=path, source=source))
        offset = newline + 2 + size
    assert offset == len(raw) and len(result["OLD_PAIR"]) == 8 and len(result["CURRENT"]) == 4
    return result


def literal_rows():
    # Day 6: price 112>110 and DIF10<12, second red -> top dull.
    # Day 7: DIF10->9 falls 10% -> structure; day 8 is first green.
    values = [(100., 10., 9., 2.), (110., 12., 11., 2.),
              (105., 9., 10., -2.), (106., 8., 9., -2.),
              (111., 9., 8., 2.), (112., 10., 9., 2.),
              (111., 9., 8., 2.), (110., 8., 9., -2.)]
    return [[(date(2023, 1, 3) + timedelta(days=index)).isoformat(), *numbers, True]
            for index, numbers in enumerate(values)]


def request(sources, bundle="CURRENT", rows=None):
    rows = literal_rows() if rows is None else rows
    return dict(kind="REQUEST", protocolVersion=1, bundle=bundle,
                commit=worker.OLD_COMMIT if bundle == "OLD_PAIR" else worker.CURRENT_COMMIT,
                tsCode="000001.SH", period="day", startDate=rows[0][0], endDate=rows[-1][0],
                inputIdentity="manual-independent-bars", inputCount=len(rows), rows=rows,
                modules=deepcopy(sources[bundle]), workDeadline=time.monotonic() + 5,
                maxWorkerMemoryBytes=128 * 1024 * 1024, maxResultBytes=16 * 1024 * 1024)


def independent_frame(value):
    body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return len(body).to_bytes(8, "big") + body


def test_hc01_authorized_one_gib_request_and_over_limit_rejection(sources):
    value = request(sources)
    value["maxWorkerMemoryBytes"] = 1024 * 1024 * 1024
    assert worker.MAX_MEMORY_BYTES == 1024 * 1024 * 1024
    assert worker.validate_request(value) is value
    for invalid in (1024 * 1024 * 1024 + 1, True):
        value["maxWorkerMemoryBytes"] = invalid
        with pytest.raises(ValueError, match="memory allowance"):
            worker.validate_request(value)


def test_hc01_authorized_one_hundred_mib_result_and_over_limit_rejection(sources):
    value = request(sources)
    value["maxResultBytes"] = 104_857_600
    assert worker.MAX_RESULT_BYTES == 104_857_600
    assert worker.validate_request(value) is value
    for invalid in (104_857_601, True):
        value["maxResultBytes"] = invalid
        with pytest.raises(ValueError, match="result allowance"):
            worker.validate_request(value)


def independent_messages(raw):
    output, offset = [], 0
    while offset < len(raw):
        assert len(raw) - offset >= 8
        size = int.from_bytes(raw[offset:offset + 8], "big")
        body = raw[offset + 8:offset + 8 + size]
        assert len(body) == size and 0 < size <= 16 * 1024 * 1024
        output.append(json.loads(body))
        offset += size + 8
    return output


def run_request(value, *, raw=None, guarded=False, without_memory_observer=False):
    command = [str(PYTHON), "-I", "-S", "-B", str(WORKER)]
    if guarded or without_memory_observer:
        # Load only the new entry before installing the probe. The actual
        # calculation then cannot open repo files, write, or use network/DB.
        code = """
import importlib.util, os, sys, sysconfig
from contextlib import contextmanager
entry, root, guarded, without_memory_observer = sys.argv[1:]
spec = importlib.util.spec_from_file_location('bounded_worker', entry)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
stdlib_roots = tuple(os.path.realpath(sysconfig.get_path(key)) + os.sep
                     for key in ('stdlib', 'platstdlib'))
if without_memory_observer == '1':
    @contextmanager
    def observe_disabled(comparison, runtime):
        yield
    module._observe_old_memory = observe_disabled
class BusinessReadDenied(AssertionError): pass
class BusinessWriteDenied(AssertionError): pass
class NetworkDenied(AssertionError): pass
class ChildProcessDenied(AssertionError): pass
class DatabaseDenied(AssertionError): pass
def audit(event, arguments):
    if event == 'open':
        path, mode, flags = arguments
        if (isinstance(mode, str) and any(x in mode for x in 'wax+')
                or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise BusinessWriteDenied('File writes are forbidden')
        if isinstance(path, (str, bytes)):
            resolved = os.path.realpath(os.fsdecode(path))
            # Only Python's own module-loading reads remain permitted. This
            # excludes site packages, repository files and external business
            # paths such as /private/tmp/market.csv, even when outside root.
            standard_code = (any(resolved.startswith(prefix) for prefix in stdlib_roots)
                             and '/site-packages/' not in resolved and '/dist-packages/' not in resolved
                             and resolved.endswith(('.py', '.pyc', '.so')))
            if not standard_code:
                raise BusinessReadDenied('Business file reads are forbidden')
        elif not isinstance(path, int) or path not in (0, 1, 2):
            raise BusinessReadDenied('Business file descriptors are forbidden')
    if event.startswith('socket.'):
        raise NetworkDenied('Network is forbidden')
    if event.startswith('subprocess.'):
        raise ChildProcessDenied('Child processes are forbidden')
    if event.startswith('sqlite3.connect'):
        raise DatabaseDenied('Databases are forbidden')
if guarded == '1':
    sys.addaudithook(audit)
sys.argv = [entry]
raise SystemExit(module.worker_main())
"""
        command = [str(PYTHON), "-I", "-S", "-B", "-c", code, str(WORKER), str(ROOT),
                   str(int(guarded)), str(int(without_memory_observer))]
    # Test-only communicate has an explicit input bound and a 6-second timeout;
    # production uses the parent's nonblocking pipe loop.
    packet = independent_frame(value) if raw is None else raw
    assert len(packet) <= worker.MAX_REQUEST_BYTES + 8
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env={}, close_fds=True, bufsize=0)
    try:
        output, error = process.communicate(packet, timeout=6)
    except BaseException:
        process.kill()
        process.wait(timeout=1)
        raise
    assert error == b""
    return process.returncode, independent_messages(output)


@pytest.mark.parametrize("bundle", ["OLD_PAIR", "CURRENT"])
def test_fixed_sources_literal_states_and_events(sources, bundle):
    value = request(sources, bundle)
    code, messages = run_request(value)
    assert code == 0
    assert messages[0]["kind"] == "HELLO" and messages[-1]["kind"] == "DONE"
    assert all(item["bundle"] == bundle and item["commit"] == value["commit"] for item in messages)
    assert len({item["pid"] for item in messages}) == 1
    assert [item["kind"] for item in messages].count("RESULT") == 1
    result = next(item["payload"] for item in messages if item["kind"] == "RESULT")
    if bundle == "CURRENT":
        assert result["rows"][6]["structures"][0]["status"] == "ASSESSING"
        groups = (result["rows"],)
        assert set(result) == {"identity", "rows"}
        assert result["identity"]["algorithmVersion"] == "xxm-direction-v0.2-r4"
    else:
        groups = ([row["r2"] for row in result["rows"]], [row["r4"] for row in result["rows"]])
        assert set(result) == {"metadata", "rows", "summary"}
        assert result["metadata"]["r2AlgorithmVersion"] == "xxm-direction-v0.1-r2"
        assert result["metadata"]["r4ResearchVersion"] == "xxm-research-r4-v2"
    for rows in groups:
        assert [(index, event["type"], event["direction"], event["route"])
                for index, row in enumerate(rows) for event in row["events"]] == [
                    (5, "DULL", "TOP", "activation"), (6, "STRUCTURE", "TOP", "dif_turn")]
        assert rows[5]["point"]["ordinaryState"] == "DULL"
        assert rows[6]["point"]["ordinaryState"] == "STRUCTURE"
        assert rows[5]["point"]["activeReference"]["price"] == 110.
        assert rows[5]["point"]["activeReference"]["dif"] == 12.
        for index, row in enumerate(rows):
            assert [row["point"][name] for name in ("time", "close", "dif", "dea", "hist")] == value["rows"][index][:5]
    if bundle == "CURRENT":
        assert result["rows"][7]["structures"][0]["status"] == "LOCKED"
        assert result["rows"][7]["structures"][0]["lockedAt"] == "2023-01-10"
        assert result["rows"][7]["point"]["ordinaryState"] == "NONE"


def test_signed_zero_float_roundtrip(sources):
    rows = [["2023-01-03", 100., -0.0, -0.0, -0.0, True]]
    code, messages = run_request(request(sources, rows=rows))
    assert code == 0
    point = next(item["payload"] for item in messages if item["kind"] == "RESULT")["rows"][0]["point"]
    assert math.copysign(1, point["dif"]) == -1
    assert type(point["close"]) is float


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(protocolVersion=True), lambda r: r.update(commit="other"),
    lambda r: r.update(inputCount=True), lambda r: r.update(inputCount=1001),
    lambda r: r.update(maxWorkerMemoryBytes=True), lambda r: r.update(maxResultBytes=True),
    lambda r: r.update(workDeadline=True), lambda r: r.update(extra=True),
    lambda r: r["rows"][0].__setitem__(1, True), lambda r: r["rows"][0].__setitem__(5, False),
    lambda r: r["rows"][1].__setitem__(0, r["rows"][0][0]),
    lambda r: r["modules"].pop(), lambda r: r["modules"][0].update(path="/tmp/other.py"),
])
def test_invalid_requests_are_rejected_before_hello(sources, mutate):
    value = request(sources)
    mutate(value)
    code, messages = run_request(value)
    assert code == 1 and messages == []


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'\xff'])
def test_json_errors_are_rejected(raw):
    with pytest.raises((ValueError, UnicodeDecodeError)):
        worker.strict_json_loads(raw)


@pytest.mark.parametrize("fault", ["short_header", "short_body", "extra", "too_large", "duplicate"])
def test_request_frames_are_bounded(sources, fault):
    value = request(sources)
    packet = independent_frame(value)
    if fault == "short_header": packet = packet[:4]
    elif fault == "short_body": packet = packet[:-1]
    elif fault == "extra": packet += b"x"
    elif fault == "too_large": packet = (worker.MAX_REQUEST_BYTES + 1).to_bytes(8, "big")
    else:
        raw = json.dumps(value).replace('"kind": "REQUEST"', '"kind":"REQUEST","kind":"REQUEST"').encode()
        packet = len(raw).to_bytes(8, "big") + raw
    code, messages = run_request(value, raw=packet)
    assert code == 1 and messages == []


def test_extra_business_module_never_falls_back_to_worktree(sources):
    value = request(sources)
    value["modules"][0]["source"] = "import src.app\n"
    code, messages = run_request(value)
    assert code == 1 and messages[0]["kind"] == "HELLO"
    assert messages[-1]["kind"] == "ERROR" and messages[-1]["errorKind"] == "MODULE"
    assert not any(item["kind"] in ("DONE", "RESULT") for item in messages)


def test_wrong_rule_version_fails_after_loading(sources):
    value = request(sources)
    module = value["modules"][1]
    module["source"] = module["source"].replace('"xxm-direction-v0.2-r4"', '"not-the-fixed-version"')
    code, messages = run_request(value)
    assert code == 1 and messages[-1]["kind"] == "ERROR"
    assert not any(item["kind"] in ("DONE", "RESULT") for item in messages)


def test_exception_text_and_source_are_not_sent(sources):
    value = request(sources)
    secret = "sample-private-connection-value"
    value["modules"][0]["source"] = f"raise RuntimeError({secret!r})"
    code, messages = run_request(value)
    assert code == 1
    assert messages[-1]["kind"] == "ERROR" and messages[-1]["exceptionType"] == "RuntimeError"
    assert secret not in json.dumps(messages)


def test_memory_observer_does_not_change_old_business_facts(sources):
    observed_code, observed = run_request(request(sources, "OLD_PAIR"))
    plain_code, plain = run_request(request(sources, "OLD_PAIR"), without_memory_observer=True)
    assert observed_code == plain_code == 0
    observed = next(item["payload"] for item in observed if item["kind"] == "RESULT")
    plain = next(item["payload"] for item in plain if item["kind"] == "RESULT")
    # This compares two executions only to prove the allowed observer is inert.
    # Recognition correctness is independently asserted by the literal test.
    assert observed["rows"] == plain["rows"] and observed["summary"] == plain["summary"]


@pytest.mark.parametrize("bundle", ["OLD_PAIR", "CURRENT"])
def test_calculation_has_no_business_io_or_child_processes(sources, bundle):
    code, messages = run_request(request(sources, bundle), guarded=True)
    assert code == 0 and messages[-1]["kind"] == "DONE"


@pytest.mark.parametrize("source,denial", [
    ("open('/private/tmp/market.csv', 'r')", "BusinessReadDenied"),
    ("import os\nos.open(b'/private/tmp/market.csv', os.O_RDONLY)", "BusinessReadDenied"),
    ("open('/private/tmp/r4-history-denied-write.txt', 'w')", "BusinessWriteDenied"),
    ("import socket\nsocket.socket()", "NetworkDenied"),
    ("import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'pass'])", "ChildProcessDenied"),
    ("import sqlite3\nsqlite3.connect(':memory:')", "DatabaseDenied"),
])
def test_guard_blocks_business_access_before_it_occurs(sources, source, denial):
    value = request(sources)
    value["modules"][0]["source"] = source
    code, messages = run_request(value, guarded=True)
    assert code == 1
    assert messages[-1]["kind"] == "ERROR"
    # A missing file/module or later calculator error is not proof of blocking.
    # A distinct AssertionError subclass proves the intended operation was
    # intercepted, rather than an unrelated standard-library import read.
    assert messages[-1]["exceptionType"] == denial
    assert not any(item["kind"] in ("RESULT", "DONE") for item in messages)


def test_old_resource_observer_restores_on_success_and_failure():
    sentinel = 123456789
    original = lambda: sentinel
    module = SimpleNamespace(_memory_bytes=original)
    observed = []
    runtime = SimpleNamespace(check=lambda: observed.append("check"))
    with worker._observe_old_memory(module, runtime):
        actual = module._memory_bytes()
        assert actual is sentinel and type(actual) is int
    assert module._memory_bytes is original and observed == ["check"]
    with pytest.raises(RuntimeError):
        with worker._observe_old_memory(module, runtime):
            raise RuntimeError("manual failure")
    assert module._memory_bytes is original


class _WritableSelector:
    def register(self, *args): pass
    def select(self, *args): return [(None, None)]
    def close(self): pass


@contextmanager
def captured_runtime(monkeypatch, sources):
    read_fd, write_fd = os.pipe()
    capture = bytearray()
    runtime = worker._Runtime(request(sources), write_fd)
    monkeypatch.setattr(worker.selectors, "DefaultSelector", _WritableSelector)
    def write(_fd, value):
        block = bytes(value[:4096])
        capture.extend(block)
        return len(block)
    monkeypatch.setattr(worker.os, "write", write)
    try:
        yield runtime, capture
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_resource_growth_cannot_insert_frames_into_result(monkeypatch, sources):
    peak = [1024 * 1024]
    def growing():
        peak[0] += 32768
        return peak[0]
    monkeypatch.setattr(worker, "_peak_memory_bytes", growing)
    with captured_runtime(monkeypatch, sources) as (runtime, capture):
        runtime.check()
        runtime.send("HELLO", peakMemoryBytes=runtime.peak)
        runtime.send("RESULT", payload={"literal": "x" * 150000})
        runtime.check(force=True)
        runtime.send("DONE", peakMemoryBytes=runtime.peak, processedCounts={"current": 8})
        messages = independent_messages(capture)
        assert [item["kind"] for item in messages] == ["HELLO", "RESULT", "RESOURCE", "DONE"]
        assert messages[1]["payload"] == {"literal": "x" * 150000}
        with pytest.raises(RuntimeError):
            runtime.send("RESOURCE", peakMemoryBytes=runtime.peak, phase="CURRENT")


def test_partial_frame_failure_does_not_append_error(monkeypatch, sources):
    monkeypatch.setattr(worker, "_peak_memory_bytes", lambda: 1024)
    with captured_runtime(monkeypatch, sources) as (runtime, capture):
        runtime.send("HELLO", peakMemoryBytes=1024)
        prefix = len(capture)
        original = runtime._sample
        def expire_after_header():
            original()
            if len(capture) > prefix:
                raise TimeoutError("manual mid-frame timeout")
        monkeypatch.setattr(runtime, "_sample", expire_after_header)
        with pytest.raises(TimeoutError):
            runtime.send("RESULT", payload={"literal": "x" * 150000})
        partial = bytes(capture)
        assert runtime.partial_frame is True
        runtime.error(TimeoutError("private input should not be reported"))
        assert bytes(capture) == partial
        assert len(capture) == prefix + 8


def test_import_only_uses_standard_library():
    import ast
    tree = ast.parse(WORKER.read_text())
    imports = [node.module if isinstance(node, ast.ImportFrom) else alias.name
               for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
               for alias in (node.names if isinstance(node, ast.Import) else [None])]
    assert all(name.split(".")[0] in sys.stdlib_module_names or name == "__future__" for name in imports)
