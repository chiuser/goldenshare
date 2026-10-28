"""Original failed executions keep their identity through manual native recovery.

The existing fixture supplies independently documented source literals, actual
Raw receipts/Parquet and an isolated Dagster instance. Only HTTP and a specific
durability interruption are replaced. No formal resource is used.
"""

import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import dagster as dg
import pytest
from dagster._core.errors import DagsterExecutionInterruptedError

from orchestrator.defs import duckdb_connection, paths
from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.asset_guards import stock_period_silver_readiness as readiness
from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.io import stock_period_silver as io
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.run_contracts.run_keys import build_repair_attempt_run_key
from orchestrator.defs.run_contracts.stock_period_silver import asset_name, raw_path
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_daily_integration import run_request, tick
from tests.test_stock_period_silver_jobs import definitions
from tests.test_stock_period_silver_sensor_recovery import event_count
from tests.test_stock_period_silver_sensors import context


def execute_request(f, request, monkeypatch):
    """Keep failed/canceled native execution results instead of reraising them."""
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    return (
        definitions(f["lake"])
        .resolve_job_def(request.job_name)
        .execute_in_process(
            instance=f["instance"],
            partition_key=request.partition_key,
            run_config=request.run_config,
            tags={"dagster/run_key": request.run_key},
            raise_on_error=False,
        )
    )


