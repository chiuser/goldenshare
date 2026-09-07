"""Actual adapters with synthetic approval, sentinels and isolated native storage."""

from stock_suspend_confirmed_test_support import (
    make_confirmed_test_instance,
    make_confirmed_test_resources,
    require_isolated_context,
)

ALLOWED = require_isolated_context()

import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.assets.stock_suspend_confirmed import (
    silver_stock_suspend_confirmed,
)
from orchestrator.defs.checks import stock_suspend_confirmed_checks as checks
from orchestrator.defs.paths import silver_stock_suspend_confirmed_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY,
    CONFIRMED_FACT_VERSION_METADATA_KEY,
)

PARTITIONS = dg.DynamicPartitionsDefinition(name="confirmed_suspend_test_dates")
DAY = "2026-01-16"
CHECKS = (checks.silver_stock_suspend_confirmed_schema_check,
          checks.silver_stock_suspend_confirmed_approved_content_check)


def _lake_inventory(root):
    return [(str(path.relative_to(root)), path.lstat().st_mode, path.lstat().st_ino,
             path.lstat().st_size, path.lstat().st_mtime_ns,
             sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None)
            for path in sorted(root.rglob("*"))] if root.exists() else None


@pytest.fixture
def instance(tmp_path):
    with make_confirmed_test_instance(instance_root=tmp_path / "instance") as instance:
        instance.add_dynamic_partitions(PARTITIONS.name, [DAY])
        yield instance


def seed_publication(instance, root, *, mutation):
    metadata = {
        "dagster/uri": str(silver_stock_suspend_confirmed_path(root)),
        CONFIRMED_FACT_VERSION_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_VERSION,
        CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256,
    }
    field = {"uri": "dagster/uri", "version": CONFIRMED_FACT_VERSION_METADATA_KEY,
             "hash": CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY}.get(mutation)
    if field:
        metadata[field] = "wrong"
    instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=silver_stock_suspend_confirmed.key, metadata=metadata,
        partition=DAY if mutation == "partition" else None,
    ))
    return instance.fetch_materializations(silver_stock_suspend_confirmed.key, limit=1).records[0]


def test_external_spec():
    assert isinstance(silver_stock_suspend_confirmed, dg.AssetSpec)
    assert silver_stock_suspend_confirmed.partitions_def is None
    assert silver_stock_suspend_confirmed.automation_condition is None
    for definition in CHECKS:
        spec = next(iter(definition.check_specs))
        assert spec.blocking and spec.partitions_def is None
        assert spec.asset_key == silver_stock_suspend_confirmed.key


