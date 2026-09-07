"""Actual daily writer, original final checks and native storage, inside the fixed runner."""

from stock_suspend_confirmed_test_support import (
    checked_test_path,
    connect_confirmed_test_duckdb,
    make_confirmed_test_instance,
    make_confirmed_test_resources,
    require_isolated_context,
)

ALLOWED = require_isolated_context()

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import pytest

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.assets import suspend_d as writer
from orchestrator.defs.assets.stock_suspend_confirmed import (
    silver_stock_suspend_confirmed,
)
from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG
from orchestrator.defs.checks import stock_partition_checks, suspend_d_checks
from orchestrator.defs.checks import stock_suspend_confirmed_checks as fixed_checks
from orchestrator.defs.jobs.suspend_update import silver_suspend_d_update_job
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    raw_suspend_d_path,
    silver_stock_suspend_confirmed_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY as HASH,
)
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_VERSION_METADATA_KEY as VERSION,
)
from orchestrator.defs.sensors.readiness import stock_suspend_confirmed_readiness

FIXED = (fixed_checks.silver_stock_suspend_confirmed_schema_check,
         fixed_checks.silver_stock_suspend_confirmed_approved_content_check)
FINAL = (suspend_d_checks.silver_suspend_d_key_integrity_check,
         suspend_d_checks.silver_suspend_d_suspend_type_domain_check,
         stock_partition_checks.silver_suspend_d_partition_allowed_check)


