"""Safety boundaries use temporary roots and independent physical failure injection."""

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap.stock_period_history import (
    check_devices,
    devices,
    roots,
    run_period,
)
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_history import args
from tests.test_stock_period_raw import POLICY, row, sample


def candidate(tmp_path):
    return raw.assemble(
        [sample(tmp_path / "source", [row("000001.SZ", "20261016")])],
        work=tmp_path / "build",
        root=tmp_path / "lake",
        mode="bootstrap",
        freq="week",
        policy=POLICY,
    )[0]


@pytest.mark.parametrize("drift", ["appeared", "missing", "changed"])
def test_target_preimage_refuses_every_drift(tmp_path, drift):
    item = candidate(tmp_path)
    target = Path(item["target"])
    if drift == "appeared":
        target.parent.mkdir(parents=True)
        target.write_bytes(b"third-party")
    else:
        with raw.connection(tmp_path / "commit", POLICY) as con:
            raw.publish(item, checkpoint=tmp_path / "initial.json", con=con)
        item = raw.assemble(
            [
                sample(
                    tmp_path / "replacement", [row("000001.SZ", "20261016", price="2")]
                )
            ],
            work=tmp_path / "replacement-build",
            root=tmp_path / "lake",
            mode="history",
            freq="week",
            codes=["000001.SZ"],
            policy=POLICY,
        )[0]
        if drift == "missing":
            target.unlink()
        else:
            stamp = target.stat()
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    before = target.read_bytes() if target.exists() else None
    with (
        raw.connection(tmp_path / "publish", POLICY) as con,
        pytest.raises(ValueError, match="preimage_changed"),
    ):
        raw.publish(item, checkpoint=tmp_path / "new.json", con=con)
    assert (target.read_bytes() if target.exists() else None) == before
    assert Path(item["candidate"]).exists() and not (tmp_path / "new.json").exists()


def test_change_while_reading_affected_prices_is_rejected(tmp_path, monkeypatch):
    item = candidate(tmp_path)
    target = Path(item["target"])
    with raw.connection(tmp_path / "commit", POLICY) as con:
        raw.publish(item, checkpoint=tmp_path / "initial.json", con=con)
    execute = raw.execute

    def change(con, sql, parameters=None, **kw):
        result = execute(con, sql, parameters, **kw)
        if kw.get("stage") == "read_affected_once":
            stamp = target.stat()
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
        return result

    monkeypatch.setattr(raw, "execute", change)
    with pytest.raises(ValueError, match="preimage_changed"):
        raw.assemble(
            [sample(tmp_path / "update", [row("000001.SZ", "20261016")])],
            work=tmp_path / "update-build",
            root=tmp_path / "lake",
            mode="upsert",
            freq="week",
            periods=["2026-10-16"],
            policy=POLICY,
        )


def test_directory_sync_failure_recovers_exact_rename_without_rewrite(
    tmp_path, monkeypatch
):
    item = candidate(tmp_path)
    target = Path(item["target"])
    target.parent.mkdir(parents=True)
    real_sync = raw.sync_directory
    failed = False

    def sync(path):
        nonlocal failed
        if Path(path) == target.parent and target.exists() and not failed:
            failed = True
            raise OSError("directory_sync_failure")
        return real_sync(path)

    monkeypatch.setattr(raw, "sync_directory", sync)
    with raw.connection(tmp_path / "commit", POLICY) as con:
        with pytest.raises(OSError, match="directory_sync"):
            raw.publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)
        version = raw.file_version(target)
        assert not (tmp_path / "checkpoint.json").exists()
        digests = []
        real_digest = raw.file_digest
        monkeypatch.setattr(
            raw, "file_digest", lambda p: digests.append(str(p)) or real_digest(p)
        )
        raw.publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)
        raw.publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)
        assert raw.file_version(target) == version and digests == [str(target)]


def test_fsync_and_checkpoint_order(tmp_path, monkeypatch):
    import stat

    item = candidate(tmp_path)
    target, cp = Path(item["target"]), tmp_path / "checkpoint.json"
    target.parent.mkdir(parents=True)
    order = []
    real_sync, real_replace = os.fsync, os.replace

    def fsync(fd):
        order.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_sync(fd)

    def replace_file(source, destination):
        order.append("target" if Path(destination) == target else "checkpoint")
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace_file)
    with raw.connection(tmp_path / "commit", POLICY) as con:
        raw.publish(item, checkpoint=cp, con=con)
    assert order == ["file", "target", "directory", "file", "checkpoint", "directory"]


