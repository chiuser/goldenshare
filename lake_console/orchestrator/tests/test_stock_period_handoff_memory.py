"""Handoff RSS wiring with real capture/build/publish and temporary roots.

Source literals follow doc365/FIELDS and the previously verified handoff fixture;
only HTTP and RSS observations are replaced. No GiBs are actually allocated.
"""

from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import digest, execution_id
from orchestrator.defs.stock_period_update import handoff_bootstrap
from tests.test_stock_period_combined import POLICY, A, B, row, wire
from tests.test_stock_period_handoff import captured, options

GIB = 1024**3


def stopped_handoff(tmp_path, monkeypatch):
    kw, parent, _ = captured(tmp_path, monkeypatch)
    calls, memory = [], {"high": False}
    execute = raw.execute

    def source(params):
        calls.append(params)
        freq = params["freq"]
        day = "20261016" if freq == "week" else "20261031"
        values = [row(A, day, freq, "3")]
        if "ts_code" not in params:
            values.append(row(B, day, freq, "9"))
        return wire(values)

    def measured(*args, **kwargs):
        if kwargs.get("stage") == "partition_copy":
            memory["high"] = True
        return execute(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", measured)
    monkeypatch.setattr(
        raw, "current_rss_bytes", lambda: 5 * GIB if memory["high"] else 1
    )
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        handoff_bootstrap(
            **options(kw, parent), transport=source, events=lambda _: True
        )
    frozen = raw.read_json(parent / "manifest.json")
    child = parent.parent / execution_id(frozen["handoff"]["intent"]["request_id"])
    assert len(calls) == 2 and {p["freq"] for p in calls} == {"week"}
    assert not (child / "build/week/copy.json").exists()
    assert not (child / "complete.json").exists()
    return kw, parent, child, calls, source


def child_args(kw, child):
    frozen = raw.read_json(child / "manifest.json")
    identity = frozen["identity"]
    return {
        "root": kw["root"],
        "staging": kw["staging"],
        "intent": identity["intent"],
        "listed": set(identity["listed"]),
        "aliases": identity["aliases"],
        "policy": POLICY,
    }


def test_handoff_override_reuses_week_source_and_preserves_frozen_identity(
    tmp_path, monkeypatch
):
    kw, parent, child, calls, source = stopped_handoff(tmp_path, monkeypatch)
    parent_identity = raw.read_json(parent / "manifest.json")["identity_hash"]
    child_before = raw.read_json(child / "manifest.json")
    sources = {
        str(p): (raw.file_version(p), p.read_bytes())
        for p in (child / "source").glob("*/complete.json")
    }
    assert len(sources) == 2
    monkeypatch.setattr(
        history, "remove_dataset", lambda *a: pytest.fail("root cleared")
    )
    progress = []
    state = handoff_bootstrap(
        **options(kw, parent),
        transport=source,
        events=lambda _: True,
        runtime_rss_bytes=6 * GIB,
        progress=progress.append,
    )
    assert state["handoff_cutoff"] == "2026-10-16"
    assert len(calls) == 4 and [p["freq"] for p in calls] == [
        "week",
        "week",
        "month",
        "month",
    ]
    after = raw.read_json(child / "manifest.json")
    assert after["identity"] == child_before["identity"]
    assert after["identity_hash"] == child_before["identity_hash"]
    assert raw.read_json(parent / "manifest.json")["identity_hash"] == parent_identity
    assert sources == {p: (raw.file_version(p), Path(p).read_bytes()) for p in sources}
    assert after["identity"]["policy"]["rss_bytes"] == 4 * GIB
    assert after["identity"]["policy"]["duckdb_memory"] == "256MiB"
    memory = [p for p in progress if p.get("stage") == "process_memory"]
    assert memory[-1]["rss_limit_bytes"] == 6 * GIB
    assert memory[-1]["observed_peak_rss_bytes"] == 5 * GIB
    complete = raw.read_json(child / "complete.json")
    with raw.connection(tmp_path / "readback", POLICY) as con:
        rows = con.execute(
            "SELECT ts_code,freq,CAST(close AS DOUBLE) FROM read_parquet(?,hive_partitioning=false)",
            [[f["target"] for f in complete["files"]]],
        ).fetchall()
    assert sorted(rows) == [
        (A, "month", 3.0),
        (A, "week", 3.0),
        (B, "month", 9.0),
        (B, "week", 9.0),
    ]
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"] == "ready"
    )
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(POLICY)


