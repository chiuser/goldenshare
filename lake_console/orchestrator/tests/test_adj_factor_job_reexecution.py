"""Native isolated Silver job, original checks and failure reexecution.

Uses the real three-column Raw / ten-column lifecycle producer contracts.
Dagster execute_job/reconstructable/from_failure and the persistent instance are
real; only the DuckDB temp location and one failed receipt write are controlled.
"""

import json
from contextlib import contextmanager
from dataclasses import replace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.assets import adj_factor as asset_module
from orchestrator.defs.checks import adj_factor_checks as checks_module
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)
from orchestrator.defs.io import adj_factor_silver_publication as publication
from orchestrator.defs.jobs.stock_adj_factor_update import silver_adj_factor_update_job
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_adj_factor_publication_root,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource

OLD = "2026-10-22"
DAY = "2026-10-28"
KEYS = [{"ts_code": "301139.SZ", "trade_date": OLD}]
CHECK_NAMES = {
    "silver_adj_factor_contract_check",
    "silver_adj_factor_key_value_integrity_check",
    "silver_adj_factor_lifecycle_coverage_check",
    "silver_adj_factor_partition_allowed_check",
}


def native_silver_factor_job():
    """Module-scope factory required by Dagster reconstructable()."""
    return dg.Definitions(
        assets=[asset_module.silver_adj_factor,
                dg.AssetSpec("raw_tushare_adj_factor"),
                dg.AssetSpec("silver_stock_lifecycle")],
        asset_checks=[checks_module.silver_adj_factor_contract_check,
                      checks_module.silver_adj_factor_key_value_integrity_check,
                      checks_module.silver_adj_factor_lifecycle_coverage_check,
                      checks_module.silver_adj_factor_partition_allowed_check],
        jobs=[silver_adj_factor_update_job],
        resources={"lake_root": LakeRootResource(), "duckdb": DuckDBResource()},
        executor=dg.in_process_executor,
    ).resolve_job_def("silver_adj_factor_update_job")


def _copy(con, sql, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")


@pytest.fixture
def isolated_job(tmp_path, monkeypatch):
    root, stage, temp = tmp_path / "lake", tmp_path / "staging", tmp_path / "duckdb"
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True)
    stage.mkdir()
    temp.mkdir()
    settings = replace(DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=temp)
    temp_seen = []

    @contextmanager
    def connection():
        with connect_configured_duckdb(settings) as con:
            temp_seen.append(con.execute("SELECT current_setting('temp_directory')").fetchone()[0])
            yield con

    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(stage))
    monkeypatch.setattr(asset_module, "connect_configured_duckdb", connection)
    monkeypatch.setattr(checks_module, "connect_configured_duckdb", connection)
    with duckdb.connect(":memory:") as con:
        _copy(con, """SELECT ts_code,symbol,name,exchange,market,curr_type,is_cny_stock,
          list_status,CAST(list_date AS DATE) list_date,CAST(delist_date AS DATE) delist_date
          FROM (VALUES
          ('000001.SZ','000001','平安','SZSE','主板','CNY',true,'L','1991-04-03',NULL),
          ('301139.SZ','301139','元道','SZSE','创业板','CNY',true,'D','2022-07-08','2026-10-28'),
          ('600002.SH','600002','历史退市','SSE','主板','CNY',true,'D','1990-01-01','2020-01-01')
          ) t(ts_code,symbol,name,exchange,market,curr_type,is_cny_stock,
              list_status,list_date,delist_date)""", silver_stock_lifecycle_path(root))
        for day, value in ((OLD, "1.0079"), (DAY, "1.1319")):
            _copy(con, f"""SELECT ts_code,'{day.replace('-', '')}'::VARCHAR trade_date,
              adj_factor::DOUBLE adj_factor FROM (VALUES
              ('000001.SZ',1.5),('301139.SZ',{value}),('600002.SH',2.0)) t(ts_code,adj_factor)""",
                  raw_adj_factor_path(root, day))
        _copy(con, f"SELECT '000001.SZ'::VARCHAR ts_code,DATE '{OLD}' trade_date,1.5::DOUBLE adj_factor",
              silver_adj_factor_path(root, OLD))
    instance_dir = tmp_path / "dagster_instance"
    instance_dir.mkdir()
    (instance_dir / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_dir), overrides={"telemetry": {"enabled": False}}) as instance:
        instance.add_dynamic_partitions(cn_a_stock_current_trade_days.name, [OLD, DAY])

        def forbid_global_instance(*args, **kwargs):
            raise AssertionError("Only the explicitly supplied isolated instance may be used")

        monkeypatch.setattr(dg.DagsterInstance, "get", forbid_global_instance)
        yield root, stage, instance
    assert temp_seen
    assert set(temp_seen) == {str(temp)}


