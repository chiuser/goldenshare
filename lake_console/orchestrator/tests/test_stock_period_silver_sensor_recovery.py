"""Recovery sensor regression using real temporary producer and job outputs.

Contracts and independent source literals are supplied by update_fixture. Only
HTTP is replaced there; these tests use real files, native checks and an isolated
Dagster event store. No formal Lake, instance or source is accessed.
"""

import json

import dagster as dg
import pytest
import sqlalchemy as sa
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.io.stock_period_silver import read_json, run_directory
from orchestrator.defs.run_contracts.run_keys import build_repair_attempt_run_key
from orchestrator.defs.run_contracts.stock_period_silver import asset_name
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_daily_integration import run_request, tick
from tests.test_stock_period_silver_execution import refresh_recovery_tail
from tests.test_stock_period_silver_sensors import context


def event_count(instance):
    with instance.event_log_storage.index_connection() as connection:
        return connection.execute(
            sa.select(sa.func.count()).select_from(Events)
        ).scalar_one()


def frozen_recovery(f, monkeypatch, freq):
    """Actual successful parent, then a genuinely published new Raw tail file."""
    ctx = context(f)
    reference = f["capture"](freq=freq)
    request = tick(f, ctx, freq).run_requests[0]
    result = run_request(f, request, monkeypatch)
    assert result.success
    assert (
        f["instance"].get_run_by_id(result.run_id).status == dg.DagsterRunStatus.SUCCESS
    )
    parent_id = request.run_config["ops"][asset_name(freq)]["config"]["execution_id"]
    parent_work = run_directory(f["staging"], parent_id)
    assert (parent_work / "complete.json").exists()
    assert not (parent_work / "events_complete.json").exists()
    refresh_recovery_tail(f, freq)
    first = tick(f, ctx, freq)
    assert not first.run_requests
    assert first.skip_reason.skip_message.startswith("silver_recovery_required:")
    child_id = json.loads(ctx.cursor)["pending"]["execution_id"]
    assert child_id != parent_id
    child_work = run_directory(f["staging"], child_id)
    child = read_json(child_work / "execution.json")
    assert child["identity"]["resume_from_execution_id"] == parent_id
    assert child["identity"]["source_completion"] == reference
    assert len(child["identity"]["units"]) == 3
    assert sum(unit["reuse"] for unit in child["identity"]["units"]) == 2
    assert not (child_work / "files").exists()
    return ctx, request, parent_id, child


def recovery_request(child, *, attempt=1):
    identity = child["identity"]
    freq = identity["units"][0]["freq"]
    asset = asset_name(freq)
    return dg.RunRequest(
        run_key=build_repair_attempt_run_key(
            subject=asset, repair_scope_id=identity["run_id"], attempt=attempt
        ),
        job_name=asset + "_update_job",
        partition_key=identity["units"][-1]["period"],
        run_config={
            "ops": {
                asset: {
                    "config": {
                        "intent": "update",
                        "execution_id": identity["run_id"],
                        "resume_from_execution_id": identity[
                            "resume_from_execution_id"
                        ],
                        "source_completion": identity["source_completion"],
                    }
                }
            }
        },
    )


def guard_sensor_computation(monkeypatch):
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("sensor read or computed market data"),
    )


