"""Actual nine-day job failure and native same-root recovery, using temporary IO.

Only source transport and formal-volume availability are substituted. The
registered job, asset, guards, file producers, checks, evaluator and event store
remain real. Independent verification runs outside measured execution attempts.
"""

import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import create_execution_plan, execute_run
from dagster._core.execution.plan.state import KnownExecutionState
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
)

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    ANNOUNCEMENT_JOB,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_window import announcement_schedule_tags
from orchestrator.defs.assets import anns_d as asset_module
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.jobs.anns_d import raw_anns_d_update_job
from orchestrator.defs.paths import raw_anns_d_path
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_measurement_support import anns_measurement as _measurement_fixture

anns_measurement = _measurement_fixture
DAYS = (
    "2023-06-01", "2023-06-02", "2023-06-03",
    "2023-06-04", "2023-06-05", "2023-06-06",
    "2023-06-07", "2023-06-08", "2023-06-09",
)
SOURCE_DATES = (
    "20230601", "20230602", "20230603", "20230604", "20230605",
    "20230606", "20230607", "20230608", "20230609",
)
FIELDS = ("ann_date", "ts_code", "name", "title", "url", "rec_time")
FAILED_DAY = "2023-06-04"
COMPLETED_DAYS = (
    "2023-06-01", "2023-06-02", "2023-06-03", "2023-06-05",
    "2023-06-06", "2023-06-07", "2023-06-08", "2023-06-09",
)
ASSET_KEY = dg.AssetKey(ANNOUNCEMENT_ASSET)