def _config(root, *, keys=()):
    return {
        "resources": {"lake_root": {"config": {"root_path": str(root)}}},
        "ops": {"silver_adj_factor": {"config": {"restore_missing_keys": list(keys)}}},
    }


def _rows(root, day):
    with duckdb.connect(":memory:") as con:
        return con.execute("SELECT ts_code,adj_factor FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                           [str(silver_adj_factor_path(root, day))]).fetchall()


def _assert_native_delivery(instance, run_id, day):
    records = instance.get_records_for_run(run_id).records
    materials = [record for record in records if record.event_log_entry.dagster_event
                 and record.event_log_entry.dagster_event.event_type_value == "ASSET_MATERIALIZATION"]
    checks = [record.event_log_entry.dagster_event.event_specific_data
              for record in records if record.event_log_entry.dagster_event
              and record.event_log_entry.dagster_event.event_type_value == "ASSET_CHECK_EVALUATION"]
    assert len(materials) == 1
    # SQLite mirrors asset events to a global index. Per-run event-record ids
    # belong to a different shard and are not valid target-materialization ids
    # (sqlite_event_log.py:store_event / fetch_materializations).
    indexed = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey("silver_adj_factor"), asset_partitions=[day]),
        limit=10,
    ).records
    target_materials = [record for record in indexed if record.event_log_entry.run_id == run_id]
    assert len(target_materials) == 1
    material = target_materials[0]
    assert material.event_log_entry.dagster_event.event_specific_data.materialization.partition == day
    assert {check.check_name for check in checks} == CHECK_NAMES
    assert len(checks) == 4
    for check in checks:
        assert check.passed
        assert check.asset_key == dg.AssetKey("silver_adj_factor")
        assert check.target_materialization_data.run_id == run_id
        assert check.target_materialization_data.storage_id == material.storage_id
    return {"materialization_storage_id": material.storage_id,
            "check_names": sorted(check.check_name for check in checks),
            "check_target_storage_ids": [check.target_materialization_data.storage_id for check in checks]}


def test_real_silver_asset_and_four_native_checks(isolated_job):
    root, stage, instance = isolated_job
    assert native_silver_factor_job().executor_def.name == "in_process"
    result = dg.execute_job(
        dg.reconstructable(native_silver_factor_job), instance=instance,
        run_config=_config(root), tags={"dagster/partition": DAY}, raise_on_error=False,
    )
    assert result.success
    assert _rows(root, DAY) == [("000001.SZ", 1.5), ("301139.SZ", 1.1319), ("600002.SH", 2.0)]
    delivery = _assert_native_delivery(instance, result.run_id, DAY)
    control = silver_adj_factor_publication_root(stage, result.run_id, DAY) / "publication.json"
    assert json.loads(control.read_text())["phase"] == "committed"
    (root.parent / "native_normal_evidence.json").write_text(json.dumps({
        "api": "execute_job(reconstructable(module_scope_factory))",
        "run_id": result.run_id, "status": "SUCCESS", "date": DAY,
        "publication_root_run_id": result.run_id, "delivery": delivery,
    }, indent=2))


