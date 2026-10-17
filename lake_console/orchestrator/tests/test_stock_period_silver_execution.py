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
    A,
    B,
    C,
    literal_row,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)


def capture_history_change(f):
    # Independent intended change: remove A's first week, revise its remaining QFQ.
    rows = []
    for row in f["state"]["rows"]:
        if row[0] == A and row[3] == "week":
            if row[1] == "20140103":
                continue
            row = list(row)
            row[9:13] = ["19.1000", "19.5000", "19.0000", "19.2500"]
        rows.append(row)
    f["state"]["rows"] = rows
    return f["capture"]()


def update(f, reference, run_id=None, **kwargs):
    return silver.build(
        f["lake"],
        f["staging"],
        run_id or str(uuid4()),
        freq="week",
        source_completion=reference,
        instance=f["instance"],
        emit=lambda _: None,
        **kwargs,
    )


def interrupted_update(f, monkeypatch, freq="week"):
    """Real Raw producer + two real commits; only cancellation is injected."""
    for row in f["state"]["rows"]:
        if row[0] == A and row[3] == freq:
            row[9:13] = ["19.1000", "19.5000", "19.0000", "19.2500"]
    reference = f["capture"](freq=freq)
    run_id, committed = str(uuid4()), []
    original = silver.publish

    def stop(*args, **kwargs):
        record = original(*args, **kwargs)
        committed.append(record)
        return record

    with monkeypatch.context() as patch:
        patch.setattr(silver, "publish", stop)
        with pytest.raises(silver.SilverCancelled):
            silver.build(
                f["lake"],
                f["staging"],
                run_id,
                freq=freq,
                source_completion=reference,
                instance=f["instance"],
                cancel=lambda: len(committed) == 2,
                emit=lambda _: None,
            )
    return run_id, reference, committed


