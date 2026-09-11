"""Response provenance and cache reuse fail closed without touching formal data."""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import stk_mins_gap_recovery as core
from orchestrator.defs.bootstrap import stk_mins_gap_recovery_cli as cli
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_fetch import (
    SOURCE_RESPONSE_CONTRACT,
    assert_verified_empty_pages,
    load_source_batch,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import write_page
from tests.test_stk_mins_gap_recovery import (
    Provider,
    bars,
    plan,
    scopes,
    source,
    windows,
)
from tests.test_stk_mins_gap_recovery import root as isolated_root

root = isolated_root


@pytest.mark.parametrize(
    "columns", [(), core.COLUMNS[:-1], (*core.COLUMNS, "unexpected")]
)
def test_bad_response_schema_retries_without_caching_empty_or_trying_alias(
    root, columns
):
    run = plan(root)
    calls, events = [], []

    class BrokenProvider:
        def call(self, api, params, fields):
            calls.append(params["ts_code"])
            return SimpleNamespace(rows=[], columns=columns)

    window = windows(run)[0]
    with pytest.raises(RuntimeError, match="bounded attempts"):
        source(run, BrokenProvider(), progress=events.append).resolve_window(
            window, scopes(run, window)
        )
    assert calls == ["001872.SZ"] * 3
    assert not list((run.root / "pages").glob("*.json"))
    assert not list((run.root / "requests").glob("*.json"))
    assert run.state("windows", window["window_id"])["status"] == "failed"
    assert [e["stage"] for e in events].count("source_failure") == 3
    assert not any(e["stage"] == "source_response" for e in events)


def test_legal_empty_response_has_evidence_and_resumes_without_network(root):
    run = plan(root)
    provider = Provider([])
    window = windows(run)[0]
    cache = source(run, provider)
    cache.resolve_window(window, scopes(run, window))
    assert_verified_empty_pages(run)
    for path in (run.root / "pages").glob("*.json"):
        page = json.loads(path.read_text())
        assert page["rows"] == 0
        assert page["observed_columns"] == list(core.COLUMNS)
        assert page["response_contract"] == SOURCE_RESPONSE_CONTRACT
    count = len(provider.calls)
    cache.resolve_window(window, scopes(run, window))
    assert len(provider.calls) == count


@pytest.mark.parametrize(
    "action,extra",
    [
        ("fetch", ["--limit", "1"]),
        ("build-raw", ["--freq", "30", "--limit", "1"]),
        ("promote-raw", ["--freq", "30", "--limit", "1"]),
    ],
)
def test_unverified_empty_cache_blocks_cli_before_initialization(
    root, monkeypatch, action, extra
):
    run = plan(root)
    request = {
        "ts_code": "001872.SZ",
        "freq": "30min",
        "start_date": "2014-01-02 09:00:00",
        "end_date": "2014-01-02 19:00:00",
    }
    write_page(run, "unverified", request, [])
    monkeypatch.setattr(cli, "RecoveryRun", lambda *args: run)
    monkeypatch.setattr(run, "require_operational_roots", lambda: None)
    monkeypatch.setattr(
        run, "initialize", lambda: pytest.fail("must stop before writes")
    )
    with pytest.raises(RuntimeError, match="Unverified empty source cache: 1"):
        cli.main(
            [
                action,
                "--plan",
                str(run.plan_path),
                "--plan-hash",
                run.hash,
                "--apply",
                *extra,
            ]
        )


def test_old_nonempty_cache_is_preserved(root):
    run = plan(root)
    request = {
        "ts_code": "001872.SZ",
        "freq": "30min",
        "start_date": "2014-01-02 09:00:00",
        "end_date": "2014-01-02 19:00:00",
    }
    page = write_page(run, "nonempty", request, bars())
    assert "response_contract" not in page
    assert_verified_empty_pages(run)


def test_invalid_columns_drain_valid_sibling_without_starting_third_window(root):
    run = plan(
        root, units=[(f"60000{i}.SH", "2014-01-02", [f"60000{i}.SH"]) for i in range(3)]
    )
    run.budget = dict(run.budget, attempts=1)
    batch = load_source_batch(run, 3)
    barrier = threading.Barrier(2)
    calls = []

    class MixedProvider:
        def call(self, api, params, fields):
            calls.append(params["ts_code"])
            barrier.wait(timeout=5)
            if params["ts_code"] == "600000.SH":
                return SimpleNamespace(rows=[], columns=())
            time.sleep(0.05)
            return SimpleNamespace(rows=bars(params["ts_code"]), columns=core.COLUMNS)

    with pytest.raises(RuntimeError, match="bounded attempts"):
        source(run, MixedProvider()).resolve_batch(batch)
    assert set(calls) == {"600000.SH", "600001.SH"}
    pages = list((run.root / "pages").glob("*.json"))
    assert len(pages) == 1 and json.loads(pages[0].read_text())["rows"] == 9
    assert run.state("windows", batch[2][0]["window_id"]) is None
