"""Concurrency, single-writer ownership and bounded batch loading acceptance."""

import json
import threading
import time
from contextlib import contextmanager
from itertools import pairwise
from types import SimpleNamespace

import pytest

from tests.test_stk_mins_gap_recovery import Provider, bars, plan, source
from tests.test_stk_mins_gap_recovery import root as isolated_root

root = isolated_root

from orchestrator.defs.bootstrap import stk_mins_gap_recovery as core
from orchestrator.defs.bootstrap import stk_mins_gap_recovery_source as source_module
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_fetch import load_source_batch
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import SourceCache


def three_windows(root):
    return plan(
        root, units=[(f"60000{i}.SH", "2014-01-02", [f"60000{i}.SH"]) for i in range(3)]
    )


def test_two_calls_overlap_all_persistence_on_owner_thread(root, monkeypatch):
    run = three_windows(root)
    batch = load_source_batch(run, 3)
    owner = threading.get_ident()
    checkpoint, db, atomic_json = run.checkpoint, run.db, core.atomic_json

    def owner_checkpoint(*args, **kwargs):
        assert threading.get_ident() == owner
        return checkpoint(*args, **kwargs)

    @contextmanager
    def owner_db(*args, **kwargs):
        assert threading.get_ident() == owner
        with db(*args, **kwargs) as connection:
            yield connection

    def owner_json(*args, **kwargs):
        assert threading.get_ident() == owner
        return atomic_json(*args, **kwargs)

    monkeypatch.setattr(run, "checkpoint", owner_checkpoint)
    monkeypatch.setattr(run, "db", owner_db)
    monkeypatch.setattr(core, "atomic_json", owner_json)
    monkeypatch.setattr(source_module, "atomic_json", owner_json)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    activity = {"active": 0, "peak": 0, "count": 0}

    class ConcurrentProvider:
        def call(self, api, params, fields):
            assert threading.get_ident() != owner
            with lock:
                activity["active"] += 1
                activity["count"] += 1
                index = activity["count"]
                activity["peak"] = max(activity["peak"], activity["active"])
            if index <= 2:
                barrier.wait(timeout=5)
            with lock:
                activity["active"] -= 1
            return SimpleNamespace(rows=bars(params["ts_code"]), columns=core.COLUMNS)

    completed = source(run, ConcurrentProvider()).resolve_batch(batch)
    assert activity == {"active": 0, "peak": 2, "count": 3}
    assert len(completed) == 3 and all(s["ready"] == 1 for s in completed)
    assert load_source_batch(run, 3) == []
    replay = Provider([])
    source(run, replay).resolve_batch(batch)
    assert replay.calls == []


def test_cancel_drains_both_pages_and_resume_only_fetches_third(root):
    run = three_windows(root)
    batch = load_source_batch(run, 3)
    cancelled = threading.Event()
    barrier = threading.Barrier(2)
    calls = []

    class CancellingProvider:
        def call(self, api, params, fields):
            calls.append(params["ts_code"])
            barrier.wait(timeout=5)
            cancelled.set()
            return SimpleNamespace(rows=bars(params["ts_code"]), columns=core.COLUMNS)

    with pytest.raises(InterruptedError):
        source(run, CancellingProvider(), cancelled=cancelled.is_set).resolve_batch(
            batch
        )
    assert len(calls) == 2
    assert len(list((run.root / "pages").glob("*.json"))) == 2
    assert not (run.root / "windows").exists()
    provider = Provider(bars("600002.SH"))
    source(run, provider).resolve_batch(batch)
    assert [c["ts_code"] for c in provider.calls] == ["600002.SH"]
    assert all(run.state("windows", w["window_id"])["ready"] == 1 for w, _ in batch)


def test_failed_window_drains_sibling_without_starting_third(root):
    run = three_windows(root)
    run.budget = dict(run.budget, attempts=1)
    batch = load_source_batch(run, 3)
    barrier = threading.Barrier(2)
    calls = []

    class FailingProvider:
        def call(self, api, params, fields):
            calls.append(params["ts_code"])
            barrier.wait(timeout=5)
            if params["ts_code"] == "600000.SH":
                raise RuntimeError("Source unavailable")
            time.sleep(0.1)
            return SimpleNamespace(rows=bars(params["ts_code"]), columns=core.COLUMNS)

    with pytest.raises(RuntimeError, match="bounded attempts"):
        source(run, FailingProvider()).resolve_batch(batch)
    assert set(calls) == {"600000.SH", "600001.SH"}
    assert len(list((run.root / "pages").glob("*.json"))) == 1
    assert run.state("windows", batch[0][0]["window_id"])["status"] == "failed"
    assert run.state("windows", batch[2][0]["window_id"]) is None