def _case(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, *, stage=None, reason=None):
    path = silver_stock_suspend_confirmed_path(fixed_lake)
    published = None if problem == "no_materialization" else seed_publication(instance, fixed_lake, mutation=problem)
    resources = make_confirmed_test_resources(lake_root=fixed_lake, work_root=ALLOWED)
    assert type(resources["lake_root"]) is LakeRootResource and resources["lake_root"].root() == fixed_lake
    sentinel = tmp_path / "daily-sentinel.txt"
    sentinel.write_text("synthetic unchanged daily\n")
    before = asdict(contract.suspend_file_identity(sentinel))
    before_bytes = sentinel.read_bytes()
    called = []

    if problem == "ok":
        # Initial runless checks really validate the synthetic file (D06).
        for name, schema_only in zip(contract.STOCK_SUSPEND_CONFIRMED_CHECKS, (True, False), strict=True):
            events = list(checks._evaluate_confirmed_check(SimpleNamespace(instance=instance),
                resources["lake_root"], resources["duckdb"], check_name=name, schema_only=schema_only))
            assert events[0].passed
            instance.report_runless_asset_event(events[0])

    if problem in ("bad_content", "zero", "short", "over", "invalid_domain"):
        connection.execute("CREATE TEMP TABLE changed AS SELECT * FROM read_parquet(?)", [str(path)])
        mutations = {
            "bad_content": "UPDATE changed SET ts_code='000002.SZ' WHERE ts_code='000001.SZ'",
            "zero": "DELETE FROM changed", "short": "DELETE FROM changed WHERE ts_code='000001.SZ'",
            "over": "INSERT INTO changed SELECT '000003.SZ', DATE '2020-01-03', NULL, 'S', 'add_missing'",
            "invalid_domain": "UPDATE changed SET suspend_timing=''",
        }
        connection.execute(mutations[problem])
        connection.execute("COPY changed TO ? (FORMAT PARQUET)", [str(path)])
    elif problem == "bad_schema":
        connection.execute("COPY (SELECT 1 AS wrong) TO ? (FORMAT PARQUET)", [str(path)])
    elif problem == "corrupt":
        path.write_bytes(b"synthetic corrupt parquet")
    elif problem == "missing_root":
        fixed_lake.rename(tmp_path / "moved-lake")
    elif problem in ("missing_file", "directory", "symlink"):
        moved = path.with_suffix(".moved")
        path.rename(moved)
        if problem == "directory":
            path.mkdir()
        elif problem == "symlink":
            path.symlink_to(moved)
    elif problem == "escape":
        monkeypatch.setattr(checks, "silver_stock_suspend_confirmed_path", lambda root: tmp_path / "outside.parquet")

    @dg.asset(name="silver_stock_suspend_daily", deps=[silver_stock_suspend_confirmed], partitions_def=PARTITIONS)
    def daily():
        called.append("writer")
        sentinel.write_text("synthetic daily executed\n")
        return dg.MaterializeResult()

    def make_final_check(name):
        @dg.asset_check(asset=daily, name=name, partitions_def=PARTITIONS, blocking=True)
        def final_check():
            return dg.AssetCheckResult(passed=True)
        return final_check

    definitions = dg.Definitions(
        assets=[silver_stock_suspend_confirmed, daily],
        asset_checks=[*CHECKS, *[make_final_check(name) for name in ("fixture_schema", "fixture_domain", "fixture_partition")]],
        jobs=[dg.define_asset_job("silver_suspend_d_update_job", selection=(
            dg.AssetSelection.assets(daily) | dg.AssetSelection.checks_for_assets(daily)
            | dg.AssetSelection.checks_for_assets(silver_stock_suspend_confirmed.key)))],
        resources=resources,
    )
    queries, sql_counts, storage_faults = [], {"describe": 0, "count": 0, "decode": 0}, []
    connect_calls = []
    original_connect = type(resources["duckdb"]).connect

    @contextmanager
    def observed_connect(resource):
        connect_calls.append(True)
        if problem == "resource":
            raise duckdb.OutOfMemoryException("synthetic resource exhausted")
        with original_connect(resource) as conn:
            def execute(sql, *args, **kwargs):
                kind = "describe" if sql.startswith("DESCRIBE SELECT") else "count" if sql.startswith("SELECT count(*) FROM read_parquet") else "decode" if sql.startswith("CREATE OR REPLACE TEMP TABLE") else None
                if kind:
                    sql_counts[kind] += 1
                if problem == "decode" and kind == "decode":
                    raise duckdb.IOException("synthetic decode failure")
                return conn.execute(sql, *args, **kwargs)
            yield Mock(execute=execute)

    original_inspect = contract.inspect_confirmed_file

    def inspect(conn, target):
        if problem == "disappeared":
            # Exact post-preflight IO fault in both adapters; physical rename is
            # independently tested in C09, avoiding order-dependent second failures.
            raise FileNotFoundError("synthetic input disappeared after preflight")
        observed = original_inspect(conn, target)
        if problem == "drift":
            return replace(observed, file_identity=replace(observed.file_identity, mtime_ns=0))
        return observed

    if problem == "oversize":
        identity = contract.suspend_file_identity
        monkeypatch.setattr(contract, "suspend_file_identity",
                            lambda p: replace(identity(p), size=100 * 1024**2 + 1) if p == path else identity(p))
    fetch = instance.fetch_materializations

    def observed_fetch(records_filter, *, limit):
        queries.append({"limit": limit, "asset": records_filter.asset_key.to_user_string()})
        return fetch(records_filter, limit=limit)

    store_event = instance.event_log_storage.store_event

    def fail_check_event(event):
        if event.dagster_event and event.dagster_event.event_type_value == "ASSET_CHECK_EVALUATION":
            assert sql_counts["decode"] > 0
            storage_faults.append("synthetic check storage failure")
            raise RuntimeError("synthetic check storage failure")
        return store_event(event)

    lake_before = _lake_inventory(fixed_lake)
    with monkeypatch.context() as runtime:
        health = Mock(side_effect=AssertionError("health probe is forbidden"))
        runtime.setattr(LakeRootResource, "ensure_available_for_run", health)
        runtime.setattr(type(resources["duckdb"]), "connect", observed_connect)
        runtime.setattr(contract, "inspect_confirmed_file", inspect)
        runtime.setattr(instance, "fetch_materializations", observed_fetch)
        runless = Mock(side_effect=AssertionError("daily runless is forbidden"))
        runtime.setattr(instance, "report_runless_asset_event", runless)
        if problem == "storage_failure":
            runtime.setattr(instance.event_log_storage, "store_event", fail_check_event)
        result = definitions.resolve_job_def("silver_suspend_d_update_job").execute_in_process(
            instance=instance, partition_key=DAY, raise_on_error=False,
            run_config={"loggers": {"console": {"config": {"log_level": "CRITICAL"}}}},
        )
        assert health.call_count == runless.call_count == 0

    after = asdict(contract.suspend_file_identity(sentinel))
    evaluations = result.get_asset_check_evaluations()
    failures = [event.event_specific_data for event in result.all_events if event.is_step_failure]
    failure_metadata = [{key: value.value for key, value in data.user_failure_data.metadata.items()}
                        for data in failures if data.user_failure_data]
    stored = {}
    for name in contract.STOCK_SUSPEND_CONFIRMED_CHECKS:
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(silver_stock_suspend_confirmed.key, name), limit=1)
        assert len(history) == 1 and history[0].run_id == result.run_id
        record = history[0]
        evaluation = record.evaluation if record.status.value != "PLANNED" else None
        stored[name] = {"status": record.status.value, "partition": record.partition,
                        "run_id": record.run_id, "evaluation": None}
        if evaluation:
            target = evaluation.target_materialization_data
            assert evaluation.partition is None and record.partition is None
            assert evaluation.severity == dg.AssetCheckSeverity.ERROR and evaluation.blocking
            assert target.storage_id == published.storage_id and target.run_id == published.event_log_entry.run_id
            assert target.timestamp == published.timestamp
            stored[name]["evaluation"] = {"passed": evaluation.passed,
                "metadata": {k: v.value for k, v in evaluation.metadata.items()},
                "target": {"storage_id": target.storage_id, "run_id": target.run_id, "timestamp": target.timestamp}}
    evidence = {"synthetic": True, "problem": problem, "run_id": result.run_id, "success": result.success,
        "queries": queries, "connections": len(connect_calls), "sql": sql_counts,
        "health_calls": 0, "runless_calls": 0, "writer_calls": len(called),
        "failure_metadata": failure_metadata, "storage_faults": storage_faults,
        "stored_checks": stored, "sentinel_before": before, "sentinel_after": after,
        "lake_unchanged": lake_before == _lake_inventory(fixed_lake),
        "sentinel_unchanged": before == after and sentinel.read_bytes() == before_bytes}
    (tmp_path / "adapter-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"adapter_case": problem, "evidence": str(tmp_path / "adapter-evidence.json")}), flush=True)
    assert result.success == (problem == "ok")
    assert evidence["lake_unchanged"]
    assert called == (["writer"] if problem == "ok" else [])
    assert evidence["sentinel_unchanged"] == (problem != "ok")
    # The budget is for the two confirmed adapters, not SDK target lookups for
    # the three downstream fixture checks. Retain all queries in the evidence.
    fixed_queries = [query for query in queries if query["asset"] == contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY]
    assert all(query["limit"] == 1 and query["asset"] in (
        contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY, "silver_stock_suspend_daily") for query in queries)
    assert len(fixed_queries) == (0 if stage == "input_path" else 2)
    assert [query for query in queries if query not in fixed_queries] == (
        [{"limit": 1, "asset": "silver_stock_suspend_daily"}] * 6 if problem == "ok" else [])
    assert len(instance.fetch_materializations(silver_stock_suspend_confirmed.key, limit=2).records) == (0 if published is None else 1)
    if stage:
        assert not evaluations and failure_metadata
        assert all(item["goldenshare/failure_stage"] == stage and item["goldenshare/reason_code"] == reason for item in failure_metadata)
        assert all("goldenshare/checked_row_count" not in item for item in failure_metadata)
        assert all(item["evaluation"] is None for item in stored.values())
        if stage in ("input_path", "publication"):
            assert not connect_calls and sql_counts == {"describe": 0, "count": 0, "decode": 0}
    elif problem == "storage_failure":
        assert storage_faults and not called
        assert all(item["evaluation"] is None for item in stored.values())
        assert any("synthetic check storage failure" in str(failure.error) for failure in failures)
    else:
        actual = {item.check_name: item for item in evaluations}
        schema, content = (actual[name] for name in contract.STOCK_SUSPEND_CONFIRMED_CHECKS)
        assert schema.passed == (problem != "bad_schema") and content.passed == (problem == "ok")
        expected = {"ok": "ok", "bad_schema": "schema_mismatch", "bad_content": "approved_content_mismatch",
                    "zero": "row_count_mismatch", "short": "row_count_mismatch", "over": "row_count_mismatch",
                    "invalid_domain": "invalid_values_or_keys"}[problem]
        assert content.metadata["goldenshare/reason_code"].value == expected
        for evaluation in (schema, content):
            assert evaluation.metadata["goldenshare/failure_stage"].value == (None if evaluation.passed else "validation")
        if problem == "bad_content":
            assert schema.metadata[CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY].value == content.metadata[CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY].value
            assert content.metadata[CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY].value != contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
        if problem in ("over", "bad_schema"):
            assert sql_counts["decode"] == 0
            assert schema.metadata[CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY].value is None
        else:
            assert sql_counts["decode"] == (1 if problem in ("zero", "short") else 2)
        if problem == "ok":
            assert len(evaluations) == 5 and all(item["status"] == "SUCCEEDED" for item in stored.values())
            assert all(item.partition == DAY for item in evaluations if item.check_name.startswith("fixture_"))


@pytest.mark.parametrize("problem,stage,reason", [
    ("missing_root", "input_path", "root_unavailable"), ("missing_file", "input_path", "input_missing"),
    ("directory", "input_path", "invalid_path"), ("escape", "input_path", "invalid_path"),
    ("symlink", "input_path", "invalid_path"), ("no_materialization", "publication", "publication_missing"),
    ("partition", "publication", "publication_partition_mismatch"), ("uri", "publication", "publication_uri_mismatch"),
    ("version", "publication", "publication_version_mismatch"), ("hash", "publication", "publication_hash_mismatch"),
])
def test_path_and_publication_failures(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, stage, reason):
    _case(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, stage=stage, reason=reason)


@pytest.mark.parametrize("problem", ["ok", "bad_content", "zero", "short", "over", "bad_schema", "corrupt", "storage_failure", "invalid_domain"])
def test_validation_and_storage(instance, fixed_lake, tmp_path, connection, monkeypatch, problem):
    kwargs = {"stage": "validation", "reason": "parquet_read_error"} if problem == "corrupt" else {}
    _case(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, **kwargs)


@pytest.mark.parametrize("problem,stage,reason", [
    ("oversize", "input_resource", "size_exceeded"), ("resource", "input_resource", "resource_exhausted"),
    ("disappeared", "validation", "input_disappeared"), ("drift", "validation", "input_drift"),
    ("decode", "validation", "parquet_read_error"),
])
def test_input_error_classification(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, stage, reason):
    _case(instance, fixed_lake, tmp_path, connection, monkeypatch, problem, stage=stage, reason=reason)
