"""Explicit worker-only case: native assets/checks, local source responses.

This file is selected by the worker, not by the normal test_anns_d*.py glob.
The literal old row and 2,001 different new titles independently imply 2,002 rows.
"""

from collections import Counter

import dagster as dg
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import create_execution_plan, execute_run
from dagster._core.execution.plan.state import KnownExecutionState

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, ANNOUNCEMENT_CHECKS
from orchestrator.defs.assets import anns_d as asset_module
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.jobs.anns_d import raw_anns_d_update_job
from orchestrator.defs.resources import LakeRootResource, TushareResource
from tests.anns_d_measurement_support import anns_measurement as _measurement_fixture

anns_measurement = _measurement_fixture
DAY = "2023-06-09"
FIELDS = ("ann_date", "ts_code", "name", "title", "url", "rec_time")
BASE = {
    "ann_date": "20230609", "ts_code": "155162.SH", "name": "19津投04",
    "title": "old literal row", "url": None, "rec_time": None,
}


def test_normal_merge_measurement(tmp_path, monkeypatch, anns_measurement):
    root, staging, instance_directory = (
        tmp_path / "lake", tmp_path / "staging", tmp_path / "instance"
    )
    for path in (root, staging, instance_directory):
        path.mkdir()
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda *_: None)
    calls, state = [], {"prepare": True}
    rows = [{**BASE, "title": f"new literal row {index}"} for index in range(2001)]

    def source(params, control):
        calls.append(dict(params))
        if state["prepare"]:
            return [dict(BASE)], FIELDS
        offset = params["offset"]
        return rows[offset:offset + 2000], FIELDS

    monkeypatch.setattr(asset_module, "AnnouncementProcessCall", lambda *_: source)
    definitions = dg.Definitions(
        assets=[asset_module.raw_tushare_anns_d],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[raw_anns_d_update_job],
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "tushare": TushareResource(token="unused-local-measurement"),
        },
    )
    job = definitions.resolve_job_def("raw_anns_d_update_job").with_executor_def(
        dg.in_process_executor
    )
    config = {"ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}}
    with dg.DagsterInstance.ephemeral(tempdir=str(instance_directory)) as instance:
        with anns_measurement.attempt("prepare"):
            baseline = job.execute_in_process(instance=instance, partition_key=DAY, run_config=config)
            assert baseline.success
            anns_measurement.result(success=True, source_calls=1, written_rows=1)
        state["prepare"] = False
        with anns_measurement.attempt("normal"):
            result = job.execute_in_process(instance=instance, partition_key=DAY, run_config=config)
            assert result.success
            anns_measurement.result(success=True, source_calls=2, written_rows=2002)
        assert calls == [
            {"ann_date": "20230609", "limit": 2000, "offset": 0},
            {"ann_date": "20230609", "limit": 2000, "offset": 0},
            {"ann_date": "20230609", "limit": 2000, "offset": 2000},
        ]
        materials = result.get_asset_materialization_events()
        assert len(materials) == 1
        metadata = materials[0].materialization.metadata
        assert metadata["dagster/row_count"].value == 2002
        assert metadata["goldenshare/source_rows"].value == 2001
        assert metadata["goldenshare/existing_rows"].value == 1
        assert metadata["goldenshare/page_count"].value == 2
        assert metadata["goldenshare/last_page_rows"].value == 1
        parent = instance.get_run_by_id(result.run_id)
        check_steps = [
            str(job.asset_layer.get_op_output_handle(dg.AssetCheckKey(
                dg.AssetKey(ANNOUNCEMENT_ASSET), name
            )).node_handle) for name in ANNOUNCEMENT_CHECKS
        ]
        known = KnownExecutionState.build_for_reexecution(instance, parent)
        plan = create_execution_plan(
            job, run_config=parent.run_config, step_keys_to_execute=check_steps,
            known_state=known, tags=parent.tags,
        )
        child = instance.create_run_for_job(
            job, execution_plan=plan, run_config=parent.run_config, tags=parent.tags,
            root_run_id=parent.run_id, parent_run_id=parent.run_id,
        )
        with anns_measurement.attempt("checks_only", run_id=child.run_id):
            checked = execute_run(InMemoryJob(job), child, instance, raise_on_error=False)
            assert checked.success
            anns_measurement.result(success=True, source_calls=0, materializations=0, checks=2)
        assert len(calls) == 3
        logs = instance.all_logs(child.run_id)
        assert not any(entry.asset_materialization for entry in logs)
        evaluations = [entry.asset_check_evaluation for entry in logs if entry.asset_check_evaluation]
        assert Counter(entry.check_name for entry in evaluations) == {
            ANNOUNCEMENT_CHECKS[0]: 1, ANNOUNCEMENT_CHECKS[1]: 1,
        }
        assert all(entry.passed and entry.target_materialization_data.run_id == parent.run_id for entry in evaluations)