def test_shared_start_gate_includes_retries_and_does_not_wait_after_slow_response(root):
    run = three_windows(root)
    batch = load_source_batch(run, 3)
    starts = []
    attempts = {}
    cache = None

    class TimedProvider:
        def call(self, api, params, fields):
            code = params["ts_code"]
            starts.append(cache.clock())
            attempts[code] = attempts.get(code, 0) + 1
            if code == "600000.SH" and attempts[code] == 1:
                raise RuntimeError("Transient")
            return SimpleNamespace(rows=bars(code), columns=core.COLUMNS)

    cache = source(run, TimedProvider())
    cache.resolve_batch(batch)
    assert len(starts) == 4
    assert all(b - a >= 1 / 3 - 1e-8 for a, b in pairwise(starts))
    # A slow response already consumes the interval; the next start adds no delay.
    cache = source(run, Provider([]))
    page = {
        "params": {
            "ts_code": "600000.SH",
            "freq": "30min",
            "start_date": "2014-01-02",
            "end_date": "2014-01-02",
            "offset": 0,
            "limit": 8000,
        },
        "attempt": 1,
        "not_before": 0,
    }
    cache.request_gate.call(page)
    cache.sleep(1.0)
    before = cache.clock()
    cache.request_gate.call(page)
    assert cache.clock() == before


def test_batch_load_reads_scope_once_for_200_windows(root, monkeypatch):
    units = [
        (f"{600000 + i}.SH", day, [f"{600000 + i}.SH"])
        for i in range(200)
        for day in ["2014-01-02", "2014-01-03"]
    ]
    run = plan(root, units=units)
    from orchestrator.defs.bootstrap import stk_mins_gap_recovery_fetch as fetch

    read = fetch.records
    queries = []

    def capture(connection, sql, params):
        queries.append((sql, params))
        return read(connection, sql, params)

    monkeypatch.setattr(fetch, "records", capture)
    batch = load_source_batch(run, 200)
    assert len(batch) == 200 and sum(len(s) for _, s in batch) == 400
    assert sum(p[0].endswith("scope.parquet") for _, p in queries) == 1
    assert all("SELECT *" not in sql for sql, _ in queries)
    ids = [w["window_id"] for w, _ in batch]
    assert [w["window_id"] for w, _ in load_source_batch(run, 2, ids[::-1])] == ids[
        ::-1
    ][:2]
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        load_source_batch(run, 1, [ids[0], ids[0]])
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        load_source_batch(run, 1, ["unknown"])
    with pytest.raises(ValueError, match="exceeds"):
        load_source_batch(run, 201)


def test_membership_failure_is_detected_before_any_dispatch(root, monkeypatch):
    run = three_windows(root)
    from orchestrator.defs.bootstrap import stk_mins_gap_recovery_fetch as fetch

    read = fetch.records

    def truncated(connection, sql, params):
        rows = read(connection, sql, params)
        return rows[:-1] if params[0].endswith("scope.parquet") else rows

    monkeypatch.setattr(fetch, "records", truncated)
    with pytest.raises(ValueError, match="complete frozen scope"):
        load_source_batch(run, 3)
    assert not (run.root / "windows").exists()


def test_cancel_while_rate_waiting_never_starts_another_call(root):
    run = three_windows(root)
    provider = Provider([])
    cancelled = threading.Event()
    cache = SourceCache(
        run, provider, cancelled=cancelled.is_set, sleep=lambda _: cancelled.set()
    )
    cache.request_gate.next_start = cache.clock() + 100
    with pytest.raises(InterruptedError):
        cache.resolve_batch(load_source_batch(run, 3))
    assert provider.calls == []
    assert not (run.root / "pages").exists()
    assert not (run.root / "windows").exists()


