"""HC01-12/18-19: literal sources and owned test processes; no real market I/O.

Source fixtures follow DailyWaveQuery's six/three projections and the real
DATE/Float/bool contract, not the consumer's guesses. Synthetic open days are
explicitly artificial and never evidence about the historical SSE calendar.
"""
import ast
from copy import deepcopy
from datetime import date, timedelta
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from scripts.research.index_market.xxm import r4_history_comparison as m


def frame(value):
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    return len(raw).to_bytes(8, "big") + raw


def request(**changes):
    result = {"kind": "REQUEST", "protocolVersion": 1, "bundle": "CURRENT",
              "commit": "c6a845fe3e8f13258b3c12f3ecfa843bce544f85", "tsCode": "000001.SH", "period": "day",
              "inputIdentity": "literal", "inputCount": 1, "rows": [["2023-01-03", 100.0, -0.0, -0.0, 0.0, True]],
              "startDate": "2023-01-03", "endDate": "2026-10-27", "modules": [],
              "workDeadline": time.monotonic() + 10, "maxWorkerMemoryBytes": 128 * 1024 * 1024,
              "maxResultBytes": 1024 * 1024}
    result.update(changes)
    return result


def message(kind, *, pid=123, **fields):
    return {"kind": kind, "protocolVersion": 1, "bundle": "CURRENT",
            "commit": "c6a845fe3e8f13258b3c12f3ecfa843bce544f85", "pid": pid, **fields}


@pytest.mark.parametrize("changes", [{"total_seconds": 30.0}, {"input_count": True},
                                      {"max_memory_bytes": 1}, {"old_commit": "HEAD"}])
def test_hc01_fixed_spec_has_no_parameter_override(changes):
    with pytest.raises(ValueError):
        m.HistoryComparisonSpec(**changes)
    assert m.SPEC.total_seconds == 20.0 and m.SPEC.input_count == 922


def synthetic_source():
    start, end = date(2023, 1, 3), date(2026, 10, 27)
    dates = [start + timedelta(days=i) for i in range(921)] + [end]
    opened = set(dates)
    rows = [{"ts_code": "000001.SH", "trade_date": day, "close": 100.123456789,
             "macd_dif_bfq": -0.0, "macd_dea_bfq": -0.0, "macd_bfq": 0.0} for day in dates]
    calendar = [{"exchange": "SSE", "trade_date": start + timedelta(days=i),
                 "is_open": start + timedelta(days=i) in opened} for i in range(1394)]
    assert calendar[-1]["trade_date"] == end
    return rows, calendar


def install_source(monkeypatch, rows, calendar):
    from src.app.dependencies import daily_wave
    events, calls = [], []

    class Session:
        def __init__(self, *, budget):
            assert budget.spec.max_main_points == 1000
            assert budget.spec.max_context_points == 0
            assert budget.spec.connection_seconds == 2
            assert budget.spec.query_seconds == 3
            assert budget.spec.lock_seconds == 1
            assert budget.spec.cleanup_seconds == .5
            self.budget = budget

        async def __aenter__(self):
            events.append("enter")
            return self

        async def execute_read(self, statement, parameters=None):
            columns = tuple(statement.selected_columns.keys())
            calls.append((columns, str(statement), statement.compile().params))
            if columns == ("ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq"):
                return rows
            assert columns == ("exchange", "trade_date", "is_open")
            return calendar

        async def __aexit__(self, *error):
            events.append("closed")
            return False

    monkeypatch.setattr(daily_wave, "DailyWaveReadSession", Session)
    return events, calls


