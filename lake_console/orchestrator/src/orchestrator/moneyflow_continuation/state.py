"""Bounded native facts and physical delivery audit; journals never prove success."""

import ast
import fcntl
import json
import os
import shutil
import time
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import dagster as dg
import yaml
from sqlalchemy import text

from orchestrator.defs.asset_guards.moneyflow_delivery_readiness import (
    batch_moneyflow_readiness,
)
from orchestrator.defs.bootstrap.daily_basic_event_instance import INSTANCE_HOME
from orchestrator.defs.checks.moneyflow import (
    audit_market_moneyflow_file,
    audit_market_moneyflow_standardization,
)
from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_equality,
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
    daily_file_scope_counts,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_moneyflow_path,
    silver_moneyflow_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_MAX_ELAPSED_SECONDS,
    MONEYFLOW_MAX_REQUESTS,
    MONEYFLOW_STABILITY_SECONDS,
    MONEYFLOW_STOCK_READINESS_FILE_MAX_BYTES,
    MONEYFLOW_WRITER_POOL,
    assert_moneyflow_memory_budget,
)
from orchestrator.moneyflow_continuation.contract import (
    ACTIVE,
    CONTRACTS,
    CONTROL,
    DATASETS,
    ENDPOINT,
    POLICY,
    PROJECT,
    REPOSITORY,
    encoded,
    file_hash,
    read_json,
    require,
    safe_path,
)
from orchestrator.moneyflow_continuation.plan import LAUNCH, REGISTER
from orchestrator.moneyflow_continuation.recovery import (
    ACTION,
    REEXECUTE,
    effective_runs,
    matches,
    request,
)

RUNTIME_QUERY = """query {version repositoriesOrError {__typename ... on RepositoryConnection{nodes{name location{name} jobs{name} sensors{name defaultStatus sensorState{status}}}}} workspaceOrError{__typename ... on Workspace{locationEntries{name loadStatus locationOrLoadError{__typename ... on RepositoryLocation{name serverId}}}}} instance{daemonHealth{allDaemonStatuses{daemonType required healthy lastHeartbeatTime}}}}"""
ASSETS_QUERY = """query($keys:[AssetKeyInput!]){assetNodes(assetKeys:$keys){assetKey{path} pools dependencyKeys{path} partitionDefinition{dimensionTypes{dynamicPartitionsDefinitionName}} assetChecksOrError{__typename ... on AssetChecks{checks{name blocking}}}}}"""


def source_inventory():
    files = sorted((PROJECT / "src/orchestrator").rglob("*.py"))
    require(len(files) <= POLICY.source_files, "source_inventory_limit")
    return {
        str(p.relative_to(PROJECT)): file_hash(p)
        for p in [*files, PROJECT / "pyproject.toml"]
    }


def dependency_files():
    """Conservative local import closure, including shared modules in full."""
    base = PROJECT / "src"
    roots = [
        base / "orchestrator/definitions.py",
        base / "orchestrator/defs/resources.py",
        base / "orchestrator/moneyflow_continuation_cli.py",
    ]
    for dataset in DATASETS:
        roots += [
            base / f"orchestrator/defs/{kind}/{dataset}{suffix}.py"
            for kind, suffix in (
                ("assets", ""),
                ("jobs", ""),
                ("checks", ""),
                ("sensors", "_sensor"),
            )
        ]
    roots.remove(base / "orchestrator/defs/checks/moneyflow.py")
    roots.append(base / "orchestrator/defs/checks/moneyflow_stock.py")
    roots += list((base / "orchestrator/moneyflow_continuation").glob("*.py"))
    visited = set()
    while roots:
        path = safe_path(roots.pop())
        if path in visited:
            continue
        require(path.is_file(), "dependency_missing")
        visited.add(path)
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [name.name for name in node.names]
            elif isinstance(node, ast.ImportFrom):
                require(node.level == 0, "relative_dependency_needs_audit")
                modules = [node.module or ""]
                modules += [
                    (node.module or "") + "." + name.name for name in node.names
                ]
            else:
                continue
            for module in modules:
                if not module.startswith("orchestrator"):
                    continue
                candidate = base.joinpath(*module.split("."))
                target = candidate.with_suffix(".py")
                if not target.is_file():
                    target = candidate / "__init__.py"
                if target.is_file():
                    roots.append(target)
                # Package initializers execute even for a leaf import.
                for parent in candidate.parents:
                    if parent == base:
                        break
                    init = parent / "__init__.py"
                    if init.is_file():
                        roots.append(init)
        require(len(visited) <= POLICY.dependency_files, "dependency_limit")
    return {str(p.relative_to(PROJECT)): file_hash(p) for p in sorted(visited)}