def test_cli_uses_batch_selection_and_preserves_existing_completed_windows(
    root, monkeypatch
):
    from orchestrator.defs.bootstrap import stk_mins_gap_recovery_cli as cli

    run = three_windows(root)
    provider = Provider([r for i in range(3) for r in bars(f"60000{i}.SH")])
    monkeypatch.setattr(run, "require_operational_roots", lambda: None)
    monkeypatch.setattr(cli, "RecoveryRun", lambda *args: run)
    monkeypatch.setattr(cli, "TushareResource", lambda **kw: provider)
    monkeypatch.setenv("TUSHARE_TOKEN", "isolated-unused-token")
    common = ["fetch", "--plan", str(run.plan_path), "--plan-hash", run.hash, "--apply"]
    cli.main([*common, "--limit", "2"])
    assert len(provider.calls) == 2
    first = {p.name: p.read_bytes() for p in (run.root / "windows").glob("*.json")}
    cli.main([*common, "--limit", "2"])
    assert len(provider.calls) == 3
    assert all(
        (run.root / "windows" / name).read_bytes() == data
        for name, data in first.items()
    )
    assert not (run.root / "files").exists()


def test_duplicate_batch_rejected_without_source_calls(root):
    run = three_windows(root)
    batch = load_source_batch(run, 1)
    provider = Provider([])
    with pytest.raises(ValueError, match="Duplicate window"):
        source(run, provider).resolve_batch(batch * 2)
    assert provider.calls == []


def test_concurrent_business_results_equal_sequential_with_alias_partial_and_paging(
    root,
):
    units = [
        ("001872.SZ", "2014-01-02", ["001872.SZ", "000022.SZ"]),
        ("600001.SH", "2014-01-03", ["600001.SH"]),
        ("600002.SH", "2014-01-02", ["600002.SH"]),
    ]
    input_rows = bars("000022.SZ") + bars("600001.SH", "2014-01-03")[:2]
    summaries, requests = [], []
    for mode in ("sequential", "concurrent"):
        run = plan(root / mode, units=units)
        run.budget = dict(run.budget, page_limit=3)
        batch = load_source_batch(run, 3)
        provider = Provider(input_rows)
        cache = source(run, provider)
        if mode == "sequential":
            for window, scopes in batch:
                cache.resolve_window(window, scopes)
        else:
            cache.resolve_batch(batch)
        rows = []
        for path in (run.root / "resolutions").glob("*.json"):
            rows.extend(json.loads(path.read_text()))
        summaries.append(
            sorted(
                (r["scope_id"], r["status"], r["source_ts_code"], r.get("source_rows"))
                for r in rows
            )
        )
        requests.append(sorted(json.dumps(p, sort_keys=True) for p in provider.calls))
    assert summaries[0] == summaries[1]
    assert requests[0] == requests[1]
    assert {r[1] for r in summaries[0]} == {
        "source-ready",
        "source-partial",
        "source-empty",
    }


def test_local_processing_overlaps_another_source_call(root, monkeypatch):
    run = three_windows(root)
    batch = load_source_batch(run, 2)
    started = threading.Event()
    saved = threading.Event()
    write_page = source_module.write_page

    class OverlapProvider:
        def call(self, api, params, fields):
            if params["ts_code"] == "600000.SH":
                assert started.wait(5)
            else:
                started.set()
                assert saved.wait(5)
            return SimpleNamespace(rows=bars(params["ts_code"]), columns=core.COLUMNS)

    def save_while_second_in_flight(run, key, params, rows, **kw):
        result = write_page(run, key, params, rows, **kw)
        if params["ts_code"] == "600000.SH":
            saved.set()
        return result

    monkeypatch.setattr(source_module, "write_page", save_while_second_in_flight)
    source(run, OverlapProvider()).resolve_batch(batch)
    assert saved.is_set()


def test_latency_fixture_records_sequential_and_concurrent_times(root):
    """Artificial delay measurement is evidence of overlap, never a source ETA."""
    durations = {}
    for mode in ("sequential", "concurrent"):
        run = three_windows(root / mode)
        batch = load_source_batch(run, 3)
        provider = Provider(
            [r for i in range(3) for r in bars(f"60000{i}.SH")],
            after=lambda: time.sleep(0.65),
        )
        cache = SourceCache(run, provider)
        started = time.monotonic()
        if mode == "sequential":
            for window, scopes in batch:
                cache.resolve_window(window, scopes)
        else:
            cache.resolve_batch(batch)
        durations[mode] = time.monotonic() - started
    # Deterministic overlap assertions above are the gate; timing isn't a flaky SLA.
    print("source_latency_fixture_seconds=" + json.dumps(durations))