def interrupted_original(f, monkeypatch, freq, status):
    """The original job really renames a candidate, then cannot commit its CP.

    Dagster's installed execute_plan/API interrupt contract records CANCELED
    when a native run first receives report_run_canceling and then raises
    DagsterExecutionInterruptedError. FAILURE uses the same real IO boundary.
    Neither case fabricates a successful job followed by a failed run record.
    """
    ctx = context(f)
    f["capture"](freq=freq)
    request = tick(f, ctx, freq).run_requests[0]
    pending = json.loads(ctx.cursor)["pending"]
    work = io.run_directory(f["staging"], pending["execution_id"])
    source_versions = {
        str(raw_path(f["lake"], unit_freq, period)): file_version(
            raw_path(f["lake"], unit_freq, period)
        )
        for unit_freq, period in f["data"]
        if unit_freq == freq
    }
    saved, interrupted = io.atomic_json, []

    def fail_commit(path, value):
        if value.get("state") == "committed" and work in path.parents:
            interrupted.append(path)
            if status == dg.DagsterRunStatus.CANCELED:
                active = f["instance"].get_runs(
                    filters=dg.RunsFilter(
                        job_name=request.job_name,
                        statuses=[dg.DagsterRunStatus.STARTED],
                    ),
                    limit=2,
                )
                assert len(active) == 1
                f["instance"].report_run_canceling(
                    active[0], message="isolated cancellation after candidate rename"
                )
                raise DagsterExecutionInterruptedError()
            raise OSError("isolated checkpoint failure after candidate rename")
        return saved(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(io, "atomic_json", fail_commit)
        result = execute_request(f, request, fault)
    assert not result.success
    original_run = f["instance"].get_run_by_id(result.run_id)
    assert original_run.status == status
    execution = io.read_json(work / "execution.json")
    assert execution["identity"]["run_id"] == pending["execution_id"]
    assert "resume_from_execution_id" not in execution["identity"]
    first = execution["identity"]["units"][0]
    checkpoint = silver.checkpoint_path(work, first)
    assert interrupted == [checkpoint]
    record = io.read_json(checkpoint)
    assert not first["reuse"] and record["state"] == "validated"
    assert not Path(record["candidate"]).exists()
    assert io.identity_after_rename(file_version(first["target"])) == (
        io.identity_after_rename(record["candidate_version"])
    )
    assert not (work / "complete.json").exists()
    assert not (work / "events_complete.json").exists()
    assert all(
        file_version(path) == version for path, version in source_versions.items()
    )
    assert json.loads(ctx.cursor)["pending"] == pending
    return ctx, request, result.run_id, execution


def guard_market_content(monkeypatch):
    """Cover both the shared entry and io.recover_committed's local import."""

    def forbidden(*args, **kwargs):
        pytest.fail("sensor opened DuckDB or computed market data")

    monkeypatch.setattr(duckdb_connection, "connect_configured_duckdb", forbidden)
    monkeypatch.setattr(silver, "connect_configured_duckdb", forbidden)
    open_path = Path.open

    def open_metadata(path, *args, **kwargs):
        if path.suffix == ".parquet":
            pytest.fail("sensor opened Parquet content or footer")
        return open_path(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_metadata)
    monkeypatch.setattr(
        cli, "replay_events", lambda *a, **k: pytest.fail("sensor needed events CLI")
    )


def guard_waiting_side_effects(monkeypatch):
    guard_market_content(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("unfinished sensor recovered files, wrote CPs or queried readiness")

    for name in (
        "recover_update_execution",
        "owned_update_records",
        "recover_committed",
        "reused_update_record",
        "atomic_json",
    ):
        monkeypatch.setattr(silver, name, forbidden)
    monkeypatch.setattr(io, "recover_committed", forbidden)
    monkeypatch.setattr(io, "atomic_json", forbidden)
    monkeypatch.setattr(readiness, "batch_event_evidence", forbidden)


def hint_request(message, original, execution_id):
    """Use the existing job/config from the hint with the standard repair key."""
    asset = original.job_name.removesuffix("_update_job")
    assert f";job={original.job_name};partition={original.partition_key};" in message
    config = json.loads(message.split(";run_config=", 1)[1])
    assert config == original.run_config
    assert config["ops"][asset]["config"]["execution_id"] == execution_id
    assert "resume_from_execution_id" not in config["ops"][asset]["config"]
    return dg.RunRequest(
        run_key=build_repair_attempt_run_key(
            subject=asset, repair_scope_id=execution_id, attempt=1
        ),
        job_name=original.job_name,
        partition_key=original.partition_key,
        run_config=config,
    )


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize(
    "status", [dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED]
)
def test_failed_original_waits_without_recovering_renamed_checkpoint(
    update_fixture, monkeypatch, freq, status
):
    """Regression A: unchanged Raw and an incomplete original are read-only."""
    f = update_fixture
    ctx, original, original_run_id, execution = interrupted_original(
        f, monkeypatch, freq, status
    )
    identity = execution["identity"]
    work = io.run_directory(f["staging"], identity["run_id"])
    checkpoint = silver.checkpoint_path(work, identity["units"][0])
    before = {path: path.read_bytes() for path in work.rglob("*.json")}
    versions = {
        unit[key]: file_version(unit[key])
        for unit in identity["units"]
        for key in ("source", "target")
    }
    pending = json.loads(ctx.cursor)["pending"]
    before_events, source_calls = event_count(f["instance"]), len(f["source_calls"])
    read, reads = silver.read_json, Counter()

    def counted(path):
        reads[str(path)] += 1
        return read(path)

    monkeypatch.setattr(silver, "read_json", counted)
    guard_waiting_side_effects(monkeypatch)
    for _ in range(2):
        reads.clear()
        result = tick(f, ctx, freq)
        assert not result.run_requests
        message = result.skip_reason.skip_message
        assert message.startswith("silver_run_requires_review:" + original_run_id)
        assert ";resume_execution_id=" + identity["run_id"] in message
        assert "silver_recovery_required:" + identity["run_id"] in message
        assert "files_committed=0/3;files_complete=false" in message
        hint_request(message, original, identity["run_id"])
        assert json.loads(ctx.cursor)["pending"] == pending
        assert reads[str(checkpoint)] == 1
        assert reads[str(work / "execution.json")] == 1
        assert {path: path.read_bytes() for path in work.rglob("*.json")} == before
        assert all(file_version(path) == version for path, version in versions.items())
        assert f["instance"].get_run_by_id(original_run_id).status == status
    assert event_count(f["instance"]) == before_events
    assert len(f["source_calls"]) == source_calls
    assert not (work / "complete.json").exists()
    assert not (work / "events_complete.json").exists()


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize(
    "status", [dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED]
)
def test_manual_same_execution_job_confirms_despite_original_failed_run(
    update_fixture, monkeypatch, freq, status
):
    """Regression B reaches native repair success before testing the old blocker.

    The preparation tick intentionally has no regression-A guard: the previous
    implementation must reach this test's independent completion assertion.
    """
    f = update_fixture
    ctx, original, original_run_id, execution = interrupted_original(
        f, monkeypatch, freq, status
    )
    identity = execution["identity"]
    work = io.run_directory(f["staging"], identity["run_id"])
    frozen = (work / "execution.json").read_bytes()
    pending = json.loads(ctx.cursor)["pending"]
    guidance = tick(f, ctx, freq)
    assert not guidance.run_requests
    repair = hint_request(
        guidance.skip_reason.skip_message, original, identity["run_id"]
    )
    assert repair.run_key != original.run_key
    assert repair.tags == {}
    assert json.loads(ctx.cursor)["pending"] == pending
    repaired = run_request(f, repair, monkeypatch)
    assert repaired.success
    assert (
        f["instance"].get_run_by_id(repaired.run_id).status
        == dg.DagsterRunStatus.SUCCESS
    )
    assert f["instance"].get_run_by_id(original_run_id).status == status
    assert (work / "execution.json").read_bytes() == frozen
    assert io.read_json(work / "complete.json")["totals"][freq] == {
        "files": 3,
        "rows": 6,
    }
    assert not (work / "events_complete.json").exists()
    target_versions = {
        unit["target"]: file_version(unit["target"]) for unit in identity["units"]
    }
    source_versions = {
        unit["source"]: file_version(unit["source"]) for unit in identity["units"]
    }
    before_events, source_calls = event_count(f["instance"]), len(f["source_calls"])
    counts = {"runs": 0, "observations": 0, "readiness_batches": 0}
    get_runs = f["instance"].get_runs
    observations = f["instance"].fetch_observations
    batch = readiness.batch_event_evidence

    def counted_runs(*args, **kwargs):
        counts["runs"] += 1
        return get_runs(*args, **kwargs)

    def counted_observations(*args, **kwargs):
        counts["observations"] += 1
        return observations(*args, **kwargs)

    def counted_batch(*args, **kwargs):
        counts["readiness_batches"] += 1
        return batch(*args, **kwargs)

    monkeypatch.setattr(f["instance"], "get_runs", counted_runs)
    monkeypatch.setattr(f["instance"], "fetch_observations", counted_observations)
    monkeypatch.setattr(readiness, "batch_event_evidence", counted_batch)
    guard_market_content(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message == "silver_batch_complete"
    assert counts == {"runs": 2, "observations": 0, "readiness_batches": 1}
    closed = json.loads(ctx.cursor)
    assert "pending" not in closed and closed["after"] == pending["observation_id"]
    receipt = io.read_json(work / "events_complete.json")
    assert receipt == {
        "run_id": identity["run_id"],
        "identity_hash": execution["identity_hash"],
        "files": 3,
        "checks": 9,
        "status": "complete",
    }
    assert event_count(f["instance"]) == before_events
    assert len(f["source_calls"]) == source_calls
    assert all(
        file_version(path) == version for path, version in target_versions.items()
    )
    assert all(
        file_version(path) == version for path, version in source_versions.items()
    )
    assert f["instance"].get_run_by_id(original_run_id).status == status
    assert (work / "execution.json").read_bytes() == frozen


def interrupted_original_stage(f, monkeypatch, freq, stage):
    """Stop the actual original before publish, first reuse CP or final summary."""
    # The bootstrap notice is an actual unconsumed original delivery. Its files
    # already have native baseline checks, so the update legitimately reuses
    # three periods without inventing identity flags or CP contents.
    ctx = context(f, after=0) if stage == "reuse" else context(f)
    if stage != "reuse":
        f["capture"](freq=freq)
    request = tick(f, ctx, freq).run_requests[0]
    pending = json.loads(ctx.cursor)["pending"]
    work = io.run_directory(f["staging"], pending["execution_id"])
    save, publish, faults = silver.atomic_json, silver.publish, []

    def stop_save(path, value):
        if work in path.parents and (
            stage == "reuse"
            and value.get("state") == "committed"
            or stage == "summary"
            and path == work / "complete.json"
        ):
            faults.append(path)
            raise OSError("isolated original " + stage + " interruption")
        return save(path, value)

    def stop_publish(record, checkpoint, **kwargs):
        if stage == "candidate":
            faults.append(checkpoint)
            raise OSError("isolated original candidate interruption")
        return publish(record, checkpoint, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(silver, "atomic_json", stop_save)
        fault.setattr(silver, "publish", stop_publish)
        result = execute_request(f, request, fault)
    assert not result.success
    assert (
        f["instance"].get_run_by_id(result.run_id).status == dg.DagsterRunStatus.FAILURE
    )
    assert len(faults) == 1
    execution = io.read_json(work / "execution.json")
    assert execution["identity"]["run_id"] == pending["execution_id"]
    assert "resume_from_execution_id" not in execution["identity"]
    checkpoints = list((work / "files").rglob("*.json"))
    if stage == "reuse":
        assert all(unit["reuse"] for unit in execution["identity"]["units"])
        assert not checkpoints
    elif stage == "candidate":
        assert len(checkpoints) == 1
        record = io.read_json(checkpoints[0])
        assert record["state"] == "validated" and Path(record["candidate"]).exists()
    else:
        assert len(checkpoints) == 3
        assert all(io.read_json(path)["state"] == "committed" for path in checkpoints)
    assert not (work / "complete.json").exists()
    assert not (work / "events_complete.json").exists()
    assert all(
        file_version(unit["source"]) == unit["source_version"]
        for unit in execution["identity"]["units"]
    )
    return ctx, request, result.run_id, execution


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize(
    "stage,committed", [("candidate", 0), ("reuse", 0), ("summary", 3)]
)
def test_original_waiting_boundaries_are_read_only_and_native_job_can_continue(
    update_fixture, monkeypatch, freq, stage, committed
):
    f = update_fixture
    ctx, original, original_run_id, execution = interrupted_original_stage(
        f, monkeypatch, freq, stage
    )
    identity = execution["identity"]
    work = io.run_directory(f["staging"], identity["run_id"])
    checkpoints = list((work / "files").rglob("*.json"))
    before = {path: path.read_bytes() for path in work.rglob("*.json")}
    versions = {
        unit[key]: file_version(unit[key])
        for unit in identity["units"]
        for key in ("source", "target")
    }
    pending = json.loads(ctx.cursor)["pending"]
    events, source_calls = event_count(f["instance"]), len(f["source_calls"])
    read, reads = silver.read_json, Counter()

    def counted(path):
        reads[str(path)] += 1
        return read(path)

    with monkeypatch.context() as guard:
        guard.setattr(silver, "read_json", counted)
        guard_waiting_side_effects(guard)
        for _ in range(2):
            reads.clear()
            result = tick(f, ctx, freq)
            assert not result.run_requests
            message = result.skip_reason.skip_message
            assert message.startswith("silver_run_requires_review:" + original_run_id)
            assert f"files_committed={committed}/3;files_complete=false" in message
            hint_request(message, original, identity["run_id"])
            assert json.loads(ctx.cursor)["pending"] == pending
            assert all(reads[str(path)] == 1 for path in checkpoints)
            assert reads[str(work / "execution.json")] == 1
            assert {path: path.read_bytes() for path in work.rglob("*.json")} == before
            assert all(
                file_version(path) == version for path, version in versions.items()
            )
    assert event_count(f["instance"]) == events
    assert len(f["source_calls"]) == source_calls
    # Only the requested native job is now allowed to finish the interrupted IO.
    assert run_request(
        f, hint_request(message, original, identity["run_id"]), monkeypatch
    ).success
    with monkeypatch.context() as guard:
        guard_market_content(guard)
        assert tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
    assert "pending" not in json.loads(ctx.cursor)
    assert (
        f["instance"].get_run_by_id(original_run_id).status
        == dg.DagsterRunStatus.FAILURE
    )


def completed_original(f, monkeypatch, freq):
    ctx, original, original_run_id, execution = interrupted_original(
        f, monkeypatch, freq, dg.DagsterRunStatus.FAILURE
    )
    guidance = tick(f, ctx, freq)
    repair = hint_request(
        guidance.skip_reason.skip_message, original, execution["identity"]["run_id"]
    )
    assert run_request(f, repair, monkeypatch).success
    assert (
        f["instance"].get_run_by_id(original_run_id).status
        == dg.DagsterRunStatus.FAILURE
    )
    return ctx, original_run_id, execution


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("fault", ["missing", "failed", "wrong_binding"])
def test_completed_original_requires_actual_bound_checks(
    update_fixture, monkeypatch, freq, fault
):
    """Missing shortens the consumer response; other faults are real bad events.

    The native repair really produced all checks. The missing case tests the
    response contract and does not claim to reproduce event-store data loss.
    """
    from orchestrator.defs.run_contracts.stock_period_silver import check_names
    from tests.test_stock_period_silver_events import emit_test_check

    f = update_fixture
    ctx, original_run_id, execution = completed_original(f, monkeypatch, freq)
    identity = execution["identity"]
    work = io.run_directory(f["staging"], identity["run_id"])
    anchor = identity["units"][-1]["period"]
    batch, queries = readiness.batch_event_evidence, []

    def evidence(*args, **kwargs):
        # The real decoder can reject wrong binding before returning. Count the
        # call attempt so that rejection does not conceal the executed query.
        queries.append(tuple(args[2]))
        result = batch(*args, **kwargs)
        if fault == "missing":
            current = result[(asset_name(freq), anchor)]
            assert set(current["checks"]) == set(check_names(freq))
            current["checks"].pop(check_names(freq)[0])
        return result

    if fault != "missing":
        bound_period = (
            identity["units"][0]["period"] if fault == "wrong_binding" else anchor
        )
        materialization = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset_name(freq)),
                    asset_partitions=[bound_period],
                ),
                limit=1,
            )
            .records[0]
        )
        emit_test_check(
            f["instance"],
            asset_name(freq),
            anchor,
            check_names(freq)[0],
            materialization,
            passed=fault != "failed",
        )
    pending = json.loads(ctx.cursor)["pending"]
    before_events = event_count(f["instance"])
    before = {path: path.read_bytes() for path in work.rglob("*.json")}
    monkeypatch.setattr(readiness, "batch_event_evidence", evidence)
    guard_market_content(monkeypatch)
    monkeypatch.setattr(
        silver,
        "atomic_json",
        lambda *a, **k: pytest.fail("bad checks wrote completion"),
    )
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith("silver_target_checks_not_ready")
    assert "files_committed=3/3;files_complete=true" in result.skip_reason.skip_message
    assert json.loads(ctx.cursor)["pending"] == pending
    assert queries == [tuple(unit["period"] for unit in identity["units"])]
    assert event_count(f["instance"]) == before_events
    assert {path: path.read_bytes() for path in work.rglob("*.json")} == before
    assert not (work / "events_complete.json").exists()
    assert (
        f["instance"].get_run_by_id(original_run_id).status
        == dg.DagsterRunStatus.FAILURE
    )


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("run_id", "silver_completion_identity_changed"),
        ("totals", "silver_completion_totals_invalid"),
    ],
)
def test_completed_original_rejects_corrupt_summary_before_readiness(
    update_fixture, monkeypatch, fault, expected
):
    f = update_fixture
    ctx, _, execution = completed_original(f, monkeypatch, "week")
    work = io.run_directory(f["staging"], execution["identity"]["run_id"])
    path = work / "complete.json"
    summary = io.read_json(path)
    if fault == "run_id":
        summary["run_id"] = str(uuid4())
    else:
        summary["totals"]["week"]["rows"] += 1
    path.write_text(json.dumps(summary))
    pending = json.loads(ctx.cursor)["pending"]
    before_events = event_count(f["instance"])
    guard_market_content(monkeypatch)
    monkeypatch.setattr(
        readiness,
        "batch_event_evidence",
        lambda *a, **k: pytest.fail("bad summary queried checks"),
    )
    result = tick(f, ctx, "week")
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith(expected)
    assert json.loads(ctx.cursor)["pending"] == pending
    assert event_count(f["instance"]) == before_events
    assert not (work / "events_complete.json").exists()


