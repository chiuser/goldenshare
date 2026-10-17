"""State gold cases are literal independent facts; source/file checks use real fixtures elsewhere."""

import copy
from types import SimpleNamespace

import pytest

from orchestrator.moneyflow_continuation.contract import ContinuationError
from orchestrator.moneyflow_continuation.state import NativeBackend, next_action
from tests.test_moneyflow_continuation_plan import plan_for


def snapshot():
    clean = {
        "ready": False,
        "reason": "missing_materialization",
        "active": False,
        "owned": False,
        "failed": False,
        "runs": [],
        "sha256": None,
        "materialized": False,
    }
    return {
        "dataset": "moneyflow_mkt_dc",
        "trade_date": "2026-10-08",
        "registered": False,
        "raw": copy.deepcopy(clean),
        "silver": copy.deepcopy(clean),
    }


def test_state_progression_is_native_fact_based():
    value = snapshot()
    value["silver"]["reason"] = "raw_not_ready"
    assert next_action(value) == "register"
    value["registered"] = True
    assert next_action(value) == "raw"
    value["raw"].update(
        active=True, owned=True, runs=[{"run_id": "r", "status": "QUEUED"}]
    )
    assert next_action(value) == "observe_raw"
    value["raw"].update(active=False, ready=True, reason="ready")
    value["silver"]["reason"] = "missing_materialization"
    assert next_action(value) == "silver"
    value["silver"].update(ready=True, reason="ready")
    assert next_action(value) == "complete"


@pytest.mark.parametrize(
    "reason",
    [
        "check_missing",
        "file_without_materialization",
        "check_failed_or_stale",
        "file_changed",
        "upstream_revision",
        "raw_not_ready",
    ],
)
def test_broken_delivery_never_skipped(reason):
    value = snapshot()
    value["raw"]["reason"] = reason
    with pytest.raises(ContinuationError):
        next_action(value)


@pytest.mark.parametrize("status", ["FAILURE", "CANCELED"])
def test_failed_native_stops(status):
    value = snapshot()
    value["raw"].update(failed=True, runs=[{"run_id": "r", "status": status}])
    with pytest.raises(ContinuationError, match="native_run_failed"):
        next_action(value)


def test_foreign_active_stops_but_own_active_resumes():
    value = snapshot()
    value["raw"]["active"] = True
    with pytest.raises(ContinuationError, match="foreign_moneyflow_run"):
        next_action(value)
    value["raw"]["owned"] = True
    assert next_action(value) == "observe_raw"


def native_run(unit):
    origin = SimpleNamespace(
        job_name=unit["raw"]["job"],
        repository_origin=SimpleNamespace(
            repository_name="__repository__",
            code_location_origin=SimpleNamespace(location_name="orchestrator"),
        ),
    )
    return SimpleNamespace(
        job_name=unit["raw"]["job"],
        run_config={},
        tags={
            "dagster/partition": unit["trade_date"],
            "dagster/partition_set": unit["raw"]["job"] + "_partition_set",
        },
        remote_job_origin=origin,
        asset_selection=None,
        asset_check_selection=None,
        resolved_op_selection=None,
        op_selection=None,
        step_keys_to_execute=[
            unit["raw"]["asset"],
            unit["raw"]["asset"] + "_" + unit["raw"]["check"],
        ],
    )