def test_hc02_03_real_producer_projection_literal_rows_preserve_float(monkeypatch):
    rows, calendar = synthetic_source()
    events, calls = install_source(monkeypatch, rows, calendar)
    result = m.read_input(m.ResearchBudget())
    assert events == ["enter", "closed"]
    assert len(calls) == 2
    assert 1001 in calls[0][2].values() and 2001 in calls[1][2].values()
    assert result["rows"][0] == ("2023-01-03", 100.123456789, -0.0, -0.0, 0.0, True)
    assert all(type(v) is float for v in result["rows"][0][1:5])
    assert result["calendarCount"] == 1394 and result["openCount"] == 922
    assert result["rows"][-1][0] == "2026-10-27"
    assert result["sourceDescription"]["sourceTypes"] == "DATE/Float(53)/bool"
    assert m.SPEC.max_input_bars == 1000
    from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC
    assert DEFAULT_SPEC.max_main_points == 800 and DEFAULT_SPEC.requested_start == "2023-10-24"


@pytest.mark.parametrize("bad", ["short", "overflow", "duplicate", "reverse", "date_text", "int_float",
                                 "nan", "extra_field", "wrong_object", "h_relation", "calendar_missing",
                                 "calendar_bool", "calendar_open", "wrong_start", "wrong_end"])
def test_hc03_bad_source_rejected_and_session_closed(monkeypatch, bad):
    rows, calendar = synthetic_source()
    if bad == "short": rows.pop(5)
    elif bad == "overflow": rows.extend(deepcopy(rows[:79]))
    elif bad == "duplicate": rows[5]["trade_date"] = rows[4]["trade_date"]
    elif bad == "reverse": rows[5], rows[6] = rows[6], rows[5]
    elif bad == "date_text": rows[5]["trade_date"] = "2023-01-08"
    elif bad == "int_float": rows[5]["close"] = 100
    elif bad == "nan": rows[5]["macd_dif_bfq"] = float("nan")
    elif bad == "extra_field": rows[5]["extra"] = 1
    elif bad == "wrong_object": rows[5]["ts_code"] = "399001.SZ"
    elif bad == "h_relation": rows[5]["macd_bfq"] = 0.003
    elif bad == "calendar_missing": calendar.pop(3)
    elif bad == "calendar_bool": calendar[3]["is_open"] = 1
    elif bad == "calendar_open": calendar[1000]["is_open"] = True
    elif bad == "wrong_start": rows[0]["trade_date"] += timedelta(days=1)
    else: rows[-1]["trade_date"] -= timedelta(days=1)
    events, _ = install_source(monkeypatch, rows, calendar)
    with pytest.raises((ValueError, RuntimeError)):
        m.read_input(m.ResearchBudget())
    assert events == ["enter", "closed"]


def test_hc03_read_bridge_shares_outer_deadline_and_no_extra_source(monkeypatch):
    from src.biz.services.wealth.market.index_detail_daily_wave import budget as daily_budget
    rows, calendar = synthetic_source()
    events, _ = install_source(monkeypatch, rows, calendar)
    outer = m.ResearchBudget()
    calls = []
    original = daily_budget.DailyWaveBudget

    def capture(*args, **kw):
        calls.append(kw)
        assert kw["deadline"] <= outer.work_deadline
        assert kw["check_cancelled"]() is False
        return original(*args, **kw)

    monkeypatch.setattr(daily_budget, "DailyWaveBudget", capture)
    m.read_input(outer)
    assert len(calls) == 1 and events[-1] == "closed"


def blob(value):
    return b"a" * 40 + b" blob " + str(len(value)).encode() + b"\n" + value + b"\n"


@pytest.mark.parametrize("body", [b"", b"missing missing\n", b"a tree 3\nabc\n", blob(b"abc")[:-1],
                                  blob(b"abc") + b"extra", blob(b"\xff"), b"a blob 999999999\n"])
def test_hc01_06_bad_git_blobs_rejected(body):
    with pytest.raises((ValueError, OverflowError)):
        m._parse_git_blobs(body, (("fixed.module", "fixed/module.py"),))


