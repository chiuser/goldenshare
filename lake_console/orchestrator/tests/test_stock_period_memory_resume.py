"""RSS overrides preserve the existing producer's frozen source identities.

Source input uses test_stock_period_history's doc365-shaped literal response;
capture, assembly, publication and CLI parsing are real. RSS stubs below test
thresholds without allocating GiBs. They do not prove full-market COPY fits.
"""

import json
from contextvars import Context
from pathlib import Path
from threading import Event, current_thread

import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import (
    StockPeriodPolicy,
    execution_id,
)
from tests.test_stock_period_history import args, source

GIB = 1024**3


def resume_args(kw):
    return [
        "resume",
        "--lake-root",
        str(kw["root"]),
        "--staging-root",
        str(kw["staging"]),
        "--run-id",
        execution_id(kw["intent"]["request_id"]),
        "--rss-limit-gib",
        "6",
    ]


def test_override_limits_are_local_and_default_remains_frozen(monkeypatch):
    policy = StockPeriodPolicy()
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * GIB)
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(policy)
    progress = []
    with raw.process_memory_budget(policy, 6 * GIB, progress=progress.append):
        raw.check_memory(policy)
        # Another execution context must retain its own default limit.
        with pytest.raises(ValueError, match="period_process_memory_exceeded"):
            Context().run(raw.check_memory, policy)
        with (
            raw.process_memory_budget(policy),
            pytest.raises(ValueError, match="period_process_memory_exceeded"),
        ):
            raw.check_memory(policy)
        raw.check_memory(policy)
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(policy)
    assert progress[-1]["rss_limit_bytes"] == 6 * GIB
    assert progress[-1]["frozen_rss_limit_bytes"] == 4 * GIB
    assert progress[-1]["observed_peak_rss_bytes"] == 5 * GIB
    assert policy.payload()["rss_bytes"] == 4 * GIB
    assert policy.duckdb_memory == "3GiB"


@pytest.mark.parametrize(
    "error", [RuntimeError("failed"), raw.PeriodCancelled("cancelled")]
)
def test_error_and_cancel_reset_the_override(monkeypatch, error):
    policy = StockPeriodPolicy()
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * GIB)
    progress = []
    with (
        pytest.raises(type(error), match=str(error)),
        raw.process_memory_budget(policy, 6 * GIB, progress=progress.append),
    ):
        raise error
    assert progress[-1]["status"] == "failed"
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(policy)


def test_memory_failure_records_observed_value_and_stops_sql_worker(monkeypatch):
    """Replace only SQL with a blocking transport to test interrupt/join."""

    class BlockingSQL:
        def __init__(self):
            self.started, self.stopped = Event(), Event()
            self.thread = None

        def execute(self, *args):
            self.thread = current_thread()
            self.started.set()
            assert self.stopped.wait(5)

        def interrupt(self):
            self.stopped.set()

    con = BlockingSQL()
    progress = []
    monkeypatch.setattr(
        raw,
        "current_rss_bytes",
        lambda: 6 * GIB + 1 if con.started.is_set() else 5 * GIB,
    )
    with (
        pytest.raises(ValueError, match="period_process_memory_exceeded"),
        raw.process_memory_budget(
            StockPeriodPolicy(), 6 * GIB, progress=progress.append
        ),
    ):
        raw.execute(con, "SELECT 1", policy=StockPeriodPolicy())
    assert con.stopped.is_set() and not con.thread.is_alive()
    assert progress[-1]["status"] == "failed"
    assert progress[-1]["last_observed_rss_bytes"] == 6 * GIB + 1


def test_real_rss_observation_is_emitted():
    progress = []
    with raw.process_memory_budget(
        StockPeriodPolicy(), 6 * GIB, progress=progress.append
    ):
        raw.check_memory(StockPeriodPolicy())
    assert (
        0
        < progress[-1]["last_observed_rss_bytes"]
        <= progress[-1]["observed_peak_rss_bytes"]
    )
    assert progress[-1]["rss_limit_bytes"] == 6 * GIB


