"""Opt-in PG/GraphQL/sensor contract probe; never loads the formal repository.

The fixture asset writes only a temporary counter. It is not a replacement for
the separately tested Raw business executor or its recovery integration.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

import dagster as dg
import psycopg2
import pytest
import yaml
from dagster._core.remote_origin import InProcessCodeLocationOrigin
from dagster._core.types.loadable_target_origin import LoadableTargetOrigin
from dagster._core.workspace.context import WorkspaceProcessContext
from dagster._core.workspace.load_target import InProcessWorkspaceLoadTarget
from dagster._daemon.sensor import execute_sensor_iteration
from dagster_graphql.test.utils import execute_dagster_graphql

from orchestrator.defs.asset_guards.stock_period_check_evidence import (
    read_latest_completed_checks,
)
from orchestrator.defs.asset_guards.stock_period_silver_readiness import raw_check_names
from orchestrator.defs.bootstrap.stock_period_history_cli import _run_reporting
from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from tests.test_stock_period_check_evidence import (
    ASSET,
    PARTITION,
    evaluate,
    materialize,
    plan,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("DG_PERIOD_PG_VERIFY") != "1",
    reason="Explicit isolated PG opt-in required",
)
PG_BIN = Path("/opt/homebrew/opt/postgresql@18/bin")
JOB_NAME = "raw_stk_period_bar_adj_week_update_job"
ASSET_NAME = ASSET.to_user_string()
INTENT_DATE = "2026-10-27"
ANCHOR = "2026-10-30"
PARTITIONS = dg.StaticPartitionsDefinition([ANCHOR])


@dg.resource(config_schema={"directory": str})
def probe_resource(context):
    path = Path(context.resource_config["directory"]).resolve()
    assert path.is_relative_to("/private/tmp")
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_probe(path, kind, context):
    with (path / "calls.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "run_id": context.run.run_id,
                    "partition": context.partition_key,
                    "date": context.run.run_config["ops"][ASSET_NAME]["config"][
                        "automatic_intent_date"
                    ],
                }
            )
            + "\n"
        )


@dg.asset(name=ASSET_NAME, partitions_def=PARTITIONS)
def period_asset(
    context: dg.AssetExecutionContext,
    config: StockPeriodRawConfig,
    probe: dg.ResourceParam[Path],
):
    assert config.automatic_intent_date == INTENT_DATE
    append_probe(probe, "asset", context)
    return dg.MaterializeResult(metadata={"intent_date": config.automatic_intent_date})


def native_check(name, fail=False):
    @dg.asset_check(
        asset=period_asset, name=name, partitions_def=PARTITIONS, blocking=True
    )
    def check(context: dg.AssetCheckExecutionContext, probe: dg.ResourceParam[Path]):
        append_probe(probe, name, context)
        return dg.AssetCheckResult(passed=not (fail and (probe / "fail").exists()))

    return check


NATIVE_CHECKS = [
    native_check(name, index == 0) for index, name in enumerate(raw_check_names("week"))
]
PERIOD_JOB = dg.Definitions(
    assets=[period_asset],
    asset_checks=NATIVE_CHECKS,
    resources={"probe": probe_resource},
    jobs=[dg.define_asset_job(JOB_NAME, executor_def=dg.in_process_executor)],
).resolve_job_def(JOB_NAME)


@dg.sensor(name=JOB_NAME + "_sensor", job=PERIOD_JOB, minimum_interval_seconds=0)
def period_sensor(context):
    yield dg.RunRequest(
        run_key=build_asset_update_run_key(subject=ASSET_NAME, unit_id=INTENT_DATE),
        partition_key=ANCHOR,
        run_config={
            "ops": {ASSET_NAME: {"config": {"automatic_intent_date": INTENT_DATE}}},
            "resources": {
                "probe": {
                    "config": {
                        "directory": str(
                            Path(context.instance.storage_directory()) / "probe"
                        )
                    }
                }
            },
        },
    )


PERIOD_DEFINITIONS = dg.Definitions(
    assets=[period_asset],
    asset_checks=NATIVE_CHECKS,
    resources={"probe": probe_resource},
    jobs=[PERIOD_JOB],
    sensors=[period_sensor],
)


@pytest.fixture(scope="module")
def pg_instance():
    root = Path(tempfile.mkdtemp(prefix="dg-period-pg.", dir="/private/tmp"))
    root.chmod(0o700)
    (root / "socket").mkdir(mode=0o700)
    environment = pytest.MonkeyPatch()
    for key in list(os.environ):
        if key.startswith("PG") or key in {"DAGSTER_HOME", "TUSHARE_TOKEN"}:
            environment.delenv(key)
    state = {"proofs": {}, "temporary_root": str(root)}
    instance = None
    started = False

    def command(binary, *args):
        return subprocess.run(
            [str(PG_BIN / binary), *map(str, args)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ),
        )

    def connect(database):
        conn = psycopg2.connect(
            host=str(root / "socket"),
            port=55437,
            dbname=database,
            user="dg_period_test",
            connect_timeout=5,
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('data_directory'),"
                "current_setting('listen_addresses'),inet_server_addr(),current_database()"
            )
            directory, listeners, address, actual_database = cursor.fetchone()
        assert Path(directory).resolve() == root / "data"
        assert listeners == "" and address is None and actual_database == database
        conn.rollback()
        return conn

    try:
        assert "18.4" in command("initdb", "--version").stdout
        command(
            "initdb",
            "-D",
            root / "data",
            "-U",
            "dg_period_test",
            "--auth=trust",
            "--encoding=UTF8",
            "--no-locale",
        )
        command(
            "pg_ctl",
            "-D",
            root / "data",
            "-l",
            root / "server.log",
            "-o",
            f"-c listen_addresses='' -c unix_socket_directories='{root / 'socket'}' "
            "-c unix_socket_permissions=0700 -p 55437",
            "-w",
            "start",
        )
        started = True
        conn = connect("postgres")
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute("CREATE DATABASE dg_period_verify")
        finally:
            conn.close()
        connect("dg_period_verify").close()
        home = root / "dagster"
        home.mkdir(mode=0o700)
        url = "postgresql://dg_period_test@/dg_period_verify?" + urlencode(
            {"host": str(root / "socket"), "port": 55437}
        )
        (home / "dagster.yaml").write_text(
            yaml.safe_dump(
                {
                    "telemetry": {"enabled": False},
                    "storage": {"postgres": {"postgres_url": url}},
                    "run_launcher": {
                        "module": "dagster._core.launcher.sync_in_memory_run_launcher",
                        "class": "SyncInMemoryRunLauncher",
                    },
                "run_coordinator": {
                    "module": "dagster._core.run_coordinator.sync_in_memory_run_coordinator",
                    "class": "SyncInMemoryRunCoordinator",
                },
                }
            )
        )
        instance = dg.DagsterInstance.from_config(str(home))
        yield instance, state
    finally:
        if instance is not None:
            instance.dispose()
        try:
            if started or (root / "data/postmaster.pid").exists():
                command("pg_ctl", "-D", root / "data", "-m", "fast", "-w", "stop")
            shutil.rmtree(root)
            state["temporary_cluster_removed"] = True
        finally:
            environment.undo()
            state["status"] = (
                "passed"
                if (
                    len(state["proofs"]) == 2 and state.get("temporary_cluster_removed")
                )
                else "failed_or_incomplete"
            )
            state["test_sha256"] = hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest()
            Path(
                "/private/tmp/dg-period-pg-reexecution-results-20261028.json"
            ).write_text(json.dumps(state, indent=2) + "\n")


def test_actual_check_query_on_postgres(pg_instance):
    instance, state = pg_instance
    instance.add_dynamic_partitions("cn_a_stock_week_ends", [PARTITION])
    names = raw_check_names("week")
    old = materialize(instance, "old")
    current = None

    def a(context):
        nonlocal current
        plan(instance, context, names)

        def b(other):
            plan(instance, other, names)
            evaluate(instance, other, names, old)

        _run_reporting(instance, b)
        current = materialize(instance, "new")
        evaluate(instance, context, names, current)

    _run_reporting(instance, a)
    selected = read_latest_completed_checks(
        instance, asset_key=ASSET, check_names=names, partition_key=PARTITION
    )
    assert len(selected) == 3
    assert {
        r.evaluation.target_materialization_data.storage_id
        for r, _, _ in selected.values()
    } == {current.storage_id}
    state["proofs"]["postgres_actual_evaluation_order"] = True


def test_sensor_key_and_real_graphql_from_failure_keep_original_intent(pg_instance):
    instance, state = pg_instance
    probe = Path(instance.storage_directory()) / "probe"
    probe.mkdir(parents=True)
    (probe / "fail").touch()
    origin = InProcessCodeLocationOrigin(
        LoadableTargetOrigin(
            executable_path=sys.executable,
            module_name=__name__,
            attribute="PERIOD_DEFINITIONS",
            working_directory=str(Path(__file__).resolve().parents[1]),
        ),
        location_name="period_isolation",
    )
    with WorkspaceProcessContext(
        instance, InProcessWorkspaceLoadTarget(origin)
    ) as workspace:
        request = workspace.create_request_context()
        remote = (
            request.get_code_location("period_isolation")
            .get_repository(PERIOD_DEFINITIONS.get_repository_def().name)
            .get_sensor(period_sensor.name)
        )
        instance.start_sensor(remote)

        def tick():
            list(
                execute_sensor_iteration(
                    workspace, logging.getLogger("period_isolation"), None, None
                )
            )

        tick()
        runs = instance.get_runs(filters=dg.RunsFilter(job_name=JOB_NAME))
        assert len(runs) == 1 and runs[0].status == dg.DagsterRunStatus.FAILURE
        parent = runs[0]
        tick()
        assert len(instance.get_runs(filters=dg.RunsFilter(job_name=JOB_NAME))) == 1
        (probe / "fail").unlink()
        result = execute_dagster_graphql(
            workspace.create_request_context(),
            """
            mutation Retry($params: ReexecutionParams!) {
              launchRunReexecution(reexecutionParams:$params) {
                __typename ... on LaunchRunSuccess { run { runId } }
                ... on PythonError { message stack }
              }
            }
        """,
            {
                "params": {
                    "parentRunId": parent.run_id,
                    "strategy": "FROM_FAILURE",
                    "useParentRunTags": True,
                }
            },
        )
        payload = result.data["launchRunReexecution"]
        assert payload["__typename"] == "LaunchRunSuccess", payload
        child = instance.get_run_by_id(payload["run"]["runId"])
        assert child.status == dg.DagsterRunStatus.SUCCESS
        assert (
            child.parent_run_id == parent.run_id and child.root_run_id == parent.run_id
        )
        assert child.run_config == parent.run_config
        assert child.tags["dagster/partition"] == ANCHOR
        assert child.tags["dagster/run_key"] == parent.tags["dagster/run_key"]
        calls = [
            json.loads(line)
            for line in (probe / "calls.jsonl").read_text().splitlines()
        ]
        assert sum(c["kind"] == "asset" for c in calls) == 1
        assert all(c["date"] == INTENT_DATE and c["partition"] == ANCHOR for c in calls)
        child_calls = [c for c in calls if c["run_id"] == child.run_id]
        assert child_calls and all(
            c["kind"] in raw_check_names("week") for c in child_calls
        )
        tick()
        assert len(instance.get_runs(filters=dg.RunsFilter(job_name=JOB_NAME))) == 2
        state["proofs"]["graphql_native_from_failure_and_sensor_dedup"] = {
            "parent_run_id": parent.run_id,
            "child_run_id": child.run_id,
            "asset_executions": 1,
            "child_check_executions": len(child_calls),
            "intent_date": INTENT_DATE,
            "partition": ANCHOR,
        }