class ReadMeter:
    def __init__(self):
        self.started = time.monotonic()
        self.count = 0
        self.consume = None

    def tick(self):
        assert_moneyflow_memory_budget()
        if self.consume:
            self.consume()
        else:
            require(
                self.count < POLICY.plan_reads
                and time.monotonic() - self.started < POLICY.plan_seconds,
                "read_budget",
                4,
            )
            self.count += 1


class Counted:
    """Count actual SDK boundary calls, including readiness's event-storage reads."""

    def __init__(self, target, meter):
        self.target, self.meter = target, meter

    def __getattr__(self, name):
        value = getattr(self.target, name)
        if name == "event_log_storage":
            return Counted(value, self.meter)
        if callable(value):

            def call(*args, **kwargs):
                self.meter.tick()
                return value(*args, **kwargs)

            return call
        return value


def next_action(snapshot):
    """Only clean absence can create work; contradictory evidence stops the batch."""
    for layer in ("raw", "silver"):
        item = snapshot[layer]
        if item["active"]:
            require(item["owned"], "foreign_moneyflow_run")
            return "observe_" + item.get("action", layer)
        require(not item["failed"], "native_run_failed")
        clean = item["reason"] == "missing_materialization" or (
            layer == "silver"
            and item["reason"] == "raw_not_ready"
            and not item.get("materialized", False)
            and not item["runs"]
        )
        require(item["ready"] or clean, layer + ":" + item["reason"])
        require(item["ready"] or not item["runs"], "success_without_delivery")
    if snapshot["silver"]["ready"]:
        require(snapshot["raw"]["ready"], "silver_without_raw")
        return "complete"
    if snapshot["raw"]["ready"]:
        require(snapshot["registered"], "delivery_without_partition")
        return snapshot["silver"].get("action", "silver")
    return "raw" if snapshot["registered"] else "register"


