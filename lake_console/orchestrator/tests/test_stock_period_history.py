import json
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.stock_period_history import (
    remove_dataset,
    run_period,
)
from orchestrator.defs.io.stock_period_raw import (
    PeriodCancelled,
    file_version,
    target_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    FIELDS,
    VERSION,
    StockPeriodPolicy,
)

POLICY = StockPeriodPolicy(
    duckdb_memory="256MiB", workspace_bytes=1024**3, spill_bytes=128 * 1024**2
)


def source(params):
    freq = params["freq"]
    day = "20261016" if freq == "week" else "20261031"
    return json.dumps(
        {
            "code": 0,
            "data": {
                "fields": list(FIELDS),
                "items": [
                    [params.get("ts_code", "000001.SZ"), day, "20261015", freq]
                    + [1.25] * 17
                ],
            },
        }
    ).encode()


def args(tmp_path):
    return {
        "root": tmp_path / "lake",
        "staging": tmp_path / "staging",
        "listed": {"000001.SZ"},
        "aliases": {},
        "policy": POLICY,
        "intent": {
            "version": VERSION,
            "mode": "bootstrap",
            "frequencies": ["week", "month"],
            "codes": ["000001.SZ"],
            "request_id": "test",
        },
        "transport": source,
    }


def test_delete_before_download_and_resume_does_not_clear(tmp_path):
    kw = args(tmp_path)
    old = target_path(kw["root"], "week", "2026-10-09")
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    cancelled = False
    calls = []

    def progress(event):
        nonlocal cancelled
        if event["stage"] == "file_committed":
            cancelled = True

    def transport(params):
        assert not old.exists()
        calls.append(params)
        return source(params)

    kw["transport"] = transport
    with pytest.raises(PeriodCancelled):
        run_period(**kw, cancel=lambda: cancelled, progress=progress)
    new = target_path(kw["root"], "week", "2026-10-16")
    version = file_version(new)
    run_period(**kw, events=lambda _: None)
    assert file_version(new) == version and len(calls) == 2
    assert (
        json.loads((kw["staging"] / "stock_period/baseline.json").read_text())["status"]
        == "ready"
    )


def test_event_failure_only_retries_event_and_preserves_file(tmp_path):
    kw = args(tmp_path)
    attempts = []

    def events(item):
        attempts.append(item["freq"])
        if item["freq"] == "month":
            raise OSError("event_failure")

    with pytest.raises(OSError):
        run_period(**kw, events=events)
    versions = [
        file_version(target_path(kw["root"], f, p))
        for f, p in [("week", "2026-10-16"), ("month", "2026-10")]
    ]
    kw["transport"] = lambda _: pytest.fail("source called on event-only resume")
    run_period(**kw, events=lambda i: attempts.append(i["freq"]))
    assert attempts == ["week", "month", "month"]
    assert versions == [
        file_version(target_path(kw["root"], f, p))
        for f, p in [("week", "2026-10-16"), ("month", "2026-10")]
    ]


def test_lock_wrong_roots_and_symlink_refuse(tmp_path):
    kw = args(tmp_path)
    import fcntl

    control = kw["staging"] / "stock_period"
    control.mkdir(parents=True)
    with (control / "writer.lock").open("a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="writer_busy"):
            run_period(**kw)
    with pytest.raises(ValueError, match="root_forbidden"):
        run_period(**{**kw, "root": Path("/private/not-a-lake")})
    target = target_path(kw["root"], "week", "2026-10-09")
    target.parent.mkdir(parents=True)
    outside = tmp_path / "keep"
    outside.write_bytes(b"keep")
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        remove_dataset(kw["root"], "week", lambda: False)
    assert outside.read_bytes() == b"keep"


def test_old_intent_and_empty_source_never_replace(tmp_path):
    kw = args(tmp_path)
    with pytest.raises(ValueError):
        run_period(
            **{**kw, "intent": {"contract_version": 1, "delivery_batch_id": "old"}}
        )
    kw["transport"] = lambda p: json.dumps(
        {"code": 0, "data": {"fields": list(FIELDS), "items": []}}
    ).encode()
    with pytest.raises(ValueError, match="source_empty"):
        run_period(**kw)
    assert not target_path(kw["root"], "week", "2026-10-16").exists()


def test_isolated_instance_events_bind_every_partition_and_resume(tmp_path):
    import dagster as dg

    from orchestrator.defs.stock_period_update import report_file_events

    (tmp_path / "instance").mkdir()
    with dg.DagsterInstance.local_temp(str(tmp_path / "instance")) as instance:
        kw = args(tmp_path)
        result = run_period(
            **kw, events=lambda item: report_file_events(instance, item)
        )
        for item in result["files"]:
            key = dg.AssetKey("raw_tushare_stk_period_bar_adj_" + item["freq"])
            first = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=[item["period"]]),
                limit=1,
            ).records[0]
            report_file_events(instance, item)
            latest = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=[item["period"]]),
                limit=1,
            ).records[0]
            assert first.storage_id == latest.storage_id


def test_cancel_during_assembly_preserves_sources_without_starting_publication(
    tmp_path,
):
    kw = args(tmp_path)
    cancelled = False
    calls = []

    def progress(event):
        nonlocal cancelled
        if event["stage"] == "import_source":
            cancelled = True

    def transport(params):
        calls.append(params["freq"])
        return source(params)

    kw["transport"] = transport
    with pytest.raises(PeriodCancelled):
        run_period(**kw, cancel=lambda: cancelled, progress=progress)
    assert not target_path(kw["root"], "week", "2026-10-16").exists()
    run_period(**kw)
    assert calls == ["week", "month"]


def test_candidate_manifest_change_and_unconfirmed_retirement_refuse(tmp_path):
    kw = args(tmp_path)
    result = run_period(**kw)
    path = Path(result["path"]) / "week.candidates.json"
    data = json.loads(path.read_text())
    data[0]["rows"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="candidate_manifest"):
        run_period(**kw)
    kw["intent"] = {
        "version": VERSION,
        "mode": "history",
        "frequencies": ["week"],
        "codes": [],
        "retired_codes": ["000001.SZ"],
    }
    with pytest.raises(ValueError, match="retirement_not_confirmed"):
        run_period(**kw)


def test_cancel_after_validated_candidate_reuses_copy_and_validation(
    tmp_path, monkeypatch
):
    import orchestrator.defs.io.stock_period_raw as raw

    kw = args(tmp_path)
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event["stage"] == "candidate_validated":
            cancelled = True

    with pytest.raises(PeriodCancelled):
        run_period(**kw, cancel=lambda: cancelled, progress=progress)
    original = raw.execute
    counts = []

    def execute(*a, **k):
        counts.append(k.get("stage", "sql"))
        return original(*a, **k)

    monkeypatch.setattr(raw, "execute", execute)
    run_period(**kw)
    # Only the untouched month builds; the completed weekly COPY/candidate are reused.
    assert counts.count("import_source") == 1 and counts.count("partition_copy") == 1


def test_confirmed_delisted_scope_makes_no_request_and_removes_rows(tmp_path):
    kw = args(tmp_path)
    run_period(**kw, events=lambda _: None)
    kw.update(
        listed=set(),
        confirmed_retired={"000001.SZ"},
        transport=lambda _: pytest.fail("delisted stock requested"),
        intent={
            "version": VERSION,
            "mode": "history",
            "frequencies": ["week", "month"],
            "codes": [],
            "retired_codes": ["000001.SZ"],
            "request_id": "retirement-fixture",
        },
    )
    result = run_period(**kw)
    assert len(result["files"]) == 2 and all(i["rows"] == 0 for i in result["files"])