def test_original_confirmation_receipt_failure_retries_without_computation(
    update_fixture, monkeypatch
):
    f = update_fixture
    ctx, original_run_id, execution = completed_original(f, monkeypatch, "week")
    identity = execution["identity"]
    work = io.run_directory(f["staging"], identity["run_id"])
    pending = json.loads(ctx.cursor)["pending"]
    before_events, source_calls = event_count(f["instance"]), len(f["source_calls"])
    versions = {
        unit["target"]: file_version(unit["target"]) for unit in identity["units"]
    }
    save, read, batch = (
        silver.atomic_json,
        silver.read_json,
        readiness.batch_event_evidence,
    )
    reads, queries = Counter(), []

    def counted(path):
        reads[str(path)] += 1
        return read(path)

    def queried(*args, **kwargs):
        queries.append(tuple(args[2]))
        return batch(*args, **kwargs)

    def fail_receipt(path, value):
        if path == work / "events_complete.json":
            raise OSError("isolated completion receipt save failure")
        return save(path, value)

    guard_market_content(monkeypatch)
    monkeypatch.setattr(silver, "read_json", counted)
    monkeypatch.setattr(readiness, "batch_event_evidence", queried)
    for retry in (False, True):
        reads.clear()
        queries.clear()
        with monkeypatch.context() as fault:
            if not retry:
                fault.setattr(silver, "atomic_json", fail_receipt)
            result = tick(f, ctx, "week")
        assert not result.run_requests
        if retry:
            assert result.skip_reason.skip_message == "silver_batch_complete"
            assert "pending" not in json.loads(ctx.cursor)
        else:
            assert result.skip_reason.skip_message.startswith(
                "isolated completion receipt save failure"
            )
            assert json.loads(ctx.cursor)["pending"] == pending
        assert queries == [tuple(unit["period"] for unit in identity["units"])]
        assert reads[str(work / "complete.json")] == 1
        assert all(
            reads[str(silver.checkpoint_path(work, unit))] == 1
            for unit in identity["units"]
        )
    assert event_count(f["instance"]) == before_events
    assert len(f["source_calls"]) == source_calls
    assert all(file_version(path) == version for path, version in versions.items())
    assert (
        f["instance"].get_run_by_id(original_run_id).status
        == dg.DagsterRunStatus.FAILURE
    )