def stop_recovery(f, child, monkeypatch, stage):
    """Inject one interruption into the real builder, not its records or results."""
    identity = child["identity"]
    original, committed = silver.publish, []
    atomic, persisted = silver.atomic_json, []
    work = run_directory(f["staging"], identity["run_id"])

    def saved(path, record):
        result = atomic(path, record)
        if (
            stage == "partial"
            and path.parent == work / "files" / identity["units"][0]["freq"]
            and record.get("state") == "committed"
        ):
            persisted.append(path)
        return result

    def publish(record, *args, **kwargs):
        if stage == "validated" and record["period"] == identity["units"][-1]["period"]:
            raise silver.SilverCancelled("injected before final rename")
        saved = original(record, *args, **kwargs)
        committed.append(saved)
        return saved

    with monkeypatch.context() as fault:
        fault.setattr(silver, "publish", publish)
        fault.setattr(silver, "atomic_json", saved)
        with pytest.raises(silver.SilverCancelled):
            silver.build(
                f["lake"],
                f["staging"],
                identity["run_id"],
                freq=identity["units"][0]["freq"],
                source_completion=identity["source_completion"],
                resume_from_execution_id=identity["resume_from_execution_id"],
                instance=f["instance"],
                # recover_update_execution -> owned_update_records creates reuse
                # CPs before the publish loop. The old test's publish count did
                # not represent persisted work. Cancel on the real first CP save.
                cancel=lambda: stage == "partial" and len(persisted) == 1,
                emit=lambda _: None,
            )
    if stage == "partial":
        first = silver.checkpoint_path(work, identity["units"][0])
        assert persisted == [first]
        assert read_json(first)["state"] == "committed"
        assert all(
            not silver.checkpoint_path(work, unit).exists()
            for unit in identity["units"][1:]
        )
        assert not (work / "complete.json").exists()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_frozen_child_without_execution_keeps_recovery_guidance_across_ticks(
    update_fixture, monkeypatch, freq
):
    f = update_fixture
    ctx, _, parent_id, child = frozen_recovery(f, monkeypatch, freq)
    child_id = child["identity"]["run_id"]
    work = run_directory(f["staging"], child_id)
    frozen = (work / "execution.json").read_bytes()
    pending = json.loads(ctx.cursor)["pending"]
    before_events, before_calls = event_count(f["instance"]), len(f["source_calls"])
    versions = {
        unit["target"]: file_version(unit["target"])
        for unit in child["identity"]["units"]
    }
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("sensor read or computed market data"),
    )
    for _ in range(2):
        result = tick(f, ctx, freq)
        assert not result.run_requests
        message = result.skip_reason.skip_message
        assert message.startswith("silver_recovery_required:" + child_id)
        assert "files_committed=0/3" in message
        assert "files_complete=false" in message
        assert f"job={asset_name(freq)}_update_job" in message
        config = json.loads(message.split(";run_config=", 1)[1])
        assert config == {
            "ops": {
                asset_name(freq): {
                    "config": {
                        "intent": "update",
                        "execution_id": child_id,
                        "resume_from_execution_id": parent_id,
                        "source_completion": child["identity"]["source_completion"],
                    }
                }
            }
        }
        assert json.loads(ctx.cursor)["pending"] == pending
        assert not (work / "files").exists()
        assert not (work / "complete.json").exists()
        assert not (work / "events_complete.json").exists()
        assert (work / "execution.json").read_bytes() == frozen
    assert event_count(f["instance"]) == before_events
    assert len(f["source_calls"]) == before_calls
    assert all(file_version(path) == version for path, version in versions.items())


@pytest.mark.parametrize("freq", ["week", "month"])
def test_failed_original_first_recovery_message_has_successor_and_parent_config(
    update_fixture, monkeypatch, freq
):
    from tests.test_stock_period_silver_jobs import definitions

    f = update_fixture
    ctx = context(f)
    f["capture"](freq=freq)
    request = tick(f, ctx, freq).run_requests[0]
    assert run_request(f, request, monkeypatch).success
    parent_id = request.run_config["ops"][asset_name(freq)]["config"]["execution_id"]
    failed = f["instance"].create_run_for_job(
        definitions(f["lake"]).resolve_job_def(request.job_name),
        run_config=request.run_config,
        status=dg.DagsterRunStatus.FAILURE,
        tags={"dagster/run_key": request.run_key},
    )
    refresh_recovery_tail(f, freq)
    first = tick(f, ctx, freq)
    assert not first.run_requests
    message = first.skip_reason.skip_message
    assert message.startswith("silver_run_requires_review:" + failed.run_id)
    child_id = json.loads(ctx.cursor)["pending"]["execution_id"]
    assert child_id != parent_id
    config = json.loads(message.split(";run_config=", 1)[1])
    assert config["ops"][asset_name(freq)]["config"]["execution_id"] == child_id
    assert (
        config["ops"][asset_name(freq)]["config"]["resume_from_execution_id"]
        == parent_id
    )
    child = read_json(run_directory(f["staging"], child_id) / "execution.json")
    assert tick(f, ctx, freq).skip_reason.skip_message.startswith(
        "silver_recovery_required:" + child_id
    )
    assert run_request(f, recovery_request(child), monkeypatch).success
    guard_sensor_computation(monkeypatch)
    assert tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
    assert "pending" not in json.loads(ctx.cursor)