def test_hc01_literal_blob_parser_not_a_source_sha_check():
    parsed = m._parse_git_blobs(blob(b"# literal\n"), (("fixed.module", "fixed/module.py"),))
    assert parsed == ({"name": "fixed.module", "path": "fixed/module.py", "source": "# literal\n"},)


def test_hc01_19_fixed_git_source_read_to_ram_only():
    budget = m.ResearchBudget()
    facts = m._preflight_git(budget)
    sources = m.read_git_sources(budget)
    assert facts["branch"] == "dev-interface"
    assert len(sources["OLD_PAIR"]) == 8 and len(sources["CURRENT"]) == 4
    assert sources["OLD_PAIR"][0]["path"].endswith("/types.py")
    assert 'algorithm_version: str = "xxm-direction-v0.2-r4"' in sources["CURRENT"][1]["source"]
    # LLD§3 explicitly permits git config exit 1 with empty output (unset).
    assert budget.active is None and all(p.returncode in (0, 1) for p in budget.processes)
    assert budget.processes[-1].returncode == 0


def test_hc01_optional_unset_git_and_false_promisor_are_normal(monkeypatch):
    calls = []

    def fake_git(args, budget, **kwargs):
        calls.append(args)
        if args[:2] == ["branch", "--show-current"]: return b"dev-interface\n"
        if args[:2] == ["config", "--get-regexp"]: return b"remote.origin.promisor false\n"
        if args[:2] == ["rev-parse", "--git-path"]: return b".git/info/grafts\n"
        return b""

    monkeypatch.setattr(m, "_git", fake_git)
    assert m._preflight_git(m.ResearchBudget())["branch"] == "dev-interface"
    assert len(calls) == 7


@pytest.mark.parametrize("failure", ["branch", "core", "partial", "promisor", "replace"])
def test_hc01_unsafe_git_refuses_without_restoring_anything(monkeypatch, failure):
    def fake_git(args, budget, **kwargs):
        if args[0] == "branch": return b"other\n" if failure == "branch" else b"dev-interface\n"
        if args[:2] == ["diff", "--name-only"]: return b"calculator.py\n" if failure == "core" else b""
        if args[:2] == ["config", "--get"]: return b"origin\n" if failure == "partial" else b""
        if args[:2] == ["config", "--get-regexp"]: return b"remote.origin.promisor true\n" if failure == "promisor" else b""
        if args[0] == "for-each-ref": return b"refs/replace/x\n" if failure == "replace" else b""
        if args[:2] == ["rev-parse", "--git-path"]: return b".git/info/grafts\n"
        return b""
    monkeypatch.setattr(m, "_git", fake_git)
    with pytest.raises(ValueError):
        m._preflight_git(m.ResearchBudget())


def parser(monkeypatch=None, *, parent=20, children=0):
    if monkeypatch is not None:
        monkeypatch.setattr(m.resource, "getrusage", lambda who: SimpleNamespace(
            ru_maxrss=(parent if who == m.resource.RUSAGE_SELF else children) * 1024 * 1024))
    budget = m.ResearchBudget()
    return m._WorkerFrames(SimpleNamespace(pid=123), request(), budget), budget


def test_hc05_normal_split_frame_and_resource_order(monkeypatch):
    p, _ = parser(monkeypatch)
    messages = [message("HELLO", peakMemoryBytes=10), message("RESULT", payload={"x": "a" * 100_000}),
                message("RESOURCE", phase="CURRENT", peakMemoryBytes=11),
                message("DONE", peakMemoryBytes=12, processedCounts={"current": 1})]
    raw = b"".join(frame(msg) for msg in messages)
    for i in range(0, len(raw), 17):
        p.feed(raw[i:i + 17])
    p.finish()
    assert p.payload["x"] == "a" * 100_000 and p.last_peak == 12
    with pytest.raises(ValueError):
        p.feed(frame(message("RESOURCE", phase="CURRENT", peakMemoryBytes=13)))