def _file_state(path):
    stat = path.stat()
    return {
        "ino": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _source_pages(day_record):
    document = json.loads(Path(day_record["checkpoint"]).read_text())
    return frozenset(page["path"] for page in document["delivery"]["source_pages"])


def test_nine_day_fourth_day_failure_and_native_same_root_recovery(
    tmp_path, monkeypatch, anns_measurement
):
    root, staging, instance_directory = (
        tmp_path / "lake", tmp_path / "staging", tmp_path / "instance"
    )
    for directory in (root, staging, instance_directory):
        directory.mkdir()
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda *_: None)
    calls, replacements = [], []
    state = {"fail": True}

    def source(params, control):
        calls.append(dict(params))
        if state["fail"] and params["ann_date"] == "20230604":
            # Deliberately wrong schema, not a source-call error and not a retry.
            return [], ("ann_date", "ts_code", "name", "title", "url")
        return [], FIELDS

    monkeypatch.setattr(asset_module, "AnnouncementProcessCall", lambda *_: source)
    paths = {day: raw_anns_d_path(root, day) for day in DAYS}
    target_paths = set(paths.values())
    original_replace = os.replace

    def replace(source_path, target_path, *args, **kwargs):
        if Path(target_path) in target_paths:
            replacements.append(Path(target_path))
        return original_replace(source_path, target_path, *args, **kwargs)

    # Keep actual replacement/exception behavior; observe only this test's targets.
    monkeypatch.setattr(os, "replace", replace)
    tick = datetime(2023, 6, 8, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    tags = {
        **announcement_schedule_tags(tick),
        ASSET_PARTITION_RANGE_START_TAG: "2023-06-01",
        ASSET_PARTITION_RANGE_END_TAG: "2023-06-09",
    }
    assert tags["anns_d/start_date"] == DAYS[0]
    assert tags["anns_d/end_date"] == DAYS[-1]
    config = {"ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}}
    definitions = dg.Definitions(
        assets=[asset_module.raw_tushare_anns_d],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[raw_anns_d_update_job],
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "tushare": TushareResource(token="isolated-unused-token"),
        },
    )
    # Preserve the registered job selection; only its test executor is in-process.
    job = definitions.resolve_job_def(ANNOUNCEMENT_JOB).with_executor_def(
        dg.in_process_executor
    )
    assert job.name == ANNOUNCEMENT_JOB
    directory = staging / "anns_d/windows" / tags["anns_d/window_id"]
    execution_path, budget_path = directory / "execution.json", directory / "budget.json"
    expected_requests = [
        {"ann_date": day, "limit": 2000, "offset": 0} for day in SOURCE_DATES
    ]

    with dg.DagsterInstance.ephemeral(tempdir=str(instance_directory)) as instance:
        with anns_measurement.attempt("initial"):
            original = job.execute_in_process(
                instance=instance, tags=tags, run_config=config, raise_on_error=False
            )
        assert not original.success
        parent = instance.get_run_by_id(original.run_id)
        assert parent.status == dg.DagsterRunStatus.FAILURE
        assert calls == expected_requests
        first = json.loads(execution_path.read_text())
        budget = json.loads(budget_path.read_text())
        assert first["phase"] == "failed"
        assert first["attempted_days"] == list(DAYS)
        assert first["files_completed"] == list(COMPLETED_DAYS)
        assert first["failed_days"] == [FAILED_DAY]
        assert first["unattempted_days"] == []
        assert first["days"][FAILED_DAY]["reason"] == "announcement_response_schema"
        assert first["requests"] == budget["requests"] == 9
        assert first["day_requests"] == budget["day_requests"] == {day: 1 for day in DAYS}
        assert budget["in_flight"] is False
        assert not paths[FAILED_DAY].exists()
        assert replacements == [paths[day] for day in COMPLETED_DAYS]
        parent_logs = instance.all_logs(parent.run_id)
        assert not any(event.asset_materialization for event in parent_logs)
        assert not any(event.asset_check_evaluation for event in parent_logs)
        assert [
            event.step_key for event in parent_logs
            if event.dagster_event and event.dagster_event.is_step_start
        ] == [ANNOUNCEMENT_ASSET]
        verification_store = AnnouncementStore(
            root, staging, "independent-nine-day-verification",
            AnnouncementPolicy(interval_seconds=0), AnnouncementControl(),
        )
        for day in COMPLETED_DAYS:
            assert verification_store.audit_file(paths[day], day)["written_rows"] == 0
        original_files = {day: _file_state(paths[day]) for day in COMPLETED_DAYS}
        original_pages = {day: _source_pages(first["days"][day]) for day in COMPLETED_DAYS}

        steps, known = KnownExecutionState.build_resume_retry_reexecution(instance, parent)
        assert ANNOUNCEMENT_ASSET in steps
        plan = create_execution_plan(
            job, run_config=parent.run_config, step_keys_to_execute=steps,
            known_state=known, tags=parent.tags,
        )
        child = instance.create_run_for_job(
            job, execution_plan=plan, run_config=parent.run_config, tags=parent.tags,
            root_run_id=parent.run_id, parent_run_id=parent.run_id,
        )
        assert child.root_run_id == parent.run_id and child.run_config == parent.run_config
        assert child.tags["anns_d/window_id"] == tags["anns_d/window_id"]
        replacements.clear()
        state["fail"] = False
        with anns_measurement.attempt("resume"):
            result = execute_run(InMemoryJob(job), child, instance, raise_on_error=False)
        assert result.success
        assert instance.get_run_by_id(child.run_id).status == dg.DagsterRunStatus.SUCCESS
        assert calls == expected_requests + [{"ann_date": "20230604", "limit": 2000, "offset": 0}]
        assert replacements == [paths[FAILED_DAY]]
        after = json.loads(execution_path.read_text())
        budget_after = json.loads(budget_path.read_text())
        assert after["identity"] == first["identity"]
        assert after["phase"] == "files_completed"
        assert after["files_completed"] == list(DAYS)
        assert after["failed_days"] == [] and after["unattempted_days"] == []
        assert after["requests"] == budget_after["requests"] == 10
        expected_counts = {day: 2 if day == FAILED_DAY else 1 for day in DAYS}
        assert after["day_requests"] == budget_after["day_requests"] == expected_counts
        assert budget_after["in_flight"] is False
        for day in DAYS:
            assert "reason" not in after["days"][day]
            assert "failure_phase" not in after["days"][day]
        repaired_cp = json.loads(Path(after["days"][FAILED_DAY]["checkpoint"]).read_text())
        assert "reason" not in repaired_cp and "failure_phase" not in repaired_cp
        assert {day: _file_state(paths[day]) for day in COMPLETED_DAYS} == original_files
        assert {
            day: _source_pages(after["days"][day]) for day in COMPLETED_DAYS
        } == original_pages

        logs = instance.all_logs(child.run_id)
        materializations = [event.asset_materialization for event in logs if event.asset_materialization]
        evaluations = [event.asset_check_evaluation for event in logs if event.asset_check_evaluation]
        assert len(materializations) == 9 and len(evaluations) == 18
        assert Counter(mat.partition for mat in materializations) == {day: 1 for day in DAYS}
        assert Counter((check.partition, check.check_name) for check in evaluations) == {
            (day, name): 1 for day in DAYS for name in ANNOUNCEMENT_CHECKS
        }
        mats = {}
        for day in DAYS:
            record = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=ASSET_KEY, asset_partitions=[day]), limit=1
            ).records[0]
            assert record.asset_materialization.partition == day
            assert record.event_log_entry.run_id == child.run_id
            metadata = record.asset_materialization.metadata
            actual = _file_state(paths[day])
            fingerprint = {key: actual[key] for key in ("size", "sha256")}
            assert metadata["goldenshare/fingerprint"].value == fingerprint
            assert metadata["dagster/row_count"].value == 0
            assert metadata["goldenshare/announcement_identity"].value["day"] == day
            assert metadata["goldenshare/announcement_checkpoint"].value == after["days"][day]["checkpoint"]
            assert after["days"][day]["fingerprint"] == fingerprint
            mats[day] = record
        for evaluation in evaluations:
            assert evaluation.passed
            target, mat = evaluation.target_materialization_data, mats[evaluation.partition]
            assert target.storage_id == mat.storage_id
            assert target.run_id == child.run_id
            assert target.timestamp == mat.timestamp
        for name in ANNOUNCEMENT_CHECKS:
            records = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(ASSET_KEY, name), limit=9
            )
            assert len(records) == 9 and {record.partition for record in records} == set(DAYS)
            for record in records:
                assert record.status == AssetCheckExecutionRecordStatus.SUCCEEDED
                assert record.run_id == child.run_id
                target = record.evaluation.target_materialization_data
                mat = mats[record.partition]
                assert target.storage_id == mat.storage_id and target.run_id == child.run_id
                assert target.timestamp == mat.timestamp