def test_cli_handoff_forwards_override_in_a_real_isolated_run(tmp_path, monkeypatch):
    import dagster as dg

    from orchestrator.defs import stock_period_update as update

    kw, parent, child, calls, source = stopped_handoff(tmp_path, monkeypatch)
    original = update.handoff_bootstrap

    def handoff(**kwargs):
        selected = options(kw, parent)
        selected.update(kwargs, transport=source)
        return original(**selected)

    monkeypatch.setattr(update, "handoff_bootstrap", handoff)
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    (instance_dir / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    instance = dg.DagsterInstance.local_temp(str(instance_dir))
    monkeypatch.setattr(dg.DagsterInstance, "get", lambda: instance)
    dispose = instance.dispose
    monkeypatch.setattr(instance, "dispose", lambda: None)
    argv = [
        "handoff",
        "--lake-root",
        str(kw["root"]),
        "--staging-root",
        str(kw["staging"]),
        "--run-id",
        parent.name,
        "--rss-limit-gib",
        "6",
    ]
    try:
        assert cli.main(argv) == 0
        assert len(calls) == 4
        assert len(instance.get_runs()) == 1 and instance.get_runs()[0].is_success
        assert raw.read_json(child / "manifest.json")["phase"] == "events_complete"
        versions = {
            f["target"]: raw.file_version(f["target"])
            for f in raw.read_json(child / "complete.json")["files"]
        }
        assert cli.main(argv) == 0
        assert len(calls) == 4 and len(instance.get_runs()) == 1
        assert versions == {p: raw.file_version(p) for p in versions}
    finally:
        dispose()


@pytest.mark.parametrize(
    "tamper",
    [
        "parent_hash",
        "parent_mode",
        "parent_phase",
        "parent_root",
        "parent_policy",
        "intent",
        "listed",
        "aliases",
        "baseline",
        "source",
    ],
)
def test_handoff_override_rejects_drift_before_new_source(
    tmp_path, monkeypatch, tamper
):
    kw, parent, child, _, _ = stopped_handoff(tmp_path, monkeypatch)
    saved = raw.read_json(parent / "manifest.json")
    if tamper == "parent_hash":
        saved["identity_hash"] = "0" * 64
    elif tamper.startswith("parent_"):
        field = tamper.removeprefix("parent_")
        if field == "mode":
            saved["identity"]["intent"]["mode"] = "history"
        elif field == "phase":
            saved["phase"] = "download"
        elif field == "root":
            saved["identity"]["root"] = str(tmp_path / "other")
        else:
            saved["identity"]["policy"]["rss_bytes"] = 6 * GIB
        saved["identity_hash"] = digest(saved["identity"])
    elif tamper == "intent":
        saved["handoff"]["intent"]["codes"] = []
    elif tamper == "listed":
        saved["handoff"]["listed"] = [A]
    elif tamper == "aliases":
        saved["handoff"]["aliases"] = {"old.BJ": "920000.BJ"}
    elif tamper == "baseline":
        path = kw["staging"] / "stock_period/baseline.json"
        facts = raw.read_json(path)
        facts["run_id"] = "0" * 64
        raw.atomic_json(path, facts)
    else:
        complete = raw.read_json(next((child / "source").glob("*/complete.json")))
        with Path(complete["pages"][0]["csv"]).open("ab") as handle:
            handle.write(b"drift")
    raw.atomic_json(parent / "manifest.json", saved)
    monkeypatch.setattr(
        history, "HttpPage", lambda **k: lambda p: pytest.fail("new source requested")
    )
    expected = (
        "period_saved_page_changed"
        if tamper == "source"
        else "period_(runtime_rss_handoff_invalid|manifest_changed)"
    )
    with pytest.raises(ValueError, match=expected):
        history.run_period(**child_args(kw, child), runtime_rss_bytes=6 * GIB)
    with history.writer(kw["staging"]):
        pass


def test_handoff_cancelled_override_keeps_sources_and_releases_lock(
    tmp_path, monkeypatch
):
    kw, parent, child, calls, source = stopped_handoff(tmp_path, monkeypatch)
    completed = {
        str(p): raw.file_version(p) for p in (child / "source").glob("*/complete.json")
    }
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event.get("stage") == "source_unit_complete":
            cancelled = True

    with pytest.raises(raw.PeriodCancelled):
        handoff_bootstrap(
            **options(kw, parent),
            transport=source,
            events=lambda _: True,
            runtime_rss_bytes=6 * GIB,
            cancel=lambda: cancelled,
            progress=progress,
        )
    assert len(calls) == 2 and completed == {p: raw.file_version(p) for p in completed}
    assert not (child / "complete.json").exists()
    with history.writer(kw["staging"]):
        pass
    state = handoff_bootstrap(
        **options(kw, parent),
        transport=source,
        events=lambda _: True,
        runtime_rss_bytes=6 * GIB,
    )
    assert state["handoff_cutoff"] == "2026-10-16" and len(calls) == 4


@pytest.mark.parametrize(
    "mode,parent",
    [
        ("upsert", None),
        ("history", None),
        ("upsert", "../outside"),
        ("upsert", "0" * 64),
    ],
)
def test_ordinary_updates_cannot_borrow_override(tmp_path, monkeypatch, mode, parent):
    kw, run, child, _, _ = stopped_handoff(tmp_path, monkeypatch)
    selected = child_args(kw, child)
    selected["intent"] = {
        **selected["intent"],
        "mode": mode,
        "bootstrap_parent": parent,
    }
    monkeypatch.setattr(
        history, "HttpPage", lambda **k: pytest.fail("new source requested")
    )
    with pytest.raises(
        ValueError, match="period_runtime_rss_(resume_required|handoff_invalid)"
    ):
        history.run_period(**selected, runtime_rss_bytes=6 * GIB)
    assert not raw.read_json(run / "manifest.json").get("handoff_complete")


def test_handoff_override_above_limit_preserves_uncommitted_files(
    tmp_path, monkeypatch
):
    kw, parent, child, calls, source = stopped_handoff(tmp_path, monkeypatch)
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 6 * GIB + 1)
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        handoff_bootstrap(
            **options(kw, parent),
            transport=source,
            events=lambda _: True,
            runtime_rss_bytes=6 * GIB,
        )
    assert len(calls) == 2 and not (child / "complete.json").exists()
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