@pytest.mark.parametrize("bad", [message("HELLO", peakMemoryBytes=True), message("HELLO", pid=999, peakMemoryBytes=1),
                                 message("HELLO", peakMemoryBytes=-1), message("HELLO", peakMemoryBytes=1, extra=0),
                                 message("RESULT", payload={}), message("UNKNOWN"),
                                 message("DONE", peakMemoryBytes=1, processedCounts={"current": 1})])
def test_hc05_bad_message_rejected(monkeypatch, bad):
    p, _ = parser(monkeypatch)
    with pytest.raises(ValueError): p.feed(frame(bad))


def test_hc05_duplicate_partial_or_single_result_never_succeeds(monkeypatch):
    p, _ = parser(monkeypatch)
    p.feed(frame(message("HELLO", peakMemoryBytes=1)))
    p.feed(frame(message("RESULT", payload={})))
    with pytest.raises(ValueError): p.finish()
    with pytest.raises(ValueError): p.feed(frame(message("RESULT", payload={})))
    p, _ = parser(monkeypatch)
    p.feed(frame(message("HELLO", peakMemoryBytes=1))[:-2])
    with pytest.raises(ValueError): p.finish()
    p, _ = parser(monkeypatch)
    with pytest.raises(OverflowError): p.feed((2 * 1024 * 1024).to_bytes(8, "big"))


def test_hc07_serial_children_take_highest_with_parent_peak(monkeypatch):
    p, budget = parser(monkeypatch, parent=90)
    p.feed(frame(message("HELLO", peakMemoryBytes=80 * 1024 * 1024)))
    assert budget.measure() == 170 * 1024 * 1024
    budget.reported_peak = 90 * 1024 * 1024
    assert budget.measure() == 180 * 1024 * 1024
    p, _ = parser(monkeypatch, parent=150)
    with pytest.raises(MemoryError):
        p.feed(frame(message("HELLO", peakMemoryBytes=120 * 1024 * 1024)))


def test_hc08_waited_peak_including_git_can_reject_final_result(monkeypatch):
    _, budget = parser(monkeypatch, parent=150)
    proc = SimpleNamespace(returncode=0)
    budget.register(proc, git=True)
    monkeypatch.setattr(m.resource, "getrusage", lambda who: SimpleNamespace(
        ru_maxrss=(150 if who == m.resource.RUSAGE_SELF else 120) * 1024 * 1024))
    with pytest.raises(MemoryError): budget.collected(proc)
    assert budget.active is None


def peer(source, budget):
    proc = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", source],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=0, close_fds=True, shell=False, env={})
    budget.register(proc)
    return proc


def peer_code(extra="", *, padding=0, hang=False):
    # Independent literal peer: it deliberately sends HELLO before consuming
    # input to test the parent's concurrent I/O, never the real worker order.
    return f'''
import sys, os, json, time
def send(kind, **fields):
    msg={{"kind":kind,"protocolVersion":1,"bundle":"CURRENT","commit":"c6a845fe3e8f13258b3c12f3ecfa843bce544f85","pid":os.getpid(),**fields}}
    raw=json.dumps(msg,separators=(",",":")).encode()
    sys.stdout.buffer.write(len(raw).to_bytes(8,"big")+raw);sys.stdout.buffer.flush()
send("HELLO",peakMemoryBytes=1)
{extra}
send("RESULT",payload={{"literal":"x"*{padding}}})
sys.stdin.buffer.read()
send("DONE",peakMemoryBytes=1,processedCounts={{"current":1}})
{"time.sleep(10)" if hang else ""}
'''


def test_hc04_large_bidirectional_pipe_is_drained_before_wait():
    budget = m.ResearchBudget()
    proc = peer(peer_code(padding=200_000), budget)
    encoded = frame(request(padding="x" * 200_000))
    result = m._pump_process(proc, encoded, protocol="WORKER", budget=budget)
    assert result["payload"] == {"literal": "x" * 200_000}
    assert budget.active is None and proc.returncode == 0
    assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed


@pytest.mark.parametrize("scenario", ["stderr", "exit1", "partial", "hang_after_done", "cancel_always", "timeout"])
def test_hc06_10_11_failures_reap_owned_process(scenario):
    budget = m.ResearchBudget()
    if scenario == "stderr": code = "import sys;sys.stderr.write('secret credential');sys.stderr.flush()"
    elif scenario == "exit1": code = "raise SystemExit(1)"
    elif scenario == "partial": code = "import sys;sys.stdout.buffer.write((50).to_bytes(8,'big')+b'{');sys.stdout.buffer.flush()"
    elif scenario in {"hang_after_done", "cancel_always"}: code = peer_code(hang=True)
    else: code = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(10)"
    proc = peer(code, budget)
    calls = []
    if scenario == "cancel_always":
        def cancelled():
            calls.append(1)
            raise LookupError("literal cancellation")
        budget.check_cancelled = cancelled
    if scenario in {"hang_after_done", "timeout"}:
        budget.work_deadline = budget.process_deadline = time.monotonic() + .12
    with pytest.raises((ValueError, RuntimeError, TimeoutError, LookupError)) as caught:
        m._pump_process(proc, frame(request()), protocol="WORKER", budget=budget)
    assert "secret credential" not in str(caught.value)
    assert proc.returncode is not None and budget.active is None
    assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed
    if scenario == "cancel_always": assert calls == [1]


def test_hc11_zero_cleanup_time_uses_kill_and_never_calls_cancel():
    budget = m.ResearchBudget()
    proc = peer("import time;time.sleep(10)", budget)
    budget.deadline = time.monotonic() - .001
    budget.check_cancelled = lambda: (_ for _ in ()).throw(AssertionError("no repeated cancel"))
    original = LookupError("first error")
    m._cleanup_process(proc, budget, original)
    assert proc.returncode is not None and budget.active is None
    assert original.__notes__ and "CLEANUP" in original.__notes__[0]


def test_hc12_control_aggregate_and_result_limit(monkeypatch):
    p, _ = parser(monkeypatch)
    p.feed(frame(message("HELLO", peakMemoryBytes=1)))
    p.controls = 1024
    with pytest.raises(OverflowError):
        p.feed(frame(message("RESOURCE", phase="CURRENT", peakMemoryBytes=1)))


def minimal_finish_args():
    source = {"rows": (("2023-01-03", 100., 0., 0., 0., True),), "actualStart": "2023-01-03",
              "actualEnd": "2023-01-03", "calendarCount": 1, "openCount": 1, "sourceDescription": {}}
    return source, {"metadata": {}}, {"identity": {}}, {"passed": True, "checks": []}, {
        "summary": {}, "differenceDays": []}


def test_hc10_12_final_encoding_checked_before_return(monkeypatch):
    from scripts.research.index_market.xxm import r4_history_records
    monkeypatch.setattr(r4_history_records, "format_report", lambda result, *, check: "literal report")
    budget = m.ResearchBudget()
    budget.result_sizes = [m.SPEC.max_result_bytes - 10]
    with pytest.raises(OverflowError): m._finish_result(*minimal_finish_args(), budget)
    budget = m.ResearchBudget()
    encode = m._encoded

    def expired(value):
        raw = encode(value)
        budget.work_deadline = time.monotonic() - 1
        return raw

    monkeypatch.setattr(m, "_encoded", expired)
    with pytest.raises(TimeoutError): m._finish_result(*minimal_finish_args(), budget)


def test_hc10_final_success_has_exact_checked_bytes(monkeypatch):
    from scripts.research.index_market.xxm import r4_history_records
    monkeypatch.setattr(r4_history_records, "format_report", lambda result, *, check: "literal report")
    result = m._finish_result(*minimal_finish_args(), m.ResearchBudget())
    assert len(m._encoded(result)) == result["metrics"]["finalResultBytes"]
    assert result["metrics"]["allChildrenReaped"] is True