@pytest.mark.parametrize("change", ["run_config", "origin", "partition", "partial"])
def test_native_identity_uses_real_sdk_contract(change):
    unit = plan_for()["units"][0]
    run = native_run(unit)
    backend = NativeBackend(None)
    backend.validate_run(run, unit, "raw")
    if change == "run_config":
        run.run_config = {"bad": True}
    elif change == "origin":
        run.remote_job_origin.repository_origin.repository_name = "wrong"
    elif change == "partition":
        run.tags["dagster/partition"] = "2026-10-09"
    else:
        run.step_keys_to_execute = [unit["raw"]["asset"]]
    with pytest.raises(ContinuationError):
        backend.validate_run(run, unit, "raw")


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "dependency",
        "calendar",
        "config",
        "loaded",
        "isolated",
        "new_module",
        "unrelated",
    ],
)
def test_verification_rechecks_each_real_file_binding(tmp_path, monkeypatch, change):
    from orchestrator.moneyflow_continuation import state
    from orchestrator.moneyflow_continuation.contract import file_hash
    from orchestrator.moneyflow_continuation.submission import write_json

    dependencies = {"src/orchestrator/moneyflow_continuation/state.py": "a" * 64}
    inventory = {**dependencies, "src/orchestrator/defs/jobs/stock_weekly.py": "b" * 64}
    calendar, config = tmp_path / "calendar.parquet", tmp_path / "dagster.yaml"
    calendar.write_bytes(b"literal calendar proof")
    config.write_text("literal isolated configuration")
    monkeypatch.setattr(state, "INSTANCE_HOME", tmp_path)
    monkeypatch.setattr(state, "silver_trade_calendar_path", lambda _: calendar)
    monkeypatch.setattr(state, "dependency_files", lambda: dict(dependencies))
    monkeypatch.setattr(state, "source_inventory", lambda: dict(inventory))
    isolated = tmp_path / "isolated.json"
    write_json(
        isolated,
        {
            "exit_code": 0,
            "dependencies": dict(dependencies),
            "source_inventory": dict(inventory),
            "command": [".venv/bin/dg", "check", "defs"],
            "isolated_instance": True,
            "no_formal_credentials": True,
        },
    )
    backend = NativeBackend(None)
    backend.runtime = lambda: {"server_id": "server-one"}
    proof = tmp_path / "proof.json"
    write_json(
        proof,
        {
            "dependencies": dict(dependencies),
            "source_inventory": dict(inventory),
            "calendar_sha256": file_hash(calendar),
            "config_sha256": file_hash(config),
            "isolated_definitions": {
                "path": str(isolated),
                "sha256": file_hash(isolated),
            },
            "runtime": {"server_id": "server-one"},
        },
    )
    ref = {"path": str(proof), "sha256": file_hash(proof)}
    if change == "dependency":
        dependencies[next(iter(dependencies))] = "c" * 64
    elif change == "calendar":
        calendar.write_bytes(b"changed")
    elif change == "config":
        config.write_text("changed")
    elif change == "loaded":
        backend.runtime = lambda: {"server_id": "server-two"}
    elif change == "isolated":
        isolated.write_text("{}")
    elif change == "new_module":
        inventory["src/orchestrator/defs/new_asset.py"] = "c" * 64
    elif change == "unrelated":
        inventory["src/orchestrator/defs/jobs/stock_weekly.py"] = "c" * 64
    if change in {"none", "unrelated"}:
        assert backend.verification(ref)["runtime"]["server_id"] == "server-one"
    else:
        with pytest.raises(ContinuationError):
            backend.verification(ref)


@pytest.mark.parametrize("conflict", ["none", "wrong_key", "duplicate"])
def test_native_reconciliation_cross_checks_partition_and_exact_key(conflict):
    from orchestrator.moneyflow_continuation.plan import request_for

    unit = plan_for()["units"][0]
    body = request_for(unit, "raw", "2026-10-17")
    key = next(
        t["value"]
        for t in body["variables"]["executionParams"]["executionMetadata"]["tags"]
        if t["key"] == "dagster/run_key"
    )
    run = native_run(unit)
    run.tags["dagster/run_key"] = key
    run.run_id, run.status = "one", SimpleNamespace(value="QUEUED")
    backend = NativeBackend(None)
    backend.runs = lambda _u, _l, key=None: (
        [run, run]
        if conflict == "duplicate"
        else []
        if conflict == "wrong_key" and key
        else [run]
    )
    if conflict == "none":
        assert backend.reconcile(unit, "raw", body) == {
            "run_id": "one",
            "status": "QUEUED",
        }
    else:
        with pytest.raises(ContinuationError):
            backend.reconcile(unit, "raw", body)


