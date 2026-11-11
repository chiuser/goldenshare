"""Real temporary files/checkpoints; only the specific crash boundary is injected."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.io import stock_period_silver as io
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.run_contracts.stock_period_silver import target_path
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)


def execute(f, **kwargs):
    return silver.build(
        f["lake"],
        f["staging"],
        f["run_id"],
        audit_report=f["report"],
        emit=lambda _: None,
        **kwargs,
    )


def test_generation_and_completed_resume_do_not_copy(period_fixture, monkeypatch):
    f = period_fixture
    result = execute(f)
    assert result["totals"] == {
        "week": {"files": 3, "rows": 6},
        "month": {"files": 3, "rows": 6},
    }
    target = target_path(f["lake"], "week", "2014-01-03")
    version = file_version(target)
    monkeypatch.setattr(
        silver,
        "select_period",
        lambda *a, **k: pytest.fail("completed unit recomputed"),
    )
    silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
    assert file_version(target) == version


def test_cancel_between_units_keeps_first_and_resumes_remaining(
    period_fixture, monkeypatch
):
    f = period_fixture
    cancel = [False]
    original = silver.publish

    def publish(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel[0] = True
        return result

    monkeypatch.setattr(silver, "publish", publish)
    with pytest.raises(silver.SilverCancelled):
        execute(f, cancel=lambda: cancel[0])
    target = target_path(f["lake"], "week", "2014-01-03")
    version = file_version(target)
    assert not target_path(f["lake"], "week", "2020-04-03").exists()
    monkeypatch.setattr(silver, "publish", original)
    assert (
        silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)[
            "totals"
        ]["month"]["rows"]
        == 6
    )
    assert file_version(target) == version


def test_rename_then_checkpoint_failure_is_recovered_without_copy(
    period_fixture, monkeypatch
):
    f = period_fixture
    original = io.atomic_json

    def fail_commit(path, value):
        if value.get("state") == "committed":
            raise OSError("injected checkpoint failure after rename")
        return original(path, value)

    monkeypatch.setattr(io, "atomic_json", fail_commit)
    with pytest.raises(OSError, match="checkpoint failure"):
        execute(f)
    target = target_path(f["lake"], "week", "2014-01-03")
    version = file_version(target)
    monkeypatch.setattr(io, "atomic_json", original)
    calls = []
    select = silver.select_period

    def tracked(con, source, *args, **kwargs):
        calls.append(str(source))
        return select(con, source, *args, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
    assert len(calls) == 5
    assert file_version(target) == version


def test_validated_candidate_cancel_reused_without_select(period_fixture, monkeypatch):
    f = period_fixture
    original = silver.publish
    monkeypatch.setattr(
        silver,
        "publish",
        lambda *a, **k: (_ for _ in ()).throw(silver.SilverCancelled("before rename")),
    )
    with pytest.raises(silver.SilverCancelled):
        execute(f)
    work = io.run_directory(f["staging"], f["run_id"])
    cp = io.read_json(work / "files/week/2014-01-03.json")
    version = cp["candidate_version"][:4]
    monkeypatch.setattr(silver, "publish", original)
    silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
    assert file_version(target_path(f["lake"], "week", "2014-01-03"))[:4] == version


def test_unknown_target_symlink_lock_and_tampered_identity_rejected(
    period_fixture, tmp_path
):
    f = period_fixture
    target = target_path(f["lake"], "week", "2014-01-03")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"another writer")
    with pytest.raises(ValueError, match="unknown_target"):
        execute(f)
    assert target.read_bytes() == b"another writer"
    target.unlink()
    target.symlink_to(tmp_path / "outside.parquet")
    with pytest.raises(ValueError, match="symlink"):
        execute(f)
    target.unlink()
    with io.writer_lock(f["staging"]), pytest.raises(ValueError, match="writer_active"):
        execute(f)
    execute(f)
    work = io.run_directory(f["staging"], f["run_id"])
    execution = io.read_json(work / "execution.json")
    execution["identity"]["units"][0]["target"] = str(tmp_path / "outside")
    (work / "execution.json").write_text(json.dumps(execution))
    with pytest.raises(ValueError, match="identity_changed"):
        silver.build(f["lake"], f["staging"], f["run_id"])
    with pytest.raises(ValueError, match="unknown_target"):
        silver.build(f["lake"], f["staging"], str(uuid4()), audit_report=f["report"])


def test_unpassed_audit_or_outside_range_fails_before_output(period_fixture):
    f = period_fixture
    path = f["report"] / "summary.json"
    summary = json.loads(path.read_text())
    summary["status"] = "failed"
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="audit_not_passed"):
        execute(f)
    summary["status"] = "passed"
    summary["lower"] = "2015-01-01"
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="outside_audit_scope"):
        execute(f)


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_real_process_exit_releases_lock_and_reuses_candidate(
    period_fixture, termination
):
    f = period_fixture
    program = """
import sys,time
from pathlib import Path
from orchestrator.defs import stock_period_silver as silver
original = silver.publish
def pause(*args, **kwargs):
    print("VALIDATED_READY", flush=True)
    while True:
        silver.check_cancel(kwargs["cancel"])
        time.sleep(.02)
silver.publish = pause
silver.build(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],audit_report=Path(sys.argv[4]),emit=lambda _: None)
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-c",
            program,
            str(f["lake"]),
            str(f["staging"]),
            f["run_id"],
            str(f["report"]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(10), "child did not reach validated candidate"
            assert process.stdout.readline().strip() == "VALIDATED_READY"
        cp = io.read_json(
            io.run_directory(f["staging"], f["run_id"]) / "files/week/2014-01-03.json"
        )
        before = time.monotonic()
        os.kill(process.pid, termination)
        process.wait(timeout=5)
        assert time.monotonic() - before < 5
        with io.writer_lock(f["staging"]):
            pass  # OS released the actual child-held lock; no worker is created.
        silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
        assert (
            file_version(target_path(f["lake"], "week", "2014-01-03"))[:4]
            == cp["candidate_version"][:4]
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def test_long_sql_cancel_is_interrupted(tmp_path):
    import threading

    import duckdb

    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )

    event = threading.Event()
    with (
        connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=tmp_path / "interrupt_spill")
        ) as con,
        silver.cancellation(con, event.is_set),
    ):
        timer = threading.Timer(0.2, event.set)
        timer.start()
        began = time.monotonic()
        try:
            with pytest.raises(duckdb.InterruptException):
                con.execute("SELECT sum(sin(i)) FROM range(1000000000000) r(i)")
            assert time.monotonic() - began < 5
        finally:
            timer.join()


def test_changed_source_reference_and_candidate_cannot_resume(
    period_fixture, monkeypatch
):
    f = period_fixture
    original = silver.publish
    monkeypatch.setattr(
        silver,
        "publish",
        lambda *a, **k: (_ for _ in ()).throw(silver.SilverCancelled("before rename")),
    )
    with pytest.raises(silver.SilverCancelled):
        execute(f)
    monkeypatch.setattr(silver, "publish", original)
    work = io.run_directory(f["staging"], f["run_id"])
    record = io.read_json(work / "files/week/2014-01-03.json")
    with open(record["candidate"], "ab") as handle:
        handle.write(b"drift")
    with pytest.raises(ValueError, match="candidate_changed"):
        silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
    with open(f["references"]["lifecycle"], "ab") as handle:
        handle.write(b"drift")
    with pytest.raises(ValueError, match="reference_changed"):
        silver.build(f["lake"], f["staging"], f["run_id"], emit=lambda _: None)