def test_hc19_dependency_and_real_entry_are_separate():
    worker = Path(m.__file__).with_name("r4_history_worker.py")
    for node in ast.walk(ast.parse(worker.read_text())):
        if isinstance(node, ast.Import):
            assert all(part.name.split(".")[0] in sys.stdlib_module_names for part in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module.split(".")[0] in sys.stdlib_module_names
    text = Path(m.__file__).read_text()
    assert "if __name__" not in text  # No hidden CLI or automatic real execution.
    assert "build_review(" not in text and "get_settings(" not in text
    assert "shell=False" in text and 'env=environment' in text
    assert not any(p.name.startswith("r4_history") for p in m.REPO_ROOT.glob("*.json"))


def test_hc18_fresh_parent_922_synthetic_full_path_without_real_entry():
    # Run in a new parent so pytest's accumulated peaks are not called a real
    # combined-memory measurement. No market or calendar query is performed.
    code = f'''
import sys,json
sys.path.insert(0,{str(m.REPO_ROOT)!r})
from datetime import date,timedelta
from scripts.research.index_market.xxm import r4_history_comparison as m
from scripts.research.index_market.xxm.r4_history_records import compare_fact_groups
m.run_historical_comparison=lambda **kw: (_ for _ in ()).throw(AssertionError("REAL ENTRY FORBIDDEN"))
b=m.ResearchBudget()
sources=m.read_git_sources(b)
rows=tuple(((date(2023,1,3)+timedelta(days=i)).isoformat(),100.0,0.0,0.0,0.0,True) for i in range(922))
old=m.run_worker("OLD_PAIR",rows,sources["OLD_PAIR"],b)
current=m.run_worker("CURRENT",rows,sources["CURRENT"],b)
compared=compare_fact_groups(old,current,input_rows=rows,check=b.check)
source={{"rows":rows,"actualStart":rows[0][0],"actualEnd":rows[-1][0],"calendarCount":1394,"openCount":922,"sourceDescription":{{"synthetic":True}}}}
result=m._finish_result(source,old,current,{{"passed":False,"checks":[],"note":"synthetic, real baseline not executed"}},compared,b)
assert result["metrics"]["stepCounts"] == {{"r2":922,"historyR4":922,"currentR4":922}}
assert result["metrics"]["elapsedSeconds"] < 20
assert result["metrics"]["combinedPeakUpper"] <= 256*1024*1024
assert sum(result["metrics"]["workerResultBytes"])+result["metrics"]["finalResultBytes"] <= 16*1024*1024
assert all(p.returncode == 0 for p in b.processes) and b.active is None
print(json.dumps(result["metrics"]))
'''
    environment = {name: os.environ[name] for name in ("HOME", "TMPDIR", "PATH") if name in os.environ}
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, timeout=25, env=environment)
    assert proc.returncode == 0, proc.stderr.decode()
    metrics = json.loads(proc.stdout)
    assert metrics["allChildrenReaped"] and metrics["stepCounts"]["currentR4"] == 922
    print("HC18_SYNTHETIC_METRICS", proc.stdout.decode().strip())


def test_hc11_close_error_still_reaps_and_preserves_original():
    events = []
    class Pipe:
        def __init__(self, name): self.name, self.closed = name, False
        def close(self):
            events.append(self.name)
            if self.name == "stdin": raise OSError("close failure")
            self.closed = True
    class Process:
        returncode = None
        stdin, stdout, stderr = Pipe("stdin"), Pipe("stdout"), Pipe("stderr")
        def poll(self): return self.returncode
        def terminate(self): events.append("terminate")
        def kill(self): events.append("kill"); self.returncode = -9
        def wait(self, timeout):
            events.append("wait")
            if self.returncode is None: raise subprocess.TimeoutExpired("literal", timeout)
            return self.returncode
    budget, proc = m.ResearchBudget(), Process()
    budget.register(proc)
    original = LookupError("first cancellation")
    m._cleanup_process(proc, budget, original)
    assert "kill" in events and "wait" in events
    assert proc.stdout.closed and proc.stderr.closed and budget.active is None
    assert original.__notes__ and "OSError" in original.__notes__[0]