def refresh_recovery_tail(f, freq="week", *, publish=True):
    """Real producer metadata; publish=False deliberately creates a bad publication."""
    from tests.test_stock_period_silver_contracts import publish_completion_contract

    for row in f["state"]["rows"]:
        if row[0] == A and row[3] == freq and row[1].startswith("202610"):
            row[9:13] = ["20.1000", "20.5000", "20.0000", "20.2500"]
    period = "2026-10-16" if freq == "week" else "2026-10"
    reference = f["capture"](mode="upsert", freq=freq, codes=(), periods=[period])
    if publish:
        publish_completion_contract(f, reference, freq)
    else:
        # Raw now publishes this field itself. Omitting the former fixture
        # adapter no longer creates a negative case: explicitly remove the
        # reference from an otherwise genuine file materialization instead.
        import dagster as dg

        from orchestrator.defs.bootstrap.stock_period_silver_cli import run_reporting
        from orchestrator.defs.run_contracts.stock_period import COMPLETION_METADATA_KEY
        from orchestrator.defs.stock_period_update import report_file_events

        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}")
        old = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[period]),
                limit=1,
            )
            .records[0]
        )
        item = next(
            i
            for i in io.read_json(
                f["staging"]
                / "stock_period/runs"
                / reference["raw_execution_id"]
                / "complete.json"
            )["files"]
            if i["freq"] == freq and i["period"] == period
        )

        def invalid_publication(ctx):
            f["instance"].report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=period,
                    metadata={
                        k: v
                        for k, v in old.asset_materialization.metadata.items()
                        if k != COMPLETION_METADATA_KEY
                    },
                )
            )
            report_file_events(f["instance"], item, context=ctx)

        run_reporting(f["instance"], invalid_publication)
    return period


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_update_process_exit_keeps_commits_and_releases_both_locks(
    update_fixture, monkeypatch, termination
):
    from orchestrator.defs.bootstrap.stock_period_history import writer

    f = update_fixture
    run_id, _, committed = interrupted_update(f, monkeypatch)
    program = """
import sys,time
from pathlib import Path
from orchestrator.defs import stock_period_silver as silver
original=silver.publish
def pause(record,*args,**kwargs):
    if record['state']=='validated':
        print('VALIDATED_READY',flush=True)
        while True:
            silver.check_cancel(kwargs['cancel'])
            time.sleep(.02)
    return original(record,*args,**kwargs)
silver.publish=pause
silver.build(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],emit=lambda _:None)
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-c",
            program,
            str(f["lake"]),
            str(f["staging"]),
            run_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(10), "update child did not reach candidate"
            assert process.stdout.readline().strip() == "VALIDATED_READY"
        cp = io.read_json(
            io.run_directory(f["staging"], run_id) / "files/week/2026-10-16.json"
        )
        os.kill(process.pid, termination)
        process.wait(timeout=5)
        with writer(f["staging"]), io.writer_lock(f["staging"]):
            pass
        with monkeypatch.context() as patch:
            patch.setattr(
                silver,
                "select_period",
                lambda *a, **k: pytest.fail("accepted candidate recomputed"),
            )
            result = silver.build(
                f["lake"],
                f["staging"],
                run_id,
                instance=f["instance"],
                emit=lambda _: None,
            )
        assert result["totals"]["week"]["files"] == 3
        assert all(file_version(r["target"]) == r["version"] for r in committed)
        assert file_version(cp["target"])[:4] == cp["candidate_version"][:4]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


@pytest.mark.parametrize("changed", [False, True])
def test_cli_resume_shares_recovery_and_never_reports_events(
    update_fixture, monkeypatch, capsys, changed
):
    from contextlib import nullcontext

    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli

    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    if changed:
        refresh_recovery_tail(f)
    source_count = len(f["source_calls"])
    monkeypatch.setattr(
        cli.dg.DagsterInstance, "get", lambda: nullcontext(f["instance"])
    )
    monkeypatch.setattr(
        cli, "run_reporting", lambda *a, **k: pytest.fail("resume wrote events")
    )
    calls, select = [], silver.select_period

    def tracked(con, source, freq, period, **kwargs):
        calls.append(period)
        return select(con, source, freq, period, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    assert (
        cli.main(
            [
                "resume",
                "--run-id",
                old_id,
                "--lake-root",
                str(f["lake"]),
                "--staging-root",
                str(f["staging"]),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (result["run_id"] != old_id) == changed
    assert calls == ["2026-10-16"]
    assert all(file_version(r["target"]) == r["version"] for r in committed)
    assert not (
        io.run_directory(f["staging"], result["run_id"]) / "events_complete.json"
    ).exists()
    assert len(f["source_calls"]) == source_count


def test_recovery_requires_published_new_raw_reference(update_fixture, monkeypatch):
    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f, publish=False)
    with pytest.raises(ValueError, match="newer_raw_completion_missing"):
        silver.build(
            f["lake"], f["staging"], old_id, instance=f["instance"], emit=lambda _: None
        )
    assert all(file_version(r["target"]) == r["version"] for r in committed)


def test_committed_version_cannot_relabel_an_unknown_replacement(
    update_fixture, monkeypatch
):
    from pathlib import Path

    f = update_fixture
    run_id, _, committed = interrupted_update(f, monkeypatch)
    path = io.run_directory(f["staging"], run_id) / "files/week/2014-01-03.json"
    record = io.read_json(path)
    Path(record["target"]).write_bytes(b"unrelated writer")
    record["version"] = file_version(record["target"])
    path.write_text(json.dumps(record))
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("unknown replacement computed"),
    )
    with pytest.raises(ValueError, match="candidate_identity_changed"):
        silver.build(
            f["lake"], f["staging"], run_id, instance=f["instance"], emit=lambda _: None
        )
    assert file_version(committed[1]["target"]) == committed[1]["version"]


def test_frozen_successor_without_local_checkpoints_uses_explicit_parent(
    update_fixture, monkeypatch
):
    f = update_fixture
    old_id, reference, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f)
    parent = silver.load_execution(f["lake"], f["staging"], old_id)
    child = silver.recover_update_execution(
        f["lake"], f["staging"], parent, f["instance"]
    )
    child_id = child["identity"]["run_id"]
    assert not (io.run_directory(f["staging"], child_id) / "files").exists()
    result = silver.build(
        f["lake"],
        f["staging"],
        child_id,
        freq="week",
        source_completion=reference,
        resume_from_execution_id=old_id,
        instance=f["instance"],
        emit=lambda _: None,
    )
    assert result["run_id"] == child_id
    assert all(file_version(r["target"]) == r["version"] for r in committed)


def test_immutable_recovery_evidence_is_read_once_and_still_rejects_drift(
    update_fixture, monkeypatch
):
    f = update_fixture
    original, calls = silver.read_json, []

    def read(path):
        calls.append(str(path))
        return original(path)

    monkeypatch.setattr(silver, "read_json", read)
    with silver.recovery_evidence():
        for _ in range(20):
            silver.load_execution(f["lake"], f["staging"], f["run_id"])
        assert len(calls) == 1
        with pytest.raises(ValueError, match="identity_changed"):
            silver.load_execution(f["lake"] / "elsewhere", f["staging"], f["run_id"])
        path = io.run_directory(f["staging"], f["run_id"]) / "execution.json"
        path.write_text(path.read_text() + " ")
        with pytest.raises(ValueError, match="evidence_changed"):
            silver.load_execution(f["lake"], f["staging"], f["run_id"])


@pytest.mark.parametrize(
    "fault", ["parent_hash", "cross_root", "wrong_parent", "cycle", "inherited_record"]
)
def test_recovery_rejects_invalid_parent_or_inheritance(
    update_fixture, monkeypatch, fault
):
    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f)
    parent = silver.load_execution(f["lake"], f["staging"], old_id)
    child = silver.recover_update_execution(
        f["lake"], f["staging"], parent, f["instance"]
    )
    child_id = child["identity"]["run_id"]
    if fault == "inherited_record":
        path = io.run_directory(f["staging"], old_id) / "files/week/2014-01-03.json"
        record = io.read_json(path)
        record["rows"] += 1
        path.write_text(json.dumps(record))
    else:
        if fault == "parent_hash":
            child["identity"]["resume_from_identity_hash"] = "0" * 64
        elif fault == "cross_root":
            child["identity"]["lake"] = str(f["lake"] / "elsewhere")
        elif fault == "wrong_parent":
            child["identity"]["resume_from_execution_id"] = f["run_id"]
            child["identity"]["resume_from_identity_hash"] = silver.load_execution(
                f["lake"], f["staging"], f["run_id"]
            )["identity_hash"]
        else:
            child["identity"]["resume_from_execution_id"] = child_id
        child["identity_hash"] = silver.fingerprint(child["identity"])
        (io.run_directory(f["staging"], child_id) / "execution.json").write_text(
            json.dumps(child)
        )
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("bad recovery computed"),
    )
    with pytest.raises(ValueError):
        silver.build(
            f["lake"],
            f["staging"],
            child_id,
            instance=f["instance"],
            emit=lambda _: None,
        )
    assert all(file_version(r["target"]) == r["version"] for r in committed)


@pytest.mark.parametrize(
    "fault", ["rows", "checks", "source_version", "identity_hash", "target"]
)
def test_recovery_rejects_damaged_checkpoint_before_other_work(
    update_fixture, monkeypatch, fault
):
    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    path = io.run_directory(f["staging"], old_id) / "files/week/2014-01-03.json"
    record = io.read_json(path)
    if fault == "rows":
        record["rows"] += 10
    elif fault == "checks":
        record["checks"]["file_contract"] = False
    elif fault == "target":
        record["target"] = str(f["lake"] / "not-owned.parquet")
    else:
        record[fault] = "damaged"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("damaged record computed"),
    )
    with pytest.raises(ValueError):
        silver.build(
            f["lake"], f["staging"], old_id, instance=f["instance"], emit=lambda _: None
        )
    assert all(file_version(r["target"]) == r["version"] for r in committed)


def test_successor_can_cancel_again_resume_and_close_exact_original_scope(
    update_fixture, monkeypatch
):
    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli

    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f)
    actual = []
    original = silver.publish

    def stopped(record, *args, **kwargs):
        if record["period"] == "2026-10-16":
            raise silver.SilverCancelled("successor before rename")
        return original(record, *args, **kwargs)

    def progress(value):
        data = json.loads(value)
        if data["stage"] == "recovery":
            actual.append(data["run_id"])

    with monkeypatch.context() as patch:
        patch.setattr(silver, "publish", stopped)
        with pytest.raises(silver.SilverCancelled):
            silver.build(
                f["lake"], f["staging"], old_id, instance=f["instance"], emit=progress
            )
    assert len(actual) == 1
    assert not (
        io.run_directory(f["staging"], old_id) / "events_complete.json"
    ).exists()
    with monkeypatch.context() as patch:
        patch.setattr(
            silver,
            "select_period",
            lambda *a, **k: pytest.fail("validated successor selected again"),
        )
        result = silver.build(
            f["lake"],
            f["staging"],
            actual[0],
            instance=f["instance"],
            emit=lambda _: None,
        )
    assert result["run_id"] == actual[0]
    completed = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], actual[0], f["instance"], ctx
        ),
    )
    assert completed["status"] == "complete" and completed["files"] == 3
    coverage = io.read_json(
        io.run_directory(f["staging"], old_id) / "events_complete.json"
    )
    assert coverage["covered_by_execution_id"] == actual[0]
    assert all(file_version(r["target"]) == r["version"] for r in committed)
    again = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], old_id, f["instance"], ctx
        ),
    )
    assert again == coverage


@pytest.mark.parametrize("freq", ["week", "month"])
def test_recovery_only_rebuilds_changed_unfinished_period(
    update_fixture, monkeypatch, freq
):
    f = update_fixture
    old_id, reference, committed = interrupted_update(f, monkeypatch, freq)
    work = io.run_directory(f["staging"], old_id)
    old_identity = (work / "execution.json").read_bytes()
    for row in f["state"]["rows"]:
        if row[0] == A and row[3] == freq and row[1].startswith("202610"):
            row[9:13] = ["20.1000", "20.5000", "20.0000", "20.2500"]
    period = "2026-10-16" if freq == "week" else "2026-10"
    latest = f["capture"](mode="upsert", freq=freq, codes=(), periods=[period])
    from tests.test_stock_period_silver_contracts import publish_completion_contract

    publish_completion_contract(f, latest, freq)
    source_count = len(f["source_calls"])
    original, selected = silver.select_period, []

    def select(con, source, frequency, key, **kwargs):
        selected.append((frequency, key))
        return original(con, source, frequency, key, **kwargs)

    monkeypatch.setattr(silver, "select_period", select)
    result = silver.build(
        f["lake"], f["staging"], old_id, instance=f["instance"], emit=lambda _: None
    )
    assert result["run_id"] != old_id
    assert selected == [(freq, period)]
    assert (work / "execution.json").read_bytes() == old_identity
    assert all(file_version(r["target"]) == r["version"] for r in committed)
    execution = silver.load_execution(f["lake"], f["staging"], result["run_id"])
    assert execution["identity"]["source_completion"] == reference
    assert execution["identity"]["resume_from_execution_id"] == old_id
    assert len(execution["identity"]["units"]) == 3
    with silver.connect_configured_duckdb(
        silver.DuckDBConnectionSettings(
            temp_directory=f["staging"] / "recovery_expected"
        )
    ) as con:
        rows = con.execute(
            "SELECT ts_code,CAST(close_qfq AS VARCHAR) FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(target_path(f["lake"], freq, period))],
        ).fetchall()
    # VARCHAR ts_code ORDER BY: 000001.SZ, 301569.SZ, 920000.BJ.
    assert rows == [(A, "20.2500"), (C, "11.1400"), (B, "11.1400")]
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("completed recovery recomputed"),
    )
    replay = silver.build(
        f["lake"], f["staging"], old_id, instance=f["instance"], emit=lambda _: None
    )
    assert replay["run_id"] == result["run_id"]
    assert len(f["source_calls"]) == source_count


def test_update_existing_history_removes_old_key_without_touching_months(
    update_fixture, monkeypatch
):
    f = update_fixture
    untouched = {
        p: file_version(target_path(f["lake"], "month", p))
        for p in ("2020-02", "2020-04", "2026-10")
    }
    reference = capture_history_change(f)
    count = len(f["source_calls"])
    run_id = str(uuid4())
    result = update(f, reference, run_id)
    assert result["totals"] == {
        "week": {"files": 3, "rows": 5},
        "month": {"files": 0, "rows": 0},
    }
    with silver.connect_configured_duckdb(
        silver.DuckDBConnectionSettings(temp_directory=f["staging"] / "verify")
    ) as con:
        path = target_path(f["lake"], "week", "2014-01-03")
        assert (
            con.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchone()[0]
            == 0
        )
        path = target_path(f["lake"], "week", "2020-04-03")
        rows = con.execute(
            "SELECT ts_code,cast(close_qfq AS VARCHAR) FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(path)],
        ).fetchall()
        assert rows == [(A, "19.2500"), (B, "11.1400")]
    versions = {
        p: file_version(target_path(f["lake"], "week", p))
        for p in ("2014-01-03", "2020-04-03", "2026-10-16")
    }
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("completed update recomputed"),
    )
    silver.build(f["lake"], f["staging"], run_id, emit=lambda _: None)
    assert all(
        file_version(target_path(f["lake"], "week", p)) == v
        for p, v in versions.items()
    )
    assert all(
        file_version(target_path(f["lake"], "month", p)) == v
        for p, v in untouched.items()
    )
    assert len(f["source_calls"]) == count


def test_update_new_period_keeps_source_date_and_creates_only_selected_week(
    update_fixture,
):
    f = update_fixture
    f["state"]["rows"] += [
        literal_row(code, "20261023", "week", asof="20261019") for code in (A, B, C)
    ]
    reference = f["capture"](
        mode="upsert", codes=(), periods=["2026-10-23"], asof="2026-10-19"
    )
    result = update(f, reference)
    assert result["totals"]["week"] == {"files": 1, "rows": 3}
    with silver.connect_configured_duckdb(
        silver.DuckDBConnectionSettings(temp_directory=f["staging"] / "verify")
    ) as con:
        rows = con.execute(
            "SELECT DISTINCT trade_date,end_date FROM read_parquet(?,hive_partitioning=false)",
            [str(target_path(f["lake"], "week", "2026-10-23"))],
        ).fetchall()
    assert rows == [("20261023", "20261019")]
    assert not target_path(f["lake"], "month", "2026-11").exists()


def test_update_cancel_after_commit_and_resume_keeps_committed_file(
    update_fixture, monkeypatch
):
    f = update_fixture
    reference = capture_history_change(f)
    run_id, stopped = str(uuid4()), [False]
    original = silver.publish

    def publish(*args, **kwargs):
        result = original(*args, **kwargs)
        stopped[0] = True
        return result

    monkeypatch.setattr(silver, "publish", publish)
    with pytest.raises(silver.SilverCancelled):
        update(f, reference, run_id, cancel=lambda: stopped[0])
    first = target_path(f["lake"], "week", "2014-01-03")
    version = file_version(first)
    monkeypatch.setattr(silver, "publish", original)
    result = silver.build(f["lake"], f["staging"], run_id, emit=lambda _: None)
    assert result["totals"]["week"] == {"files": 3, "rows": 5}
    assert file_version(first) == version
    with io.writer_lock(f["staging"]):
        pass


@pytest.mark.parametrize("fault", ["target_preimage", "source", "receipt"])
def test_update_frozen_candidate_rejects_drift_without_overwriting(
    update_fixture, monkeypatch, fault
):
    f = update_fixture
    reference = capture_history_change(f)
    run_id = str(uuid4())
    original = silver.publish
    monkeypatch.setattr(
        silver,
        "publish",
        lambda *a, **k: (_ for _ in ()).throw(silver.SilverCancelled("before rename")),
    )
    with pytest.raises(silver.SilverCancelled):
        update(f, reference, run_id)
    work = io.run_directory(f["staging"], run_id)
    original_execution = (work / "execution.json").read_bytes()
    record = io.read_json(work / "files/week/2014-01-03.json")
    candidate_version = file_version(record["candidate"])
    if fault == "target_preimage":
        from pathlib import Path

        Path(record["target"]).write_bytes(b"other writer")
    elif fault == "source":
        from pathlib import Path

        Path(record["source"]).write_bytes(b"other source writer")
    else:
        receipt = (
            f["staging"]
            / "stock_period/runs"
            / reference["raw_execution_id"]
            / "complete.json"
        )
        value = io.read_json(receipt)
        value["files"] = []
        receipt.write_text(json.dumps(value))
    monkeypatch.setattr(silver, "publish", original)
    with pytest.raises(
        ValueError,
        match={
            "target_preimage": "preimage_changed",
            "source": "source_changed",
            "receipt": "completion_changed",
        }[fault],
    ):
        silver.build(f["lake"], f["staging"], run_id, emit=lambda _: None)
    assert (work / "execution.json").read_bytes() == original_execution
    assert file_version(record["candidate"]) == candidate_version


def test_update_rename_checkpoint_failure_recovers_candidate_without_select(
    update_fixture, monkeypatch
):
    f = update_fixture
    reference = capture_history_change(f)
    run_id = str(uuid4())
    original = io.atomic_json

    def fail(path, value):
        if value.get("state") == "committed":
            raise OSError("after update rename")
        return original(path, value)

    monkeypatch.setattr(io, "atomic_json", fail)
    with pytest.raises(OSError, match="after update rename"):
        update(f, reference, run_id)
    first = target_path(f["lake"], "week", "2014-01-03")
    version = file_version(first)
    monkeypatch.setattr(io, "atomic_json", original)
    select, calls = silver.select_period, []

    def tracked(con, source, freq, period, **kwargs):
        calls.append(period)
        return select(con, source, freq, period, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    silver.build(f["lake"], f["staging"], run_id, emit=lambda _: None)
    assert calls == ["2020-04-03", "2026-10-16"]
    assert file_version(first) == version


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