@pytest.mark.parametrize(
    "argv",
    [
        [action, "--rss-limit-gib", "6"]
        for action in ("prepare", "apply", "events", "handoff")
    ]
    + [["resume", "--rss-limit-gib", value] for value in ("0", "-1", "1.5")],
)
def test_invalid_cli_override_rejects_before_root_or_source_access(monkeypatch, argv):
    monkeypatch.setattr(
        cli, "roots", lambda *a: pytest.fail("invalid option reached IO")
    )
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2


def test_cli_resumes_copy_without_redownloading_completed_week(
    tmp_path, monkeypatch, capsys
):
    kw = args(tmp_path)
    calls, high_rss = [], False
    original_execute = raw.execute

    def transport(params):
        calls.append(params["freq"])
        return source(params)

    def execute(*a, **k):
        nonlocal high_rss
        if k.get("stage") == "partition_copy":
            high_rss = True
        return original_execute(*a, **k)

    kw["transport"] = transport
    monkeypatch.setattr(raw, "execute", execute)
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * GIB if high_rss else 1)
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        history.run_period(**kw)
    run = kw["staging"] / "stock_period/runs" / execution_id("test")
    frozen = raw.read_json(run / "manifest.json")
    complete = next((run / "source").glob("*/complete.json"))
    version, contents = raw.file_version(complete), complete.read_bytes()
    assert raw.read_json(complete)["identity"]["freq"] == "week"
    assert calls == ["week"]
    assert not kw["root"].exists()

    # CLI, frozen-policy loading and source cache lookup stay real. Only HTTP
    # is replaced; reaching it for the completed week is a regression.
    monkeypatch.setattr(history, "HttpPage", lambda **k: transport)
    assert cli.main(resume_args(kw)) == 0
    assert calls == ["week", "month"]
    after = raw.read_json(run / "manifest.json")
    assert after["identity"] == frozen["identity"]
    assert after["identity_hash"] == frozen["identity_hash"]
    assert raw.file_version(complete) == version and complete.read_bytes() == contents
    assert after["identity"]["policy"]["rss_bytes"] == 4 * GIB
    assert after["identity"]["policy"]["duckdb_memory"] == "256MiB"
    result = raw.read_json(run / "complete.json")
    with raw.connection(tmp_path / "independent_readback", kw["policy"]) as con:
        observed = sorted(
            con.execute(
                "SELECT ts_code,trade_date,freq,CAST(close AS DOUBLE) "
                "FROM read_parquet(?,hive_partitioning=false)",
                [[item["target"] for item in result["files"]]],
            ).fetchall()
        )
    assert observed == [
        ("000001.SZ", "20261016", "week", 1.25),
        ("000001.SZ", "20261031", "month", 1.25),
    ]
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    memory = [e for e in events if e.get("stage") == "process_memory"]
    assert memory[-1]["observed_peak_rss_bytes"] == 5 * GIB
    assert memory[-1]["rss_limit_bytes"] == 6 * GIB
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(kw["policy"])
    versions = {
        item["target"]: raw.file_version(item["target"]) for item in result["files"]
    }
    assert cli.main(resume_args(kw)) == 0
    assert calls == ["week", "month"]
    assert versions == {p: raw.file_version(p) for p in versions}