@pytest.mark.parametrize(
    "change",
    ["none", "sensor", "job", "pool", "partition", "check", "dependency", "server"],
)
def test_loaded_runtime_checks_fourteen_assets_and_twenty_one_switches(change):
    import time

    from tests.test_moneyflow_continuation_plan import NAMES

    sensors, jobs, nodes = [], [], []
    for name in NAMES:
        raw, silver = "raw_tushare_" + name, "silver_" + name
        sensors.append(
            {
                "name": "cn_a_" + name + "_trade_day_sensor",
                "defaultStatus": "STOPPED",
                "sensorState": {"status": "STOPPED"},
            }
        )
        for asset, check in (
            (raw, raw + "_file_contract_check"),
            (silver, silver + "_standardization_check"),
        ):
            job = asset + "_update_job"
            jobs.append({"name": job})
            sensors.append(
                {
                    "name": job + "_sensor",
                    "defaultStatus": "STOPPED",
                    "sensorState": {"status": "STOPPED"},
                }
            )
            nodes.append(
                {
                    "assetKey": {"path": [asset]},
                    "pools": ["moneyflow_tushare_writer"],
                    "dependencyKeys": [] if asset == raw else [{"path": [raw]}],
                    "partitionDefinition": {
                        "dimensionTypes": [
                            {
                                "dynamicPartitionsDefinitionName": "cn_a_"
                                + name
                                + "_trade_days"
                            }
                        ]
                    },
                    "assetChecksOrError": {
                        "__typename": "AssetChecks",
                        "checks": [{"name": check, "blocking": True}],
                    },
                }
            )
    entry = {
        "name": "orchestrator",
        "loadStatus": "LOADED",
        "locationOrLoadError": {
            "__typename": "RepositoryLocation",
            "name": "orchestrator",
            "serverId": "server-one",
        },
    }
    data = {
        "version": "1.13.26",
        "repositoriesOrError": {
            "__typename": "RepositoryConnection",
            "nodes": [
                {
                    "name": "__repository__",
                    "location": {"name": "orchestrator"},
                    "jobs": jobs,
                    "sensors": sensors,
                }
            ],
        },
        "workspaceOrError": {"__typename": "Workspace", "locationEntries": [entry]},
        "instance": {
            "daemonHealth": {
                "allDaemonStatuses": [
                    {
                        "required": True,
                        "healthy": True,
                        "lastHeartbeatTime": time.time(),
                    }
                    for _ in range(7)
                ]
            }
        },
    }
    if change == "sensor":
        sensors[0]["sensorState"]["status"] = "RUNNING"
    elif change == "job":
        jobs.pop()
    elif change == "pool":
        nodes[0]["pools"] = []
    elif change == "partition":
        nodes[0]["partitionDefinition"]["dimensionTypes"] = []
    elif change == "check":
        nodes[0]["assetChecksOrError"]["checks"][0]["blocking"] = False
    elif change == "dependency":
        nodes[1]["dependencyKeys"] = []
    elif change == "server":
        entry["loadStatus"] = "LOADING"
    backend = NativeBackend(None)
    backend.http = lambda body: {
        "data": data if "version" in body["query"] else {"assetNodes": nodes}
    }
    if change == "none":
        result = backend.runtime()
        assert len(result["assets"]) == 14 and len(result["sensors"]) == 21
    else:
        with pytest.raises(ContinuationError):
            backend.runtime()