@pytest.mark.parametrize("case", ["ok", "empty", "duplicate", "conflict", "bad_content", "bad_schema", "no_publication", "bad_uri", "bypass"])
def test_actual_silver_job(case, fixed_lake, connection, tmp_path, monkeypatch, capsys):
    day = "2020-01-03" if case == "empty" else "2020-01-02"
    raw = raw_suspend_d_path(fixed_lake, day)
    raw.parent.mkdir(parents=True)
    connection.execute("CREATE TEMP TABLE raw_fixture(ts_code VARCHAR, trade_date VARCHAR, suspend_timing VARCHAR, suspend_type VARCHAR)")
    if case == "duplicate":
        connection.execute("INSERT INTO raw_fixture VALUES ('000001.SZ','20200102',NULL,'S'), ('000001.SZ','20200102',NULL,'S')")
    elif case == "conflict":
        connection.execute("INSERT INTO raw_fixture VALUES ('000001.SZ','20200102','09:30-10:00','S')")
    connection.execute("COPY raw_fixture TO ? (FORMAT PARQUET)", [str(raw)])
    raw_before = asdict(contract.suspend_file_identity(raw)), raw.read_bytes()
    target = silver_stock_suspend_daily_path(fixed_lake, day)
    target.parent.mkdir(parents=True)
    connection.execute("COPY (SELECT '000009.SZ'::VARCHAR ts_code, DATE '2020-01-02' trade_date, NULL::VARCHAR suspend_timing, 'R'::VARCHAR suspend_type) TO ? (FORMAT PARQUET)", [str(target)])
    target_before = target.read_bytes()
    resources = make_confirmed_test_resources(lake_root=fixed_lake, work_root=ALLOWED)
    staging = checked_test_path(tmp_path / "staging", allowed=ALLOWED)
    staging.mkdir()
    # Only these reviewed aliases may connect; the shared/default entry remains rejected.
    temporary_connect = lambda: connect_confirmed_test_duckdb(temp_directory=ALLOWED / "duckdb-temp")
    monkeypatch.setattr(writer, "connect_configured_duckdb", temporary_connect)
    monkeypatch.setattr(suspend_d_checks, "connect_configured_duckdb", temporary_connect)
    monkeypatch.setattr(writer, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    calls = []
    actual_writer = writer.write_silver_stock_suspend_daily_partition

    def observed_writer(*args, **kwargs):
        assert kwargs["lake_root"] == fixed_lake and kwargs["staging_root"] == staging
        calls.append(day)
        return actual_writer(*args, **kwargs)

    monkeypatch.setattr(writer, "write_silver_stock_suspend_daily_partition", observed_writer)
    with make_confirmed_test_instance(instance_root=tmp_path / "instance") as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, [day])
        path = silver_stock_suspend_confirmed_path(fixed_lake)
        if case != "no_publication":
            instance.report_runless_asset_event(dg.AssetMaterialization(
                asset_key=silver_stock_suspend_confirmed.key,
                metadata={VERSION: contract.STOCK_SUSPEND_CONFIRMED_VERSION,
                          HASH: contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256,
                          "dagster/uri": "wrong" if case == "bad_uri" else str(path)},
            ))
        published = instance.fetch_materializations(silver_stock_suspend_confirmed.key, limit=1).records
        if case in ("ok", "empty"):
            for name, schema_only in zip(contract.STOCK_SUSPEND_CONFIRMED_CHECKS, (True, False), strict=True):
                events = list(fixed_checks._evaluate_confirmed_check(
                    SimpleNamespace(instance=instance), resources["lake_root"], resources["duckdb"],
                    check_name=name, schema_only=schema_only,
                ))
                assert events[0].passed
                instance.report_runless_asset_event(events[0])
        if case in ("bad_content", "bypass"):
            connection.execute("CREATE TEMP TABLE changed AS SELECT * FROM read_parquet(?)", [str(path)])
            connection.execute("UPDATE changed SET ts_code='000002.SZ' WHERE ts_code='000001.SZ'")
            connection.execute("COPY changed TO ? (FORMAT PARQUET)", [str(path)])
        elif case == "bad_schema":
            connection.execute("COPY (SELECT 1 wrong) TO ? (FORMAT PARQUET)", [str(path)])
        fixed_before = asdict(contract.suspend_file_identity(path)), path.read_bytes()
        runless = Mock(side_effect=AssertionError("daily job must not write runless events"))
        monkeypatch.setattr(instance, "report_runless_asset_event", runless)
        job_definition = silver_suspend_d_update_job
        if case == "bypass":
            job_definition = dg.define_asset_job("bypass", selection=dg.AssetSelection.assets(writer.silver_stock_suspend_daily).without_checks())
        definitions = dg.Definitions(
            assets=[writer.raw_tushare_suspend_d.get_asset_spec(), silver_stock_suspend_confirmed,
                    writer.silver_stock_suspend_daily],
            asset_checks=[*FIXED, *FINAL], jobs=[job_definition], resources=resources,
        )
        graph = definitions.resolve_asset_graph()
        assert job_definition.selection.resolve(graph) == {writer.silver_stock_suspend_daily.key}
        expected_checks = {spec.key for definition in (*FIXED, *FINAL) for spec in definition.check_specs}
        assert job_definition.selection.resolve_checks(graph) == (set() if case == "bypass" else expected_checks)
        for definition in FINAL:
            assert next(iter(definition.check_specs)).partitions_def == cn_a_stock_trade_days
        for definition in FIXED:
            assert next(iter(definition.check_specs)).partitions_def is None
        assert silver_stock_suspend_confirmed.partitions_def is None
        result = definitions.resolve_job_def(job_definition.name).execute_in_process(
            instance=instance, partition_key=day, raise_on_error=False,
            run_config={"loggers": {"console": {"config": {"log_level": "CRITICAL"}}}},
        )
        assert result.success == (case in ("ok", "empty"))
        expected_calls = 1 if case in ("ok", "empty", "duplicate", "conflict", "bypass") else 0
        assert len(calls) == expected_calls
        assert (asdict(contract.suspend_file_identity(raw)), raw.read_bytes()) == raw_before
        assert (asdict(contract.suspend_file_identity(path)), path.read_bytes()) == fixed_before
        assert not runless.called
        events = result.get_asset_check_evaluations()
        if case in ("ok", "empty", "duplicate"):
            assert len(events) == 5
            for evaluation in events:
                fixed = evaluation.asset_key == silver_stock_suspend_confirmed.key
                assert evaluation.partition == (None if fixed else day)
                check_key = dg.AssetCheckKey(evaluation.asset_key, evaluation.check_name)
                stored = instance.event_log_storage.get_asset_check_execution_history(check_key, limit=1)[0]
                assert stored.partition == evaluation.partition
                assert stored.run_id == result.run_id
                if fixed:
                    assert evaluation.target_materialization_data.storage_id == published[0].storage_id
            steps = [event for event in result.all_events if event.is_step_start or event.event_type_value == "ASSET_CHECK_EVALUATION"]
            writer_start = next(i for i, event in enumerate(steps) if event.is_step_start and event.step_key == "silver_stock_suspend_daily")
            assert all(i < writer_start for i, event in enumerate(steps) if event.event_type_value == "ASSET_CHECK_EVALUATION" and event.event_specific_data.asset_key == silver_stock_suspend_confirmed.key)
            assert all(i > writer_start for i, event in enumerate(steps) if event.event_type_value == "ASSET_CHECK_EVALUATION" and event.event_specific_data.asset_key == writer.silver_stock_suspend_daily.key)
            rows = connection.execute("SELECT ts_code, trade_date::VARCHAR, suspend_timing, suspend_type FROM read_parquet(?, hive_partitioning=false)", [str(target)]).fetchall()
            assert rows == ([] if case == "empty" else [("000001.SZ", day, None, "S")] * (2 if case == "duplicate" else 1))
            status = stock_suspend_confirmed_readiness(instance, connection, lake_root=fixed_lake)
            assert status.ready and status.materialization_storage_id == published[0].storage_id
            if case == "duplicate":
                assert {e.check_name for e in events if not e.passed} == {"silver_suspend_d_key_integrity_check"}
        else:
            assert target.read_bytes() == target_before
            if case == "bad_content":
                assert any(e.check_name.endswith("approved_content_check") and not e.passed for e in events)
            if case == "bad_schema":
                assert all(not e.passed for e in events)
        assert len(instance.fetch_materializations(silver_stock_suspend_confirmed.key, limit=2).records) == len(published)
        output = capsys.readouterr().out
        if case in ("bypass", "conflict"):
            assert "event=silver_suspend_d_validation_failed" in output
        if case == "conflict":
            assert "reason_code=confirmed_raw_conflict" in output
        evidence = {"case": case, "run_id": result.run_id, "success": result.success,
                    "writer_calls": len(calls), "synthetic": True, "raw_unchanged": True,
                    "fixed_unchanged": True, "checks": [{"name": e.check_name, "passed": e.passed,
                    "partition": e.partition, "target_id": e.target_materialization_data.storage_id
                    if e.target_materialization_data else None} for e in events]}
        (tmp_path / "integration-evidence.json").write_text(json.dumps(evidence) + "\n")
        print(json.dumps({"integration_case": case, "evidence": str(tmp_path / "integration-evidence.json")}))


def test_actual_catalog_registration():
    matches = [entry for entry in LAKE_ASSET_CATALOG if entry.asset_key == contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY]
    assert len(matches) == 1