@pytest.mark.parametrize("tamper", ["manifest", "source"])
def test_override_cannot_bypass_frozen_or_source_drift(tmp_path, monkeypatch, tamper):
    kw = args(tmp_path)
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event.get("stage") == "source_unit_complete":
            cancelled = True

    with pytest.raises(raw.PeriodCancelled):
        history.run_period(**kw, progress=progress, cancel=lambda: cancelled)
    run = kw["staging"] / "stock_period/runs" / execution_id("test")
    if tamper == "manifest":
        saved = raw.read_json(run / "manifest.json")
        saved["identity"]["policy"]["rss_bytes"] = 6 * GIB
        raw.atomic_json(run / "manifest.json", saved)  # Deliberate invalid input.
        reason = "period_manifest_changed"
    else:
        complete = raw.read_json(next((run / "source").glob("*/complete.json")))
        with Path(complete["pages"][0]["csv"]).open("ab") as handle:
            handle.write(b"corrupted")  # Deliberate version drift.
        reason = "period_saved_page_changed"
    monkeypatch.setattr(
        history, "HttpPage", lambda **k: lambda p: pytest.fail("source requested")
    )
    with pytest.raises(ValueError, match=reason):
        cli.main(resume_args(kw))
    with history.writer(kw["staging"]):
        pass  # Failure released the real lock.


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_internal_invalid_limit_cannot_start_work(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(
        history, "writer", lambda *a: pytest.fail("invalid limit acquired writer")
    )
    with pytest.raises(ValueError, match="period_runtime_rss_limit_invalid"):
        history.run_period(**args(tmp_path), runtime_rss_bytes=limit)


def test_override_requires_existing_bootstrap(tmp_path):
    kw = args(tmp_path)
    with pytest.raises(ValueError, match="period_runtime_rss_resume_required"):
        history.run_period(**kw, runtime_rss_bytes=6 * GIB)
    assert not kw["root"].exists() and not kw["staging"].exists()


def test_cli_rejects_override_for_a_real_history_refresh(tmp_path, monkeypatch):
    kw = args(tmp_path)
    bootstrap = history.run_period(**kw)
    kw["intent"] = {
        **kw["intent"],
        "mode": "history",
        "request_id": "history-refresh",
        "bootstrap_parent": bootstrap["run_id"],
    }
    refreshed = history.run_period(**kw)
    manifest = Path(refreshed["path"]) / "manifest.json"
    before = manifest.read_bytes()
    monkeypatch.setattr(
        history, "HttpPage", lambda **k: pytest.fail("source requested")
    )
    with pytest.raises(SystemExit) as caught:
        cli.main(resume_args(kw))
    assert caught.value.code == 2 and manifest.read_bytes() == before


def test_cancelled_override_releases_lock_and_preserves_completed_source(
    tmp_path, monkeypatch
):
    kw = args(tmp_path)
    calls, cancelled = [], False

    def transport(params):
        calls.append(params["freq"])
        return source(params)

    def progress(event):
        nonlocal cancelled
        if event.get("stage") == "source_unit_complete":
            cancelled = True

    kw["transport"] = transport
    with pytest.raises(raw.PeriodCancelled):
        history.run_period(**kw, progress=progress, cancel=lambda: cancelled)
    run = kw["staging"] / "stock_period/runs" / execution_id("test")
    complete = next((run / "source").glob("*/complete.json"))
    version = raw.file_version(complete)
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * GIB)
    monkeypatch.setattr(
        history, "remove_dataset", lambda *a: pytest.fail("root cleared again")
    )
    cancelled = False
    with pytest.raises(raw.PeriodCancelled):
        history.run_period(
            **kw, runtime_rss_bytes=6 * GIB, progress=progress, cancel=lambda: cancelled
        )
    with history.writer(kw["staging"]):
        pass
    assert calls == ["week"] and raw.file_version(complete) == version
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(kw["policy"])
    result = history.run_period(**kw, runtime_rss_bytes=6 * GIB)
    assert len(result["files"]) == 2 and calls == ["week", "month"]
    assert raw.file_version(complete) == version


def test_reporting_failure_cannot_leak_override_or_mask_primary_error(monkeypatch):
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * GIB)

    def failed_report(event):
        if event["status"] != "started":
            raise OSError("report_down")

    with (
        pytest.raises(RuntimeError, match="primary"),
        raw.process_memory_budget(StockPeriodPolicy(), 6 * GIB, progress=failed_report),
    ):
        raise RuntimeError("primary")
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(StockPeriodPolicy())
