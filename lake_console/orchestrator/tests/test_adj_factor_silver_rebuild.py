"""Only temporary Lake/staging fixtures; production resources and network are unused."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.assets.adj_factor import silver_adj_factor
from orchestrator.defs.bootstrap import adj_factor_silver_history as history
from orchestrator.defs.checks import adj_factor_checks as checks
from orchestrator.defs.jobs.stock_adj_factor_update import silver_adj_factor_update_job
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import silver_adj_factor_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from tests.test_adj_factor_checks import (
    _write_raw_adj_factor_file,
    _write_silver_adj_factor_file,
    _write_silver_stock_lifecycle_file,
)

DAYS = ("2020-02-28", "2020-03-02", "2020-03-03")


@pytest.fixture
def rebuild_fixture(tmp_path):
    root = tmp_path.resolve() / "lake"
    run = tmp_path.resolve() / "staging/run"
    temp = tmp_path.resolve() / "duckdb"
    temp.mkdir()
    _write_silver_stock_lifecycle_file(root, (
        ("000001.SZ", "CNY", "L", "2010-01-01", None),
        ("000002.SZ", "CNY", "D", "2010-01-01", "2026-06-30"),
    ))
    for day in (*DAYS, "2020-03-04"):
        _write_raw_adj_factor_file(root, day, (
            ("000001.SZ", day.replace("-", ""), 1.12345678),
            ("000002.SZ", day.replace("-", ""), 2.25),
        ))
    for day in DAYS:
        rows = (("000001.SZ", day, 1.12345678),)
        if day != DAYS[-1]:
            rows += (("000002.SZ", day, 2.25),)
        _write_silver_adj_factor_file(root, day, rows)
    sentinel = root / "gold/untouched.bin"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"No quote or indicator writes")
    return root, run, temp


def _snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in root.rglob("*") if path.is_file()}


def _plan(fixture):
    root, _, temp = fixture
    with patch.object(history, "silver_stock_lifecycle_ready_for_trade_date",
                      return_value=SimpleNamespace(ready=True)):
        return history.plan_silver_adj_factor_rebuild(
            lake_root=root, temp_directory=temp, instance=object(),
            listing_as_of_date="2026-10-13",
        )


def _definitions(root):
    return dg.Definitions(
        assets=[silver_adj_factor, dg.AssetSpec("raw_tushare_adj_factor"),
                dg.AssetSpec("silver_stock_lifecycle")],
        asset_checks=[checks.silver_adj_factor_contract_check,
                      checks.silver_adj_factor_key_value_integrity_check,
                      checks.silver_adj_factor_lifecycle_coverage_check,
                      checks.silver_adj_factor_partition_allowed_check],
        jobs=[silver_adj_factor_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(root)), "duckdb": DuckDBResource()},
    )


def test_plan_and_candidates_never_modify_raw_silver_or_other_data(rebuild_fixture):
    root, run, _ = rebuild_fixture
    before = _snapshot(root)
    plan = _plan(rebuild_fixture)
    assert len(plan.raw_inputs) == 4
    assert len(plan.units) == 3
    assert sum(unit.removed_rows for unit in plan.units) == 2
    assert _snapshot(root) == before
    history.freeze_silver_adj_factor_rebuild(plan, run)
    assert history.load_silver_adj_factor_rebuild(run) == plan
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    assert len(list((run / "candidates").rglob("*.parquet"))) == 2
    assert _snapshot(root) == before
    for candidate in (run / "candidates").rglob("*.parquet"):
        with duckdb.connect() as connection:
            assert connection.execute("SELECT ts_code,adj_factor FROM read_parquet(?)",
                                      [str(candidate)]).fetchall() == [("000001.SZ", 1.12345678)]


def test_cancel_resume_and_idempotence_preserve_all_non_silver_files(rebuild_fixture):
    root, run, _ = rebuild_fixture
    before = _snapshot(root)
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    with pytest.raises(history.AdjFactorSilverRebuildError, match="maintenance_required"):
        history.promote_silver_adj_factor_rebuild(plan, run)

    def stop_after_first(completed, total):
        if completed == 1:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True,
                                                progress=stop_after_first)
    assert _snapshot(root)[str(silver_adj_factor_path(root, DAYS[1]).relative_to(root))] == before[
        str(silver_adj_factor_path(root, DAYS[1]).relative_to(root))]
    history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    after = _snapshot(root)
    history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    assert _snapshot(root) == after
    for relative, identity in before.items():
        if not relative.startswith("silver/quote/adj_factor/") or DAYS[-1] in relative:
            assert after[relative] == identity
    assert json.loads((run / "audit.json").read_text())["removed_rows"] == 2


def test_checkpoint_failure_after_replace_is_safely_recovered(rebuild_fixture):
    _, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    writer = history._rebuild_write_json

    def fail_promoted_checkpoint(path, payload):
        if "promoted" in path.parts:
            raise OSError("checkpoint failed")
        writer(path, payload)

    with patch.object(history, "_rebuild_write_json", fail_promoted_checkpoint), \
            pytest.raises(OSError, match="checkpoint failed"):
        history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    assert not (run / "candidates" / Path(plan.units[0].silver.path).relative_to(plan.lake_root)).exists()
    history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    assert history.verify_silver_adj_factor_rebuild(plan, run)["status"] == "files_verified"


def test_corrupt_later_candidate_blocks_all_formal_writes(rebuild_fixture):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    before = _snapshot(root)
    candidates = sorted((run / "candidates").rglob("*.parquet"))
    candidates[-1].write_bytes(b"bad candidate")
    with pytest.raises(history.AdjFactorSilverRebuildError, match="candidate_drift"):
        history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    assert _snapshot(root) == before


@pytest.mark.parametrize("target", ["raw", "silver", "lifecycle"])
def test_external_file_drift_is_rejected(rebuild_fixture, target):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    if target == "raw":
        path = Path(plan.units[0].raw.path)
    elif target == "silver":
        path = Path(plan.units[0].silver.path)
    else:
        path = Path(plan.lifecycle.path)
    path.write_bytes(path.read_bytes() + b"changed externally")
    before = _snapshot(root)
    with pytest.raises(history.AdjFactorSilverRebuildError, match="input_drift"):
        history.build_silver_adj_factor_rebuild_candidates(plan, run)
    assert _snapshot(root) == before


@pytest.mark.parametrize("factor", [3.0, None])
def test_current_listed_value_change_is_outside_this_rebuild(rebuild_fixture, factor):
    root, _, _ = rebuild_fixture
    rows = (("000002.SZ", DAYS[0].replace("-", ""), 2.25),)
    if factor is not None:
        rows += (("000001.SZ", DAYS[0].replace("-", ""), factor),)
    _write_raw_adj_factor_file(root, DAYS[0], rows)
    before = _snapshot(root)
    with pytest.raises(history.AdjFactorSilverRebuildError, match="current_listed_values_differ"):
        _plan(rebuild_fixture)
    assert _snapshot(root) == before


def test_incomplete_candidate_stage_cannot_promote_and_build_resumes(rebuild_fixture):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    before = _snapshot(root)

    def stop_after_first(completed, total):
        if completed == 1:
            raise RuntimeError("cancelled build")

    with pytest.raises(RuntimeError, match="cancelled build"):
        history.build_silver_adj_factor_rebuild_candidates(plan, run, progress=stop_after_first)
    with pytest.raises(history.AdjFactorSilverRebuildError, match="full_candidates_not_ready"):
        history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    first_candidate = next((run / "candidates").rglob("*.parquet"))
    first_mtime = first_candidate.stat().st_mtime_ns
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    assert first_candidate.stat().st_mtime_ns == first_mtime
    assert _snapshot(root) == before


def test_candidate_and_record_mutation_during_promote_is_refused(rebuild_fixture):
    _, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    second = plan.units[1]

    def change_next_candidate(completed, total):
        if completed != 1:
            return
        candidate = run / "candidates" / Path(second.silver.path).relative_to(plan.lake_root)
        candidate.write_bytes(b"modified together with record")
        record_path = run / "checkpoints/candidates" / f"{second.partition_key}.json"
        record = json.loads(record_path.read_text())
        record["candidate_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        record_path.write_text(json.dumps(record))

    original_second = Path(second.silver.path).read_bytes()
    with pytest.raises(history.AdjFactorSilverRebuildError, match="candidate_record_drift"):
        history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True,
                                                progress=change_next_candidate)
    assert Path(second.silver.path).read_bytes() == original_second


def test_stale_listing_blocks_read_only_plan(rebuild_fixture):
    root, _, temp = rebuild_fixture
    with patch.object(history, "silver_stock_lifecycle_ready_for_trade_date",
                      return_value=SimpleNamespace(ready=False)), \
            pytest.raises(history.AdjFactorSilverRebuildError, match="listing_not_ready"):
        history.plan_silver_adj_factor_rebuild(lake_root=root, temp_directory=temp,
            instance=object(), listing_as_of_date="2026-10-13")


def test_candidate_budget_staging_scope_and_cancel_do_not_touch_formal(rebuild_fixture):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    before = _snapshot(root)
    with pytest.raises(history.AdjFactorSilverRebuildError, match="staging_inside_lake"):
        history.build_silver_adj_factor_rebuild_candidates(plan, root / "staging")
    with patch.object(history, "REBUILD_MAX_CANDIDATE_BYTES", 0), \
            pytest.raises(history.AdjFactorSilverRebuildError, match="candidate_budget_exceeded"):
        history.build_silver_adj_factor_rebuild_candidates(plan, run)
    assert _snapshot(root) == before

    def cancel():
        raise RuntimeError("cancelled before unit")

    with pytest.raises(RuntimeError, match="cancelled before unit"):
        history.build_silver_adj_factor_rebuild_candidates(plan, run, cancel=cancel)
    assert _snapshot(root) == before


def test_real_checks_only_subset_and_event_binding_without_asset_execution(rebuild_fixture):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    before = _snapshot(root)
    definitions = _definitions(root)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_current_trade_days.name, list(DAYS))
        summary = history.report_silver_adj_factor_rebuild_events(plan, run,
            instance=instance, definitions=definitions, maintenance_confirmed=True)
        assert summary == {"asset_key": "silver_adj_factor", "materializations": 2,
                           "checks": 8, "real_check_runs": 2, "asset_executions": 0}
        first_runs = instance.get_runs_count()
        history.report_silver_adj_factor_rebuild_events(plan, run,
            instance=instance, definitions=definitions, maintenance_confirmed=True)
        assert instance.get_runs_count() == first_runs
        for day in DAYS[:2]:
            assert len(instance.fetch_materializations(dg.AssetRecordsFilter(
                asset_key=dg.AssetKey("silver_adj_factor"), asset_partitions=[day]), limit=10).records) == 1
    assert _snapshot(root) == before


def test_successful_run_with_wrong_check_binding_is_not_treated_as_verified(rebuild_fixture):
    root, run, _ = rebuild_fixture
    plan = _plan(rebuild_fixture)
    history.build_silver_adj_factor_rebuild_candidates(plan, run)
    history.promote_silver_adj_factor_rebuild(plan, run, maintenance_confirmed=True)
    definitions = _definitions(root)
    job = history.silver_adj_factor_rebuild_check_job(definitions)

    def wrong_binding(**kwargs):
        actual = job.execute_in_process(**kwargs)
        evaluations = [SimpleNamespace(check_name=e.check_name, passed=e.passed,
            target_materialization_data=SimpleNamespace(storage_id=-1))
            for e in actual.get_asset_check_evaluations()]
        return SimpleNamespace(success=actual.success, run_id=actual.run_id,
                               get_asset_check_evaluations=lambda: evaluations)

    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_current_trade_days.name, list(DAYS))
        with patch.object(history, "silver_adj_factor_rebuild_check_job",
                          return_value=SimpleNamespace(execute_in_process=wrong_binding)), \
                pytest.raises(history.AdjFactorSilverRebuildError, match="real_checks_failed"):
            history.report_silver_adj_factor_rebuild_events(plan, run, instance=instance,
                definitions=definitions, maintenance_confirmed=True)
        record = json.loads((run / "checkpoints/events" / f"{DAYS[0]}.json").read_text())
        assert record["checks_verified"] is False
        assert instance.get_run_by_id(record["run_id"]).is_success
        history.report_silver_adj_factor_rebuild_events(plan, run, instance=instance,
            definitions=definitions, maintenance_confirmed=True)
        assert instance.get_runs_count() == 3


def test_full_market_multibatch_comparison_stays_within_process_budget(tmp_path):
    import resource
    import sys
    from datetime import date, timedelta

    from orchestrator.defs.duckdb_connection import connect_configured_duckdb
    from orchestrator.defs.duckdb_sql import duckdb_string

    root = tmp_path / 'lake'
    life = history.silver_stock_lifecycle_path(root)
    life.parent.mkdir(parents=True)
    temp = tmp_path / 'temp'
    temp.mkdir()
    days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(256)]
    with connect_configured_duckdb(history._rebuild_settings(temp), temp_policy='existing_no_spill') as connection:
        connection.execute(f"""COPY (
            SELECT printf('%06d.SZ',range) ts_code,true is_cny_stock,'L' list_status,
                DATE '2010-01-01' list_date,NULL::DATE delist_date FROM range(1,5001)
            UNION ALL SELECT '600000.SH',true,'D',DATE '2010-01-01',DATE '2026-01-01'
        ) TO {duckdb_string(life)} (FORMAT PARQUET)""")
        for day in days:
            raw = history.raw_adj_factor_path(root, day)
            silver = history.silver_adj_factor_path(root, day)
            raw.parent.mkdir(parents=True)
            silver.parent.mkdir(parents=True)
            source = f"SELECT ts_code,DATE {duckdb_string(day)} trade_date,1.12345678::DOUBLE adj_factor FROM read_parquet({duckdb_string(life)})"
            connection.execute(f'COPY ({source}) TO {duckdb_string(silver)} (FORMAT PARQUET)')
            connection.execute(f"COPY (SELECT ts_code,strftime(trade_date,'%Y%m%d') trade_date,adj_factor FROM ({source})) TO {duckdb_string(raw)} (FORMAT PARQUET)")
    for offset in range(0, len(days), 64):
        batch = days[offset:offset+64]
        with connect_configured_duckdb(history._rebuild_settings(temp), temp_policy='existing_no_spill') as connection:
            observed = history._rebuild_batch_comparison(connection,
                [history.raw_adj_factor_path(root,d) for d in batch],
                [history.silver_adj_factor_path(root,d) for d in batch],life)
        assert observed == {d: (5001,5000,1) for d in batch}
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        assert (peak if sys.platform == 'darwin' else peak * 1024) < history.REBUILD_MAX_RSS_BYTES