def test_original_job_failure_before_execution_freeze_keeps_review(
    update_fixture, monkeypatch
):
    f = update_fixture
    ctx = context(f)
    f["capture"]()
    request = tick(f, ctx, "week").run_requests[0]
    pending = json.loads(ctx.cursor)["pending"]

    def fail_freeze(*args, **kwargs):
        raise OSError("isolated execution freeze failure")

    with monkeypatch.context() as fault:
        fault.setattr(silver, "make_update_execution", fail_freeze)
        failed = execute_request(f, request, fault)
    assert not failed.success
    assert (
        f["instance"].get_run_by_id(failed.run_id).status == dg.DagsterRunStatus.FAILURE
    )
    work = io.run_directory(f["staging"], pending["execution_id"])
    assert not (work / "execution.json").exists()
    guard_market_content(monkeypatch)
    monkeypatch.setattr(
        readiness,
        "batch_event_evidence",
        lambda *a, **k: pytest.fail("no execution queried checks"),
    )
    result = tick(f, ctx, "week")
    assert not result.run_requests
    # The pre-change failed-original branch already included the explicit ID
    # even when execution.json was absent; preserve that complete existing hint.
    assert result.skip_reason.skip_message == (
        "silver_run_requires_review:"
        + failed.run_id
        + ";resume_execution_id="
        + pending["execution_id"]
    )
    assert json.loads(ctx.cursor)["pending"] == pending
    assert not (work / "execution.json").exists()