def test_missing_mount_or_device_drift_rejects_before_writes(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.stock_period_history as history

    monkeypatch.setattr(history.os.path, "ismount", lambda _: False)
    with pytest.raises(ValueError, match="mount_missing"):
        roots(
            Path("/Volumes/datasource/data_lake"),
            Path("/Volumes/datasource/data_lake_staging"),
        )
    expected = devices(tmp_path / "lake", tmp_path / "staging")
    expected["root"] += 1
    with pytest.raises(ValueError, match="device_changed"):
        check_devices(tmp_path / "lake", tmp_path / "staging", expected)
    kw = args(tmp_path)
    kw["listed"] = set()
    with pytest.raises(ValueError, match="listed_scope_empty"):
        run_period(**kw)
    assert not kw["root"].exists()


def test_budget_accumulates_frequencies_and_moves_without_double_count(
    tmp_path, monkeypatch
):
    run = tmp_path / "run"
    run.mkdir()
    policy = replace(POLICY, workspace_bytes=2048, spill_bytes=512)
    budget = raw.StorageBudget(run, policy)
    one, two = run / "week", run / "month"
    one.write_bytes(b"a" * 600)
    budget.record(one)
    two.write_bytes(b"b" * 600)
    budget.record(two)
    assert budget.used == 1200
    budget.reserve(100, spill=True)
    with pytest.raises(ValueError, match="workspace_budget"):
        budget.reserve(400, spill=True)
    target = tmp_path / "published"
    one.rename(target)
    budget.moved(one, target)
    assert budget.used == 1200
    monkeypatch.setattr(raw.shutil, "disk_usage", lambda _: SimpleNamespace(free=10))
    with pytest.raises(ValueError, match="free_space"):
        budget.reserve(11)
    budget.reserve(10)


def test_space_drop_stops_before_copy_and_keeps_captured_source(tmp_path, monkeypatch):
    kw = args(tmp_path)
    original = raw.execute
    copies = []

    def execute(*a, **k):
        copies.append(k.get("stage"))
        return original(*a, **k)

    monkeypatch.setattr(raw, "execute", execute)

    def progress(event):
        if event["stage"] == "source_unit_complete":
            monkeypatch.setattr(
                raw.shutil, "disk_usage", lambda _: SimpleNamespace(free=1)
            )

    with pytest.raises(ValueError, match="free_space"):
        run_period(**kw, progress=progress)
    assert "partition_copy" not in copies
    assert list(kw["staging"].glob("stock_period/runs/*/source/*/complete.json"))
    assert not list(kw["root"].glob("raw/tushare/*/*/*.parquet"))


def test_current_rss_is_real_and_history_peak_does_not_control_gate(monkeypatch):
    import resource

    assert raw.current_rss_bytes() > 0
    monkeypatch.setattr(
        resource, "getrusage", lambda _: SimpleNamespace(ru_maxrss=10**15)
    )
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 1024)
    raw.check_memory(replace(POLICY, rss_bytes=2048))
    with pytest.raises(ValueError, match="process_memory"):
        raw.check_memory(replace(POLICY, rss_bytes=512))


def test_recovery_budget_counts_already_published_target_once(tmp_path):
    run = tmp_path / "run"
    committed = run / "committed/week/2026-10-16.json"
    target = tmp_path / "published.parquet"
    target.write_bytes(b"x" * 1024)
    raw.atomic_json(committed, {"target": str(target)})
    budget = raw.StorageBudget(run, POLICY)
    used = target.stat().st_size + committed.stat().st_size
    assert budget.used == used
    budget.record(target)
    assert budget.used == used


def test_device_loss_after_capture_stops_before_copy(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.stock_period_history as history

    kw = args(tmp_path)
    real_devices = history.devices
    lost = False

    def devices(root, staging):
        result = real_devices(root, staging)
        if lost:
            result["root"] += 1
        return result

    def progress(event):
        nonlocal lost
        if event["stage"] == "source_unit_complete":
            lost = True

    monkeypatch.setattr(history, "devices", devices)
    with pytest.raises(ValueError, match="device_changed"):
        run_period(**kw, progress=progress)
    assert not list(kw["root"].glob("raw/tushare/stk_period_bar_adj_*/*/*.parquet"))
    assert list(kw["staging"].glob("stock_period/runs/*/source/*/complete.json"))


def test_process_term_during_native_sql_exits_and_releases_own_lock(tmp_path):
    import fcntl
    import json
    import signal
    import subprocess
    import sys
    import time

    program = """import json,os
from pathlib import Path
from orchestrator.defs.bootstrap.stock_period_history import writer
from orchestrator.defs.io.stock_period_raw import connection,execute
from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy
work=Path(__WORK__)
with writer(work/'staging'):
 with connection(work/'compute',StockPeriodPolicy(duckdb_memory='256MiB')) as con:
  print(json.dumps({'pid':os.getpid(),'ppid':os.getppid()}),flush=True)
  execute(con,'SELECT sum(i) FROM range(1000000000000) t(i)')
""".replace("__WORK__", repr(str(tmp_path)))
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        identity = json.loads(child.stdout.readline())
        assert identity == {"pid": child.pid, "ppid": os.getpid()}
        time.sleep(0.2)
        started = time.monotonic()
        child.send_signal(signal.SIGTERM)
        _, error = child.communicate(timeout=10)
        assert child.returncode == 143 and not error
        assert time.monotonic() - started < 10
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    with (tmp_path / "staging/stock_period/writer.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