@pytest.mark.parametrize("freq,size", [("week", 658), ("month", 154)])
def test_full_period_metadata_progress_reads_once_per_tick_without_market_open(
    update_fixture, monkeypatch, freq, size
):
    """Capacity only: real producer JSON shapes, synthetic units and stat targets.

    The tiny target bytes deliberately are not valid Parquet. This test proves
    only control-record access counts, cache boundaries and zero content reads;
    the other tests exercise actual producer Parquet and native job/checks.
    """
    from collections import Counter
    from copy import deepcopy
    from datetime import date, timedelta
    from pathlib import Path
    from uuid import uuid4

    from orchestrator.defs.run_contracts.stock_period_silver import (
        raw_path,
        target_path,
    )

    f = update_fixture
    _, _, parent_id, _ = frozen_recovery(f, monkeypatch, freq)
    parent_work = run_directory(f["staging"], parent_id)
    producer = read_json(parent_work / "execution.json")
    template_unit = producer["identity"]["units"][0]
    template_record = read_json(silver.checkpoint_path(parent_work, template_unit))
    template_summary = read_json(parent_work / "complete.json")
    assert template_record["state"] == "committed"
    assert set(template_summary["totals"]) == {"week", "month"}
    assert all(
        set(value) == {"files", "rows"} for value in template_summary["totals"].values()
    )
    assert template_record["checks"] == {
        "file_contract": True,
        "key_partition": True,
        "source_projection": True,
    }
    identity = deepcopy(producer["identity"])
    identity["run_id"] = str(uuid4())
    identity["units"] = []
    work = run_directory(f["staging"], identity["run_id"])
    keys = (
        [(date(2014, 1, 3) + timedelta(weeks=i)).isoformat() for i in range(size)]
        if freq == "week"
        else [f"{2014 + i // 12:04d}-{1 + i % 12:02d}" for i in range(size)]
    )
    versions = {}
    for key in keys:
        unit = deepcopy(template_unit)
        unit.update(
            freq=freq,
            period=key,
            source=str(raw_path(f["lake"], freq, key)),
            target=str(target_path(f["lake"], freq, key)),
            reuse=False,
        )
        assert not unit.get("inherited_from") and not unit.get("preimage_from")
        target = Path(unit["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"stat")
        versions[key] = file_version(target)
        identity["units"].append(unit)
    execution = {"identity": identity, "identity_hash": silver.fingerprint(identity)}
    silver.atomic_json(work / "execution.json", execution)
    for unit in identity["units"]:
        record = deepcopy(template_record)
        record.update(
            **unit,
            identity_hash=execution["identity_hash"],
            rows=1,
            candidate=str(
                work / "candidates" / freq / unit["period"] / "part-000.parquet"
            ),
            version=versions[unit["period"]],
            candidate_version=versions[unit["period"]],
        )
        # Populate hashes as producer input only; metric expectations below are
        # independent literals and never generated by the helper under test.
        record["validation_hash"] = silver.checkpoint_validation_hash(record)
        silver.atomic_json(silver.checkpoint_path(work, unit), record)
    summary = deepcopy(template_summary)
    summary.update(
        run_id=identity["run_id"],
        totals={
            f: {"files": size if f == freq else 0, "rows": size if f == freq else 0}
            for f in ("week", "month")
        },
    )
    silver.atomic_json(work / "complete.json", summary)
    reads, read, open_path = Counter(), silver.read_json, Path.open

    def counted(path):
        reads[str(path)] += 1
        return read(path)

    def guarded_open(path, *args, **kwargs):
        if path.suffix == ".parquet":
            pytest.fail("metadata progress opened market file content")
        return open_path(path, *args, **kwargs)

    monkeypatch.setattr(silver, "read_json", counted)
    monkeypatch.setattr(Path, "open", guarded_open)
    guard_sensor_computation(monkeypatch)
    expected = {"files": size, "committed": size, "files_complete": True}
    paths = [str(silver.checkpoint_path(work, unit)) for unit in identity["units"]]
    paths.append(str(work / "complete.json"))
    with silver.recovery_evidence():
        assert silver.update_delivery_progress(f["staging"], execution) == expected
        assert silver.update_delivery_progress(f["staging"], execution) == expected
    assert set(reads) == set(paths)
    assert all(reads[path] == 1 for path in paths)
    with silver.recovery_evidence():
        assert silver.update_delivery_progress(f["staging"], execution) == expected
    assert all(reads[path] == 2 for path in paths)


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize(
    "fault,expected",
    [
        ("run_id", "silver_completion_identity_changed"),
        ("files", "silver_completion_totals_invalid"),
        ("rows", "silver_completion_totals_invalid"),
        ("boolean", "silver_completion_totals_invalid"),
        ("other_frequency", "silver_completion_totals_invalid"),
        ("missing_checkpoint", "silver_completion_checkpoint_missing"),
        ("uncommitted", "silver_completion_checkpoint_uncommitted"),
        ("json_list", "silver_completion_invalid"),
        ("invalid_json", "silver_completion_invalid"),
    ],
)
def test_claimed_file_completion_requires_intact_actual_summary_and_checkpoints(
    update_fixture, monkeypatch, freq, fault, expected
):
    from uuid import uuid4

    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    assert run_request(f, recovery_request(child), monkeypatch).success
    work = run_directory(f["staging"], child["identity"]["run_id"])
    path = work / "complete.json"
    summary = read_json(path)
    assert set(summary["totals"]) == {"week", "month"}
    assert "identity_hash" not in summary and "status" not in summary
    if fault == "run_id":
        summary["run_id"] = str(uuid4())
    elif fault in ("files", "rows"):
        summary["totals"][freq][fault] += 1
    elif fault == "boolean":
        summary["totals"][freq]["files"] = True
    elif fault == "other_frequency":
        summary["totals"]["month" if freq == "week" else "week"]["files"] = 1
    elif fault == "missing_checkpoint":
        silver.checkpoint_path(work, child["identity"]["units"][0]).unlink()
    elif fault == "uncommitted":
        cp = silver.checkpoint_path(work, child["identity"]["units"][-1])
        record = read_json(cp)
        assert not record["reuse"]
        record["state"] = "validated"
        cp.write_text(json.dumps(record))
    if fault == "json_list":
        path.write_text("[]")
    elif fault == "invalid_json":
        path.write_text("{invalid")
    else:
        path.write_text(json.dumps(summary))
    pending = json.loads(ctx.cursor)["pending"]
    before_events = event_count(f["instance"])
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith(expected)
    assert json.loads(ctx.cursor)["pending"] == pending
    assert not (work / "events_complete.json").exists()
    assert event_count(f["instance"]) == before_events


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("fault", ["bad_later_checkpoint", "target", "reference"])
def test_unfinished_execution_does_not_hide_existing_corruption(
    update_fixture, monkeypatch, freq, fault
):
    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    stop_recovery(f, child, monkeypatch, "validated")
    work = run_directory(f["staging"], child["identity"]["run_id"])
    if fault == "bad_later_checkpoint":
        silver.checkpoint_path(work, child["identity"]["units"][0]).unlink()
        cp = silver.checkpoint_path(work, child["identity"]["units"][1])
        record = read_json(cp)
        record["identity_hash"] = "0" * 64
        cp.write_text(json.dumps(record))
        expected = "silver_checkpoint_identity_invalid"
    elif fault == "target":
        from pathlib import Path

        Path(child["identity"]["units"][0]["target"]).write_bytes(b"bad target")
        expected = "silver_event_file_changed"
    else:
        from pathlib import Path

        Path(child["identity"]["references"]["lifecycle"]).write_bytes(b"bad reference")
        expected = "silver_event_reference_changed"
    pending = json.loads(ctx.cursor)["pending"]
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith(expected)
    assert json.loads(ctx.cursor)["pending"] == pending
    assert not (work / "events_complete.json").exists()


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("fault", ["failed", "wrong_binding"])
def test_completed_recovery_keeps_real_check_failure_or_binding_error(
    update_fixture, monkeypatch, freq, fault
):
    from orchestrator.defs.run_contracts.stock_period_silver import check_names
    from tests.test_stock_period_silver_events import emit_test_check

    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    assert run_request(f, recovery_request(child), monkeypatch).success
    units = child["identity"]["units"]
    period = units[-1]["period"]
    materialization_period = units[0]["period"] if fault == "wrong_binding" else period
    mat = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset_name(freq)),
                asset_partitions=[materialization_period],
            ),
            limit=1,
        )
        .records[0]
    )
    emit_test_check(
        f["instance"],
        asset_name(freq),
        period,
        check_names(freq)[0],
        mat,
        passed=fault != "failed",
    )
    before_events = event_count(f["instance"])
    pending = json.loads(ctx.cursor)["pending"]
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith("silver_target_checks_not_ready")
    assert "files_complete=true" in result.skip_reason.skip_message
    assert json.loads(ctx.cursor)["pending"] == pending
    assert event_count(f["instance"]) == before_events
    assert not (
        run_directory(f["staging"], child["identity"]["run_id"])
        / "events_complete.json"
    ).exists()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_source_changes_again_preserve_original_notification_and_successor_chain(
    update_fixture, monkeypatch, freq
):
    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    original_pending = json.loads(ctx.cursor)["pending"]
    old_path = (
        run_directory(f["staging"], child["identity"]["run_id"]) / "execution.json"
    )
    old_bytes = old_path.read_bytes()
    # The actual producer publishes a third Raw version with a new receipt.
    refresh_recovery_tail(f, freq)
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    pending = json.loads(ctx.cursor)["pending"]
    assert pending["observation_id"] == original_pending["observation_id"]
    assert pending["completion"] == original_pending["completion"]
    assert pending["execution_id"] != child["identity"]["run_id"]
    successor = read_json(
        run_directory(f["staging"], pending["execution_id"]) / "execution.json"
    )
    assert (
        successor["identity"]["resume_from_execution_id"] == child["identity"]["run_id"]
    )
    assert [(u["freq"], u["period"]) for u in successor["identity"]["units"]] == [
        (u["freq"], u["period"]) for u in child["identity"]["units"]
    ]
    assert old_path.read_bytes() == old_bytes
    assert result.skip_reason.skip_message.startswith(
        "silver_recovery_required:" + pending["execution_id"]
    )


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize(
    "stage,committed", [("partial", 1), ("validated", 2), ("summary", 3)]
)
def test_unfinished_recovery_keeps_progress_and_never_confirms(
    update_fixture, monkeypatch, freq, stage, committed
):
    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    work = run_directory(f["staging"], child["identity"]["run_id"])
    if stage == "summary":
        assert run_request(f, recovery_request(child), monkeypatch).success
        # Deliberate interruption boundary: all CPs survived, final summary did not.
        (work / "complete.json").unlink()
    else:
        stop_recovery(f, child, monkeypatch, stage)
    before = {str(path): path.read_bytes() for path in (work / "files").rglob("*.json")}
    pending = json.loads(ctx.cursor)["pending"]
    before_events = event_count(f["instance"])
    guard_sensor_computation(monkeypatch)
    monkeypatch.setattr(
        silver,
        "confirm_update_delivery",
        lambda *a, **k: pytest.fail("premature confirm"),
    )
    for _ in range(2):
        result = tick(f, ctx, freq)
        assert not result.run_requests
        message = result.skip_reason.skip_message
        assert message.startswith(
            "silver_recovery_required:" + child["identity"]["run_id"]
        )
        assert f"files_committed={committed}/3" in message
        assert "files_complete=false" in message
        assert json.loads(ctx.cursor)["pending"] == pending
    assert {
        str(path): path.read_bytes() for path in (work / "files").rglob("*.json")
    } == before
    assert not (work / "complete.json").exists()
    assert not (work / "events_complete.json").exists()
    assert event_count(f["instance"]) == before_events


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("failed_parent", [False, True])
def test_actual_recovery_closes_parent_and_advances_to_next_notification(
    update_fixture, monkeypatch, freq, failed_parent
):
    from collections import Counter

    from tests.test_stock_period_silver_jobs import definitions

    f = update_fixture
    ctx, parent_request, parent_id, child = frozen_recovery(f, monkeypatch, freq)
    if failed_parent:
        # A failed attempt record must not conceal the already-frozen successor.
        # File/check evidence is still from the actual successful native job.
        f["instance"].create_run_for_job(
            definitions(f["lake"]).resolve_job_def(parent_request.job_name),
            run_config=parent_request.run_config,
            status=dg.DagsterRunStatus.FAILURE,
            tags={"dagster/run_key": parent_request.run_key},
        )
    selected, select = [], silver.select_period

    def tracked(*args, **kwargs):
        selected.append((args[2], args[3]))
        return select(*args, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    assert run_request(f, recovery_request(child), monkeypatch).success
    tail = "2026-10-16" if freq == "week" else "2026-10"
    assert selected == [(freq, tail)]
    work = run_directory(f["staging"], child["identity"]["run_id"])
    summary = read_json(work / "complete.json")
    # Independent expectation from the fixture's three eligible periods.
    assert summary["totals"][freq] == {"files": 3, "rows": 6}
    reads, read = Counter(), silver.read_json

    def counted(path):
        reads[str(path)] += 1
        return read(path)

    monkeypatch.setattr(silver, "read_json", counted)
    guard_sensor_computation(monkeypatch)
    assert tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
    assert "pending" not in json.loads(ctx.cursor)
    closed = read_json(work / "events_complete.json")
    assert closed["files"] == 3 and closed["checks"] == 9
    coverage = read_json(
        run_directory(f["staging"], parent_id) / "events_complete.json"
    )
    assert coverage["covered_by_execution_id"] == child["identity"]["run_id"]
    assert coverage["files"] == 3 and coverage["checks"] == 9
    for path in (work / "files").rglob("*.json"):
        assert reads[str(path)] == 1
    assert reads[str(work / "complete.json")] == 1
    next_tick = tick(f, ctx, freq)
    assert len(next_tick.run_requests) == 1
    assert next_tick.run_requests[0].partition_key == tail
    assert next_tick.run_requests[0].run_key != parent_request.run_key
    assert selected == [(freq, tail)]


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("destination", ["child", "parent"])
def test_recovery_completion_save_failure_retries_only_confirmation(
    update_fixture, monkeypatch, freq, destination
):
    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli

    f = update_fixture
    ctx, _, parent_id, child = frozen_recovery(f, monkeypatch, freq)
    assert run_request(f, recovery_request(child), monkeypatch).success
    child_id = child["identity"]["run_id"]
    work = run_directory(f["staging"], child_id)
    failed_path = (
        run_directory(f["staging"], child_id if destination == "child" else parent_id)
        / "events_complete.json"
    )
    before = {
        u["target"]: file_version(u["target"]) for u in child["identity"]["units"]
    }
    before_events, before_calls = event_count(f["instance"]), len(f["source_calls"])
    original = silver.atomic_json

    def fail(path, value):
        if path == failed_path:
            raise OSError("injected recovery completion save failure")
        return original(path, value)

    guard_sensor_computation(monkeypatch)
    with monkeypatch.context() as fault:
        fault.setattr(silver if destination == "child" else cli, "atomic_json", fail)
        assert "save failure" in tick(f, ctx, freq).skip_reason.skip_message
    assert json.loads(ctx.cursor)["pending"]["execution_id"] == child_id
    assert tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
    assert "pending" not in json.loads(ctx.cursor)
    assert read_json(work / "events_complete.json")["files"] == 3
    assert all(file_version(path) == version for path, version in before.items())
    assert event_count(f["instance"]) == before_events
    assert len(f["source_calls"]) == before_calls


@pytest.mark.parametrize("freq", ["week", "month"])
def test_direct_confirmation_cannot_bypass_unexecuted_file_stage(
    update_fixture, monkeypatch, freq
):
    f = update_fixture
    _, _, parent_id, child = frozen_recovery(f, monkeypatch, freq)
    before = event_count(f["instance"])
    guard_sensor_computation(monkeypatch)
    with pytest.raises(ValueError, match="silver_update_files_incomplete"):
        silver.confirm_update_delivery(f["lake"], f["staging"], child, {})
    assert event_count(f["instance"]) == before
    assert not (
        run_directory(f["staging"], child["identity"]["run_id"]) / "files"
    ).exists()
    assert not (
        run_directory(f["staging"], parent_id) / "events_complete.json"
    ).exists()


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("ready", [False, True])
def test_pending_recovery_preserves_run_and_set_query_budgets(
    update_fixture, monkeypatch, freq, ready
):
    from orchestrator.defs.asset_guards import (
        stock_period_silver_readiness as readiness,
    )

    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    if ready:
        assert run_request(f, recovery_request(child), monkeypatch).success
    counts = {"runs": 0, "observations": 0, "readiness_sql": 0}
    get_runs = f["instance"].get_runs
    observations = f["instance"].fetch_observations
    batch = readiness.batch_event_evidence

    def runs(*args, **kwargs):
        counts["runs"] += 1
        return get_runs(*args, **kwargs)

    def observed(*args, **kwargs):
        counts["observations"] += 1
        return observations(*args, **kwargs)

    def queried(*args, **kwargs):
        counts["readiness_sql"] += 2
        return batch(*args, **kwargs)

    monkeypatch.setattr(f["instance"], "get_runs", runs)
    monkeypatch.setattr(f["instance"], "fetch_observations", observed)
    monkeypatch.setattr(readiness, "batch_event_evidence", queried)
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert counts == {"runs": 2, "observations": 0, "readiness_sql": 2 if ready else 0}


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("record_type", ["checkpoint", "summary"])
def test_progress_cache_rejects_version_change_and_refreshes_next_tick(
    update_fixture, monkeypatch, freq, record_type
):
    f = update_fixture
    _, _, _, child = frozen_recovery(f, monkeypatch, freq)
    assert run_request(f, recovery_request(child), monkeypatch).success
    work = run_directory(f["staging"], child["identity"]["run_id"])
    path = (
        silver.checkpoint_path(work, child["identity"]["units"][-1])
        if record_type == "checkpoint"
        else work / "complete.json"
    )
    guard_sensor_computation(monkeypatch)
    expected = {"files": 3, "committed": 3, "files_complete": True}
    with silver.recovery_evidence():
        assert silver.update_delivery_progress(f["staging"], child) == expected
        # Valid JSON, identical content, but a different durable file version.
        path.write_text(path.read_text() + " ")
        with pytest.raises(ValueError, match="silver_recovery_evidence_changed"):
            silver.update_delivery_progress(f["staging"], child)
    with silver.recovery_evidence():
        assert silver.update_delivery_progress(f["staging"], child) == expected


@pytest.mark.parametrize("freq", ["week", "month"])
def test_completed_recovery_refuses_missing_anchor_check_evidence(
    update_fixture, monkeypatch, freq
):
    """A deliberately incomplete evidence response cannot borrow a parent's green.

    The native job really produced all checks. Only the consumer's evidence
    response is shortened here; this is not proof of an actual event-store loss.
    """
    from orchestrator.defs.asset_guards import (
        stock_period_silver_readiness as readiness,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import check_names

    f = update_fixture
    ctx, _, _, child = frozen_recovery(f, monkeypatch, freq)
    assert run_request(f, recovery_request(child), monkeypatch).success
    anchor = child["identity"]["units"][-1]["period"]
    original = readiness.batch_event_evidence
    calls = []

    def missing(*args, **kwargs):
        evidence = original(*args, **kwargs)
        current = evidence[(asset_name(freq), anchor)]
        assert set(current["checks"]) == set(check_names(freq))
        current["checks"].pop(check_names(freq)[0])
        calls.append(anchor)
        return evidence

    monkeypatch.setattr(readiness, "batch_event_evidence", missing)
    before_events = event_count(f["instance"])
    pending = json.loads(ctx.cursor)["pending"]
    guard_sensor_computation(monkeypatch)
    result = tick(f, ctx, freq)
    assert not result.run_requests
    assert result.skip_reason.skip_message.startswith("silver_target_checks_not_ready")
    assert "files_complete=true" in result.skip_reason.skip_message
    assert calls == [anchor]
    assert json.loads(ctx.cursor)["pending"] == pending
    assert event_count(f["instance"]) == before_events
    assert not (
        run_directory(f["staging"], child["identity"]["run_id"])
        / "events_complete.json"
    ).exists()