@pytest.mark.parametrize("problem", ["none", "pool", "claimed", "foreign_run"])
def test_guard_uses_readonly_pool_and_ignores_unrelated_queue(
    tmp_path, monkeypatch, problem
):
    from contextlib import contextmanager
    from pathlib import Path

    from orchestrator.moneyflow_continuation import state
    from tests.test_moneyflow_continuation_plan import AT

    # PostgreSQL SELECT boundary replaced; no test can reach a real database.
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

        def fetchall(self):
            return self.value

    class Connection:
        def execute(self, query, *_):
            sql = str(query)
            if sql.startswith("SHOW"):
                return Result("on")
            if "concurrency_limits" in sql:
                return Result([(2 if problem == "pool" else 1, False)])
            if "concurrency_slots" in sql:
                return Result([("unknown" if problem == "claimed" else None,)])
            assert "pending_steps" in sql
            return Result(0)

    @contextmanager
    def connection():
        yield Connection()

    filters = []

    def runs(query, **kw):
        filters.append(query)
        assert query.job_name.startswith(("raw_tushare_moneyflow", "silver_moneyflow"))
        return [object()] if problem == "foreign_run" else []

    backend = NativeBackend(
        SimpleNamespace(
            event_log_storage=SimpleNamespace(index_connection=connection),
            get_runs=runs,
        )
    )
    backend.lake, backend.staging, backend.control = (
        tmp_path / "lake",
        tmp_path / "staging",
        tmp_path / "control",
    )
    backend.lake.mkdir()
    backend.staging.mkdir()
    backend.verification = lambda _: {}
    backend.calendar = lambda dates: set(dates)
    monkeypatch.setattr(state, "INSTANCE_HOME", tmp_path)
    (tmp_path / "dagster.yaml").write_text(
        "concurrency:\n  runs:\n    max_concurrent_runs: 1\n  pools:\n    granularity: run\n"
    )
    monkeypatch.setattr(Path, "is_mount", lambda _: True)
    monkeypatch.setattr(
        state.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**3)
    )
    if problem == "none":
        backend.guard(plan_for(), AT)
        assert len(filters) == 14 and backend.meter.count <= 40
    else:
        with pytest.raises(ContinuationError):
            backend.guard(plan_for(), AT)


@pytest.mark.parametrize(
    "problem", ["none", "wrong_key", "duplicate", "no_intent", "wrong_response"]
)
def test_snapshot_reuses_one_native_read_per_layer_and_keeps_identity_checks(
    tmp_path, monkeypatch, problem
):
    from orchestrator.moneyflow_continuation import state
    from orchestrator.moneyflow_continuation.contract import digest
    from orchestrator.moneyflow_continuation.submission import Journal, write_json
    from tests.test_moneyflow_continuation_plan import AT

    plan = plan_for()
    unit = plan["units"][0]
    journal = Journal(plan, tmp_path)
    files = journal.prepare(unit, "raw", AT, None, {})
    if problem != "no_intent":
        write_json(
            journal.action_dir(unit, "raw") / "send_intent.json",
            {"request_sha256": digest(files["request"])},
        )
    if problem == "wrong_response":
        write_json(
            journal.action_dir(unit, "raw") / "response.json",
            {
                "request_sha256": digest(files["request"]),
                "value": {
                    "data": {
                        "launchRun": {
                            "__typename": "LaunchRunSuccess",
                            "run": {"runId": "wrong"},
                        }
                    }
                },
            },
        )
    run = native_run(unit)
    run.run_id, run.status = "one", SimpleNamespace(value="QUEUED")
    # Literal key follows the public run-key contract and accepted 10-08 sample.
    run.tags["dagster/run_key"] = "raw_tushare_moneyflow_mkt_dc:2026-10-08:2026-10-17:1"
    if problem == "wrong_key":
        run.tags["dagster/run_key"] = "different"
    queries = []

    def runs(filters, **kwargs):
        queries.append(filters)
        if filters.job_name.startswith("silver_"):
            return []
        return [run, run] if problem == "duplicate" else [run]

    backend = NativeBackend(
        SimpleNamespace(get_runs=runs, has_dynamic_partition=lambda *_: True)
    )
    missing = SimpleNamespace(
        ready=False, reason="missing_materialization", materialized=False, metadata=None
    )
    monkeypatch.setattr(
        state,
        "batch_moneyflow_readiness",
        lambda *a, **k: {
            layer: {unit["trade_date"]: missing} for layer in ("raw", "silver")
        },
    )
    if problem == "none":
        value = backend.snapshots([unit], journal)[0]
        assert next_action(value) == "observe_raw"
        assert (
            len(queries) == 2
        )  # One date+job read for each layer, no exact-key requery.
        assert all(q.tags == {"dagster/partition": "2026-10-08"} for q in queries)
    else:
        with pytest.raises(ContinuationError):
            value = backend.snapshots([unit], journal)[0]
            next_action(value)