class NativeBackend:
    """The CLI always uses these fixed local resources; tests substitute at the Python boundary."""

    def __init__(self, instance):
        self.meter = ReadMeter()
        self.instance = Counted(instance, self.meter)
        self.lake, self.staging = (
            Path(DEFAULT_LAKE_ROOT),
            Path(DEFAULT_LAKE_STAGING_ROOT),
        )
        self.control = CONTROL
        self.stopping = lambda: False
        self.recovery_journal = None

    @contextmanager
    def connection(self):
        self.meter.tick()
        with connect_configured_duckdb(
            DuckDBConnectionSettings(
                temp_directory=self.staging,
                memory_limit=MONEYFLOW_DUCKDB_MEMORY_LIMIT,
                threads=MONEYFLOW_DUCKDB_THREADS,
            ),
            temp_policy="existing_no_spill",
        ) as connection:
            yield connection

    def http(self, body, *, mutation=False):
        from dagster_graphql.schema import create_schema
        from graphql import get_variable_values, parse, validate

        document = parse(body["query"])
        schema = create_schema().graphql_schema
        require(not validate(schema, document), "graphql_schema")
        require(
            isinstance(
                get_variable_values(
                    schema,
                    document.definitions[0].variable_definitions,
                    body.get("variables", {}),
                ),
                dict,
            ),
            "graphql_variables",
        )
        require(
            mutation == (document.definitions[0].operation.value == "mutation"),
            "graphql_operation",
        )
        if not mutation:
            self.meter.tick()
        request = urllib.request.Request(
            ENDPOINT, data=encoded(body), headers={"Content-Type": "application/json"}
        )
        # urllib does not retry POSTs. An uncertain mutation is recovered only by native reads.
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read(POLICY.plan_bytes + 1)
        require(len(payload) <= POLICY.plan_bytes, "graphql_response_size")
        value = json.loads(payload)
        require(isinstance(value, dict) and not value.get("errors"), "graphql_response")
        return value

    def mutate(self, body):
        require(
            body.get("query") in {REGISTER, LAUNCH, REEXECUTE}, "mutation_not_allowed"
        )
        return self.http(body, mutation=True)

    def runtime(self):
        data = self.http({"query": RUNTIME_QUERY})["data"]
        require(data["version"] == dg.__version__ == "1.13.26", "runtime_version")
        repos = data["repositoriesOrError"]
        require(repos["__typename"] == "RepositoryConnection", "repository_unavailable")
        repo = [
            r
            for r in repos["nodes"]
            if r["name"] == REPOSITORY["repositoryName"]
            and r["location"]["name"] == REPOSITORY["repositoryLocationName"]
        ]
        require(len(repo) == 1, "repository_identity")
        repo = repo[0]
        jobs = {j["name"] for j in repo["jobs"]}
        require(
            all(
                getattr(c, layer + "_job") in jobs
                for c in CONTRACTS.values()
                for layer in ("raw", "silver")
            ),
            "loaded_jobs",
        )
        names = {
            name
            for c in CONTRACTS.values()
            for name in (
                "cn_a_" + c.dataset + "_trade_day_sensor",
                c.raw_job + "_sensor",
                c.silver_job + "_sensor",
            )
        }
        sensors = {
            s["name"]: [s["defaultStatus"], s["sensorState"]["status"]]
            for s in repo["sensors"]
            if s["name"] in names
        }
        require(
            set(sensors) == names
            and all(v == ["STOPPED", "STOPPED"] for v in sensors.values()),
            "moneyflow_sensor_not_stopped",
        )
        workspace = data["workspaceOrError"]
        require(workspace["__typename"] == "Workspace", "workspace_unavailable")
        entries = [
            e for e in workspace["locationEntries"] if e["name"] == "orchestrator"
        ]
        require(
            len(entries) == 1
            and entries[0]["loadStatus"] == "LOADED"
            and entries[0]["locationOrLoadError"]["__typename"] == "RepositoryLocation",
            "location_unavailable",
        )
        health = data["instance"]["daemonHealth"]["allDaemonStatuses"]
        require(
            len(health) == 7
            and all(
                x["healthy"]
                and x["lastHeartbeatTime"]
                and 0 <= time.time() - x["lastHeartbeatTime"] < 90
                for x in health
                if x["required"]
            ),
            "daemon_unhealthy",
        )
        keys = [
            {"path": [getattr(c, layer + "_asset")]}
            for c in CONTRACTS.values()
            for layer in ("raw", "silver")
        ]
        nodes = self.http({"query": ASSETS_QUERY, "variables": {"keys": keys}})["data"][
            "assetNodes"
        ]
        by_key = {n["assetKey"]["path"][0]: n for n in nodes}
        require(len(nodes) == len(by_key) == 14, "loaded_assets")
        for c in CONTRACTS.values():
            require(
                by_key[c.raw_asset]["dependencyKeys"] == [], "loaded_raw_dependency"
            )
            for layer in ("raw", "silver"):
                node = by_key[getattr(c, layer + "_asset")]
                require(
                    node["pools"] == [MONEYFLOW_WRITER_POOL]
                    and node["partitionDefinition"]["dimensionTypes"]
                    == [{"dynamicPartitionsDefinitionName": c.partition_set}]
                    and node["assetChecksOrError"]["__typename"] == "AssetChecks"
                    and node["assetChecksOrError"]["checks"]
                    == [{"name": getattr(c, layer + "_check"), "blocking": True}],
                    "loaded_asset_contract",
                )
            require(
                by_key[c.silver_asset]["dependencyKeys"] == [{"path": [c.raw_asset]}],
                "loaded_dependency",
            )
        return {
            "version": data["version"],
            "server_id": entries[0]["locationOrLoadError"]["serverId"],
            "sensors": sensors,
            "assets": sorted(nodes, key=lambda x: x["assetKey"]["path"]),
        }

    def calendar(self, dates):
        require(0 < len(set(dates)) <= POLICY.max_units, "calendar_scope", 2)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR) FROM read_parquet(?,hive_partitioning=false) "
                "WHERE exchange='SSE' AND is_open=true AND CAST(trade_date AS DATE) IN "
                "(SELECT CAST(unnest(?) AS DATE)) GROUP BY trade_date LIMIT 50",
                [str(silver_trade_calendar_path(self.lake)), list(set(dates))],
            ).fetchall()
        return {r[0] for r in rows}

    def verification(self, reference):
        require(
            set(reference) == {"path", "sha256"}
            and file_hash(reference["path"]) == reference["sha256"],
            "verification_digest",
            2,
        )
        proof = read_json(reference["path"])
        dependencies = dependency_files()
        require(proof.get("dependencies") == dependencies, "dependency_drift")
        inventory = source_inventory()
        require(
            set(proof.get("source_inventory", {})) == set(inventory),
            "source_inventory_members_changed",
        )
        unrelated = sorted(
            path
            for path, sha in inventory.items()
            if path not in dependencies and proof["source_inventory"][path] != sha
        )
        require(
            proof.get("calendar_sha256")
            == file_hash(silver_trade_calendar_path(self.lake)),
            "calendar_drift",
        )
        require(
            proof.get("config_sha256") == file_hash(INSTANCE_HOME / "dagster.yaml"),
            "instance_config_drift",
        )
        isolated = proof.get("isolated_definitions", {})
        require(
            set(isolated) == {"path", "sha256"}
            and file_hash(isolated["path"]) == isolated["sha256"],
            "isolated_proof_digest",
        )
        report = read_json(isolated["path"])
        require(
            report.get("exit_code") == 0
            and report.get("dependencies") == dependencies
            and report.get("source_inventory") == proof["source_inventory"]
            and isinstance(report.get("command"), list)
            and bool(report["command"])
            and report.get("isolated_instance") is True
            and report.get("no_formal_credentials") is True,
            "isolated_definitions_not_proven",
        )
        require(self.runtime() == proof.get("runtime"), "loaded_code_drift")
        return {**proof, "unrelated_source_changes": unrelated}

    def guard(self, plan, at):
        from orchestrator.moneyflow_continuation.plan import validate_scope

        require(at < datetime.fromisoformat(plan["valid_until"]), "observation_expired")
        self.last_guard = self.verification(plan["verification"])
        validate_scope(
            [
                {"dataset": u["dataset"], "trade_date": u["trade_date"]}
                for u in plan["units"]
            ],
            self.calendar([u["trade_date"] for u in plan["units"]]),
            at,
        )
        config = yaml.safe_load((INSTANCE_HOME / "dagster.yaml").read_text())
        concurrency = config.get("concurrency", {})
        require(
            concurrency.get("runs", {}).get("max_concurrent_runs") == 1
            and concurrency.get("pools", {}).get("granularity") == "run",
            "global_concurrency",
        )
        require(
            self.lake.parent.is_mount()
            and self.lake.stat().st_dev == self.staging.stat().st_dev
            and shutil.disk_usage(self.staging).free >= POLICY.free_bytes,
            "filesystem_budget",
        )
        lock = safe_path(self.staging / "moneyflow/writer.lock")
        if lock.exists():
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    require(False, "moneyflow_writer_busy")
            finally:
                os.close(fd)
        self.meter.tick()
        with self.instance.event_log_storage.index_connection() as connection:
            require(
                connection.execute(text("SHOW transaction_read_only")).scalar() == "on",
                "not_readonly",
            )
            rows = connection.execute(
                text(
                    'SELECT "limit",using_default_limit FROM concurrency_limits WHERE concurrency_key=:key'
                ),
                {"key": MONEYFLOW_WRITER_POOL},
            ).fetchall()
            require(rows == [(1, False)], "moneyflow_pool_limit")
            self.meter.tick()
            slots = connection.execute(
                text(
                    "SELECT run_id FROM concurrency_slots WHERE concurrency_key=:key AND deleted=false LIMIT 3"
                ),
                {"key": MONEYFLOW_WRITER_POOL},
            ).fetchall()
            require(slots == [(None,)], "moneyflow_pool_claimed")
            self.meter.tick()
            require(
                connection.execute(
                    text(
                        "SELECT count(*) FROM pending_steps WHERE concurrency_key=:key"
                    ),
                    {"key": MONEYFLOW_WRITER_POOL},
                ).scalar()
                == 0,
                "moneyflow_pool_pending",
            )
        for c in CONTRACTS.values():
            for layer in ("raw", "silver"):
                require(
                    not self.instance.get_runs(
                        dg.RunsFilter(
                            job_name=getattr(c, layer + "_job"),
                            statuses=[dg.DagsterRunStatus(s) for s in ACTIVE],
                        ),
                        limit=1,
                    ),
                    "foreign_moneyflow_run",
                )
        self.disk_budget(plan)

    def disk_budget(self, plan):
        from orchestrator.moneyflow_continuation.submission import Journal

        journal = Journal(plan, self.control)
        total, raw_ms = journal.size(), 0
        seen = set()
        for unit in plan["root_units"]:
            for layer in (
                "raw",
                "silver",
                *([ACTION] if matches(plan.get("launch_recovery"), unit) else []),
            ):
                files = journal.read(unit, layer)
                native = files.get("observation", {}).get("native") or {}
                if not native and "response" in files:
                    run = (
                        files["response"]
                        .get("value", {})
                        .get("data", {})
                        .get("launchRun", {})
                        .get("run", {})
                    )
                    native = {"run_id": run.get("runId")}
                run_id = native.get("run_id")
                if run_id and run_id not in seen:
                    require(str(uuid.UUID(run_id)) == run_id, "run_directory_identity")
                    directory = safe_path(
                        self.staging
                        / "moneyflow"
                        / run_id
                        / unit["dataset"]
                        / unit["trade_date"]
                    )
                    if directory.exists():
                        total += self.run_disk_size(directory)
                        receipt = directory / "receipt.json"
                        if layer == "raw" and receipt.exists():
                            value = read_json(receipt, POLICY.action_bytes)
                            elapsed = value.get("elapsed_ms")
                            require(
                                type(elapsed) in (int, float)
                                and 0 <= elapsed < MONEYFLOW_MAX_ELAPSED_SECONDS * 1000,
                                "raw_activity_proof",
                            )
                            raw_ms += elapsed
                    seen.add(run_id)
                target = safe_path(
                    (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
                        self.lake, unit["dataset"], unit["trade_date"]
                    )
                )
                if target.exists():
                    require(target.is_file(), "formal_target_kind")
                    total += target.stat().st_size
                require(
                    total <= POLICY.disk_bytes
                    and raw_ms <= POLICY.raw_activity_seconds * 1000,
                    "session_disk_or_raw_activity_budget",
                )

    def runs(self, unit, layer, key=None):
        tags = {"dagster/partition": unit["trade_date"]}
        if key:
            tags["dagster/run_key"] = key
        return self.instance.get_runs(
            dg.RunsFilter(job_name=unit[layer]["job"], tags=tags),
            limit=POLICY.run_query_limit,
        )

    def validate_run(self, run, unit, layer, body=None):
        require(
            run.job_name == unit[layer]["job"]
            and run.run_config == {}
            and run.tags.get("dagster/partition") == unit["trade_date"]
            and run.tags.get("dagster/partition_set")
            == unit[layer]["job"] + "_partition_set",
            "native_run_identity",
        )
        origin = run.remote_job_origin
        require(
            origin is not None
            and origin.job_name == unit[layer]["job"]
            and origin.repository_origin.repository_name == REPOSITORY["repositoryName"]
            and origin.repository_origin.code_location_origin.location_name
            == REPOSITORY["repositoryLocationName"],
            "native_run_origin",
        )
        require(
            run.asset_selection is None
            and run.asset_check_selection is None
            and run.resolved_op_selection is None
            and run.op_selection is None
            and (
                run.step_keys_to_execute is None
                or set(run.step_keys_to_execute)
                == {
                    unit[layer]["asset"],
                    unit[layer]["asset"] + "_" + unit[layer]["check"],
                }
            ),
            "partial_job_run",
        )
        if body:
            params = body["variables"]["executionParams"]
            require(
                run.tags
                == {
                    **run.tags,
                    **{
                        t["key"]: t["value"]
                        for t in params["executionMetadata"]["tags"]
                    },
                },
                "native_run_tags",
            )

    def reconcile(self, unit, action, body):
        if action == "register":
            return (
                {"partition": unit["trade_date"]}
                if self.instance.has_dynamic_partition(
                    unit["partition_set"], unit["trade_date"]
                )
                else None
            )
        if action == ACTION:
            journal = self.recovery_journal
            require(journal is not None, "recovery_context")
            value = journal.plan.get("launch_recovery")
            require(
                body == request(value, unit, value["raw_sha256"]),
                "recovery_request_changed",
            )
            runs, _ = effective_runs(self, journal, unit, self.runs(unit, "silver"))
            require(
                file_hash(unit["raw"]["target"]) == value["raw_sha256"],
                "recovery_raw_revision",
            )
            return (
                {"run_id": runs[0].run_id, "status": runs[0].status.value}
                if runs
                else None
            )
        key = next(
            t["value"]
            for t in body["variables"]["executionParams"]["executionMetadata"]["tags"]
            if t["key"] == "dagster/run_key"
        )
        exact, dated = self.runs(unit, action, key), self.runs(unit, action)
        require(len(exact) <= 1 and len(dated) <= 1, "duplicate_native_runs")
        require(
            {r.run_id for r in exact} == {r.run_id for r in dated},
            "unexplained_native_run",
        )
        if not exact:
            return None
        self.validate_run(exact[0], unit, action, body)
        return {"run_id": exact[0].run_id, "status": exact[0].status.value}

    @staticmethod
    def check_response(response, action, native):
        data = response.get("data", {})
        result = data.get(
            "addDynamicPartition" if action == "register" else "launchRun", {}
        )
        require(
            result.get("__typename")
            == (
                "AddDynamicPartitionSuccess"
                if action == "register"
                else "LaunchRunSuccess"
            ),
            "mutation_rejected",
        )
        require(
            (result.get("partitionKey") == native["partition"])
            if action == "register"
            else (result.get("run", {}).get("runId") == native["run_id"]),
            "response_native_mismatch",
        )

    def run_status(self, run_id):
        run = self.instance.get_run_by_id(run_id)
        require(run is not None, "native_run_missing")
        return run.status.value

    def snapshots(self, units, journal=None):
        self.recovery_journal = journal
        results = []
        for dataset in DATASETS:
            selected = [u for u in units if u["dataset"] == dataset]
            for offset in range(0, len(selected), POLICY.dates_per_read):
                batch = selected[offset : offset + POLICY.dates_per_read]
                facts = batch_moneyflow_readiness(
                    self.instance,
                    self.lake,
                    [u["trade_date"] for u in batch],
                    contract=CONTRACTS[dataset],
                )
                for unit in batch:
                    snap = {
                        "dataset": dataset,
                        "trade_date": unit["trade_date"],
                        "registered": self.instance.has_dynamic_partition(
                            unit["partition_set"], unit["trade_date"]
                        ),
                    }
                    for layer in ("raw", "silver"):
                        delivery = facts[layer][unit["trade_date"]]
                        runs = self.runs(unit, layer)
                        recovery = (
                            layer == "silver"
                            and journal is not None
                            and matches(journal.plan.get("launch_recovery"), unit)
                        )
                        failed_launch = None
                        action = ACTION if recovery else layer
                        if recovery:
                            require(
                                snap["raw"]["ready"]
                                and snap["raw"]["sha256"]
                                == journal.plan["launch_recovery"]["raw_sha256"],
                                "recovery_raw_not_ready",
                            )
                            runs, failed_launch = effective_runs(
                                self, journal, unit, runs
                            )
                        else:
                            require(len(runs) <= 1, "duplicate_native_runs")
                        for run in runs:
                            self.validate_run(run, unit, layer)
                        files = (
                            journal.read(unit, action)
                            if journal and unit in journal.plan["root_units"]
                            else {}
                        )
                        owned = False
                        if runs and files:
                            # This bounded date+job query has already proved uniqueness.
                            # Check its canonical request tags directly; only submissions
                            # need the independent exact-key/date reconciliation reads.
                            if not recovery:
                                self.validate_run(
                                    runs[0], unit, layer, files["request"]["body"]
                                )
                            native = {
                                "run_id": runs[0].run_id,
                                "status": runs[0].status.value,
                            }
                            owned = "send_intent" in files and native is not None
                            if "response" in files:
                                self.check_response(
                                    files["response"]["value"], action, native
                                )
                        active = bool(runs and runs[0].status.value in ACTIVE)
                        if delivery.ready and not active:
                            require(
                                len(runs) == 1
                                and runs[0].status.value == "SUCCESS"
                                and delivery.record.event_log_entry.run_id
                                == runs[0].run_id,
                                "delivery_run_binding",
                            )
                        snap[layer] = {
                            "ready": delivery.ready and not active,
                            "reason": delivery.reason,
                            "materialized": delivery.materialized,
                            "active": active,
                            "owned": owned,
                            "failed": bool(
                                runs and runs[0].status.value in {"FAILURE", "CANCELED"}
                            ),
                            "runs": [
                                {"run_id": r.run_id, "status": r.status.value}
                                for r in runs
                            ],
                            "sha256": (delivery.metadata or {}).get("file_sha256"),
                        }
                        if recovery:
                            snap[layer].update(
                                action=ACTION, failed_launch=failed_launch
                            )
                        if delivery.ready and not active:
                            snap[layer]["proof"] = self.audit(unit, layer, delivery)
                    results.append(snap)
        return results

    def audit(self, unit, layer, delivery):
        day, dataset = unit["trade_date"], unit["dataset"]
        raw, silver = (
            raw_moneyflow_path(self.lake, dataset, day),
            silver_moneyflow_path(self.lake, dataset, day),
        )
        md = delivery.metadata
        with self.connection() as connection:
            if dataset == "moneyflow_mkt_dc":
                (
                    audit_market_moneyflow_standardization(connection, raw, silver, day)
                    if layer == "silver"
                    else audit_market_moneyflow_file(connection, raw, day)
                )
                count = 1
            else:
                count = (
                    audit_daily_moneyflow_standardization(
                        connection, raw, silver, day, dataset=dataset
                    )
                    if layer == "silver"
                    else audit_daily_moneyflow_file(
                        connection, raw, day, dataset=dataset
                    )
                )
            require(
                delivery.record.asset_materialization.metadata[
                    "dagster/row_count"
                ].value
                == count,
                "materialization_row_count",
            )
            if layer == "raw":
                directory = safe_path(
                    self.staging
                    / "moneyflow"
                    / delivery.record.event_log_entry.run_id
                    / dataset
                    / day
                )
                self.run_disk_size(directory)
                proof_path = safe_path(directory / "receipt.json")
                require(
                    md.get("source_proof_path") == str(proof_path), "source_proof_path"
                )
                proof = read_json(proof_path, POLICY.action_bytes)
                require(
                    proof.get("stage") == "raw_candidate_ready"
                    and proof.get("source") == "tushare"
                    and proof.get("trade_date") == day
                    and proof.get("row_count") == count
                    and proof.get("raw_sha256") == md["file_sha256"]
                    and 2 <= proof.get("request_count", 0) <= MONEYFLOW_MAX_REQUESTS
                    and MONEYFLOW_STABILITY_SECONDS
                    <= proof.get("stability_gap_seconds", 0)
                    and 0
                    <= proof.get("elapsed_ms", -1)
                    < MONEYFLOW_MAX_ELAPSED_SECONDS * 1000,
                    "source_receipt",
                )
                checkpoint = read_json(
                    directory / "promotion-raw.json", POLICY.action_bytes
                )
                require(
                    checkpoint.get("published_sha256") == md["file_sha256"]
                    and checkpoint.get("stage") == "complete"
                    and checkpoint.get("trade_date") == day
                    and checkpoint.get("layer") == "raw"
                    and checkpoint.get("target") == str(raw),
                    "publication_proof",
                )
                if dataset != "moneyflow_mkt_dc":
                    verification = safe_path(directory / "verification.parquet")
                    require(
                        proof.get("dataset") == dataset
                        and proof.get("row_count_guard", {}).get("passed") is True
                        and verification.stat().st_size
                        <= MONEYFLOW_STOCK_READINESS_FILE_MAX_BYTES
                        and file_hash(verification) == proof.get("verification_sha256"),
                        "source_verification",
                    )
                    require(
                        audit_daily_moneyflow_file(
                            connection, verification, day, dataset=dataset
                        )
                        == count
                        and daily_file_scope_counts(connection, raw, dataset=dataset)
                        == proof.get("scope_row_counts"),
                        "source_scope_counts",
                    )
                    audit_daily_moneyflow_equality(
                        connection, raw, verification, dataset=dataset
                    )
        return {
            "run_id": delivery.record.event_log_entry.run_id,
            "materialization_id": delivery.record.storage_id,
            "timestamp": delivery.record.timestamp,
            "sha256": md["file_sha256"],
            "rows": count,
        }

    def run_disk_size(self, directory):
        require(directory.is_dir(), "run_directory_missing")
        paths, total, count = [(directory, 0)], 0, 0
        while paths:
            parent, depth = paths.pop()
            require(depth <= POLICY.depth_per_run, "run_directory_depth")
            for path in parent.iterdir():
                safe_path(path)
                count += 1
                require(count <= POLICY.files_per_run, "run_file_count")
                if path.is_dir():
                    paths.append((path, depth + 1))
                else:
                    require(path.is_file(), "run_special_file")
                    total += path.stat().st_size
                    require(total <= POLICY.disk_bytes, "run_disk_budget")
        return total