def test_native_reexecution_recovers_committed_file_without_rebuild(isolated_job, monkeypatch):
    root, stage, instance = isolated_job
    target = silver_adj_factor_path(root, OLD)
    raw_before = raw_adj_factor_path(root, OLD).read_bytes()
    lifecycle_before = silver_stock_lifecycle_path(root).read_bytes()
    real_checkpoint = publication._checkpoint
    real_candidate = asset_module.build_silver_adj_factor_candidate
    real_replace = publication.os.replace
    calls = {"candidates": 0, "promotions": 0, "receipt_failures": 0}

    def counted_candidate(*args, **kwargs):
        calls["candidates"] += 1
        return real_candidate(*args, **kwargs)

    def counted_replace(source, destination):
        if str(destination) == str(target):
            calls["promotions"] += 1
        return real_replace(source, destination)

    def fail_first_commit(path, state):
        if state["phase"] == "committed" and calls["receipt_failures"] == 0:
            calls["receipt_failures"] += 1
            raise OSError("isolated commit receipt failure after replace")
        return real_checkpoint(path, state)

    monkeypatch.setattr(asset_module, "build_silver_adj_factor_candidate", counted_candidate)
    monkeypatch.setattr(publication.os, "replace", counted_replace)
    monkeypatch.setattr(publication, "_checkpoint", fail_first_commit)
    recon = dg.reconstructable(native_silver_factor_job)
    first = dg.execute_job(recon, instance=instance, run_config=_config(root, keys=KEYS),
                           tags={"dagster/partition": OLD}, raise_on_error=False)
    assert not first.success
    first_run = instance.get_run_by_id(first.run_id)
    assert first_run.status == dg.DagsterRunStatus.FAILURE
    assert _rows(root, OLD) == [("000001.SZ", 1.5), ("301139.SZ", 1.0079)]
    published_identity = publication.file_identity(target)
    control = silver_adj_factor_publication_root(stage, first.run_id, OLD) / "publication.json"
    assert json.loads(control.read_text())["phase"] == "prepared"
    assert calls == {"candidates": 1, "promotions": 1, "receipt_failures": 1}

    def forbid_rebuild(*args, **kwargs):
        raise AssertionError("Native reexecution must recover the existing publication, not rebuild")

    monkeypatch.setattr(asset_module, "build_silver_adj_factor_candidate", forbid_rebuild)
    # Native API inherits the parent's run_config and creates real parent/root
    # links. Partition tags are explicitly carried as in the formal retry API.
    second = dg.execute_job(
        recon, instance=instance, tags=dict(first_run.tags), raise_on_error=False,
        reexecution_options=dg.ReexecutionOptions.from_failure(first.run_id, instance),
    )
    assert second.success
    second_run = instance.get_run_by_id(second.run_id)
    assert second_run.parent_run_id == first.run_id
    assert second_run.root_run_id == first.run_id
    assert second_run.run_config == first_run.run_config
    assert second_run.status == dg.DagsterRunStatus.SUCCESS
    assert publication.file_identity(target) == published_identity
    assert calls == {"candidates": 1, "promotions": 1, "receipt_failures": 1}
    assert json.loads(control.read_text())["phase"] == "committed"
    assert not silver_adj_factor_publication_root(stage, second.run_id, OLD).exists()
    assert raw_adj_factor_path(root, OLD).read_bytes() == raw_before
    assert silver_stock_lifecycle_path(root).read_bytes() == lifecycle_before
    delivery = _assert_native_delivery(instance, second.run_id, OLD)
    (root.parent / "native_reexecution_evidence.json").write_text(json.dumps({
        "api": "execute_job + ReexecutionOptions.from_failure",
        "parent_run_id": first.run_id, "parent_status": first_run.status.value,
        "retry_run_id": second.run_id, "retry_status": second_run.status.value,
        "retry_root_run_id": second_run.root_run_id,
        "retry_parent_run_id": second_run.parent_run_id,
        "publication_root_run_id": first.run_id, "calls": calls,
        "file_identity_unchanged_after_retry": publication.file_identity(target) == published_identity,
        "raw_unchanged": raw_adj_factor_path(root, OLD).read_bytes() == raw_before,
        "lifecycle_unchanged": silver_stock_lifecycle_path(root).read_bytes() == lifecycle_before,
        "delivery": delivery,
    }, indent=2))