def test_hc11_bad_owned_request_is_also_cleaned():
    budget = m.ResearchBudget()
    proc = peer("import time;time.sleep(10)", budget)
    try:
        with pytest.raises(ValueError):
            m._pump_process(proc, b"short", protocol="WORKER", budget=budget)
        assert budget.active is None and proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=1)
        for pipe in (proc.stdin, proc.stdout, proc.stderr): pipe.close()


def test_hc01_partial_refused_before_object_diff_or_cat_file(monkeypatch):
    calls = []
    def unsafe(args, budget, **kw):
        calls.append(args)
        if args[:2] == ["config", "--get"]: return b"origin\n"
        if args[0] == "branch": return b"dev-interface\n"
        return b""
    monkeypatch.setattr(m, "_git", unsafe)
    with pytest.raises(ValueError): m._preflight_git(m.ResearchBudget())
    assert not any(args[0] in {"diff", "cat-file"} for args in calls)


def test_hc19_git_environment_is_minimal_worker_environment_empty(monkeypatch):
    calls = []
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("DB_PASSWORD", "artificial-secret")
    monkeypatch.setattr(m.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace())
    m._spawn(["/usr/bin/git", "--version"], m.ResearchBudget(), git=True)
    m._spawn([sys.executable, "-I", "-S", "-B", "fixed-worker"], m.ResearchBudget())
    assert set(calls[0][1]["env"]) <= {"HOME", "TMPDIR", "PATH"}
    assert calls[1][1]["env"] == {}


def test_hc01_identity_rejects_bool_count_even_for_one_literal_bar():
    req = request()
    identity = {k: req[k] for k in ("bundle", "commit", "tsCode", "period", "inputIdentity", "inputCount")}
    identity.update(requestedStartDate="2023-01-03", requestedEndDate="2026-10-27",
                    algorithmVersion="xxm-direction-v0.2-r4")
    # A literal identity fixture, independent of the product Spec constructor.
    identity["spec"] = {"algorithm_version": "xxm-direction-v0.2-r4", "dif_turn_pct": 1.0,
                        "max_refs": 2, "min_bars": 2, "reference_policy": "nearest_then_farther_two",
                        "active_reference_policy": "same_bar_near_to_far_on_dull_break",
                        "zero_policy": "neutral_real_opposite", "allow_zero_activation": True,
                        "activation_policy": "current_close_and_current_dif",
                        "reference_break_policy": "strict_break_within_current_segment",
                        "structure_return_policy": "adjacent_one_percent_to_dull",
                        "structure_lock_policy": "first_valid_opposite_color", "historical_min_bars": 1,
                        "top_activation_requires_positive_dif": True, "macd_parameters": [12, 26, 9],
                        "histogram_multiplier": 2, "color_flip": True, "flip_requires_turn": False}
    identity["specHash"] = hashlib.sha256(json.dumps(identity["spec"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {"identity": identity, "rows": [{}]}
    m._check_identity(payload, req)
    identity["inputCount"] = True
    with pytest.raises(ValueError): m._check_identity(payload, req)
    identity["inputCount"] = 1
    identity["specHash"] = "a" * 64
    with pytest.raises(ValueError): m._check_identity(payload, req)
    del identity["spec"]
    with pytest.raises(ValueError): m._check_identity(payload, req)


def test_hc05_nontext_message_kind_is_a_protocol_error(monkeypatch):
    p, _ = parser(monkeypatch)
    with pytest.raises(ValueError): p.feed(frame(message([])))
