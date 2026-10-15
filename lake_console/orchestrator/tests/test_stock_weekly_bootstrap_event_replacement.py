"""Real B0 files and an isolated event store; no production resources."""

import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap import stock_weekly_events as events
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    capture_file_hash,
)
from orchestrator.defs.bootstrap.stock_weekly_event_files import (
    audit_weekly_event_files,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    stable_weekly_hash,
)

from .test_stock_weekly_adj_bootstrap_replacement import build


@pytest.fixture
def bootstrap_entry(tmp_path):
    _, _, _, audit = build(tmp_path)
    promote_weekly_candidates(audit, apply=True)
    return audit_weekly_event_files(
        [{"path": str(audit), "sha256": capture_file_hash(audit)}]
    )[0]


def execute_checks(instance, plan, tmp_path, *, checkpoint=None, raise_on_error=True):
    from orchestrator.defs.jobs.stock_weekly_event_backfill import (
        raw_stk_period_bar_adj_week_event_backfill_job,
    )

    plan_path = tmp_path / "event-plan.json"
    plan_path.write_text(json.dumps(plan))
    return raw_stk_period_bar_adj_week_event_backfill_job.execute_in_process(
        instance=instance,
        raise_on_error=raise_on_error,
        run_config={
            "ops": {
                "report_stock_weekly_bootstrap_checks": {
                    "config": {
                        "plan_path": str(plan_path),
                        "expected_plan_hash": plan["plan_hash"],
                        "checkpoint_path": str(
                            checkpoint or tmp_path / "checkpoint.json"
                        ),
                        "start": 0,
                        "count": 33,
                    }
                }
            }
        },
    )


def apply_stage(instance, plan, *, stage, checkpoint):
    if stage == "checks":
        return execute_checks(
            instance, plan, checkpoint.parent, checkpoint=checkpoint
        ).output_for_node("report_stock_weekly_bootstrap_checks")
    return events.apply_weekly_events(
        instance, plan, stage=stage, checkpoint=checkpoint
    )


def apply_all(instance, plan, tmp_path):
    for stage in ("register", "materializations", "checks"):
        apply_stage(
            instance, plan, stage=stage, checkpoint=tmp_path / "checkpoint.json"
        )


def latest_mat(instance, entry):
    return instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=events._asset(entry), asset_partitions=[entry["week"]]
        ),
        limit=1,
    ).records[0]


def write_check(instance, entry, mat, name, *, passed=True, target=True):
    instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=events._asset(entry),
            check_name=name,
            partition=entry["week"],
            passed=passed,
            blocking=True,
            severity=dg.AssetCheckSeverity.ERROR,
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=mat.storage_id,
                run_id=mat.event_log_entry.run_id,
                timestamp=mat.event_log_entry.timestamp,
            )
            if target
            else None,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=entry["rows"],
            ),
        )
    )


def seed_previous_events(
    instance, entry, *, rows=None, metadata=None, passed=True, write_checks=True
):
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=events._asset(entry),
            partition=entry["week"],
            metadata=build_materialization_metadata(
                uri=entry["path"],
                row_count=entry["rows"] if rows is None else rows,
                extra_metadata=metadata or {},
            ),
        )
    )
    mat = latest_mat(instance, entry)
    if write_checks:
        for name in events.weekly_check_names(StockWeeklySource(entry["source"])):
            write_check(instance, entry, mat, name, passed=passed)
    return mat


@pytest.mark.parametrize(
    "previous", ["same_rows", "different_rows", "wrong_b0", "wrong_content"]
)
def test_refresh_appends_new_events_and_binds_all_checks(
    tmp_path, bootstrap_entry, previous
):
    entry = bootstrap_entry
    metadata = {}
    if previous in ("wrong_b0", "wrong_content"):
        metadata = {
            events.BOOTSTRAP_TOKEN: deepcopy(entry["bootstrap_identity"]),
            events.FILE_SHA256_TOKEN: entry["sha256"],
        }
        if previous == "wrong_b0":
            metadata[events.BOOTSTRAP_TOKEN]["closure_revision"] += 1
        else:
            metadata[events.FILE_SHA256_TOKEN] = "f" * 64
    with dg.DagsterInstance.ephemeral() as instance:
        previous_mat = seed_previous_events(
            instance,
            entry,
            rows=entry["rows"] + 1 if previous == "different_rows" else None,
            metadata=metadata,
        )
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        assert plan["version"] == 2
        assert plan["counts"]["materializations"] == 1
        assert plan["counts"]["checks"] == 3
        assert plan["counts"]["blocked_checks"] == 0
        apply_all(instance, plan, tmp_path)
        mat = latest_mat(instance, entry)
        assert mat.storage_id != previous_mat.storage_id
        assert (
            mat.asset_materialization.metadata[events.BOOTSTRAP_TOKEN].value
            == entry["bootstrap_identity"]
        )
        assert (
            mat.asset_materialization.metadata[events.FILE_SHA256_TOKEN].value
            == entry["sha256"]
        )
        state, _ = events.read_weekly_event_state(instance, [entry])
        for _, record in state[(entry["source"], entry["week"])]["checks"].values():
            run = instance.get_run_by_id(record.event_log_entry.run_id)
            assert run is not None and run.job_name == events.BOOTSTRAP_CHECKS_JOB_NAME
            assert run.status == dg.DagsterRunStatus.SUCCESS
            evaluation = record.event_log_entry.dagster_event.event_specific_data
            assert evaluation.passed and evaluation.blocking
            assert evaluation.partition == entry["week"]
            assert evaluation.target_materialization_data.storage_id == mat.storage_id
            assert (
                evaluation.target_materialization_data.run_id
                == mat.event_log_entry.run_id
            )
            assert (
                evaluation.target_materialization_data.timestamp
                == mat.event_log_entry.timestamp
            )
        for stage in ("register", "materializations", "checks"):
            assert (
                apply_stage(
                    instance, plan, stage=stage, checkpoint=tmp_path / "resume.json"
                )["writes"]
                == 0
            )
        assert (
            len(
                instance.fetch_materializations(
                    dg.AssetRecordsFilter(
                        asset_key=events._asset(entry), asset_partitions=[entry["week"]]
                    ),
                    limit=100,
                ).records
            )
            == 2
        )
        after = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        assert after["counts"]["materializations"] == after["counts"]["checks"] == 0


@pytest.mark.parametrize("stage", ["materializations", "checks"])
def test_committed_replacement_survives_checkpoint_failure(
    tmp_path, bootstrap_entry, monkeypatch, stage
):
    entry = bootstrap_entry
    with dg.DagsterInstance.ephemeral() as instance:
        seed_previous_events(instance, entry)
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        apply_stage(instance, plan, stage="register", checkpoint=tmp_path / "c.json")
        if stage == "checks":
            apply_stage(
                instance, plan, stage="materializations", checkpoint=tmp_path / "c.json"
            )
        real = events._atomic_json
        monkeypatch.setattr(
            events,
            "_atomic_json",
            lambda *args: (_ for _ in ()).throw(OSError("checkpoint failed")),
        )
        with pytest.raises(OSError):
            apply_stage(instance, plan, stage=stage, checkpoint=tmp_path / "c.json")
        monkeypatch.setattr(events, "_atomic_json", real)
        result = apply_stage(
            instance, plan, stage=stage, checkpoint=tmp_path / "c.json"
        )
        assert result["writes"] == (0 if stage == "materializations" else 2)
        apply_all(instance, plan, tmp_path)
        assert (
            events.freeze_weekly_event_plan(
                instance,
                [entry],
                instance_identity={
                    "artifact_root": instance.root_directory,
                    "storage": None,
                },
            )["counts"]["checks"]
            == 0
        )


def test_cancel_does_not_lose_replacement_materialization(
    tmp_path, bootstrap_entry, monkeypatch
):
    from orchestrator.defs.ops import stock_weekly_bootstrap_checks as checks_op

    entry = bootstrap_entry
    with dg.DagsterInstance.ephemeral() as instance:
        seed_previous_events(instance, entry)
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        for stage in ("register", "materializations"):
            apply_stage(instance, plan, stage=stage, checkpoint=tmp_path / "c.json")
        mat = latest_mat(instance, entry)
        real = checks_op.apply_weekly_events

        def canceled(*args, **kwargs):
            return real(*args, **{**kwargs, "cancel": lambda: True})

        monkeypatch.setattr(checks_op, "apply_weekly_events", canceled)
        failed = execute_checks(instance, plan, tmp_path, raise_on_error=False)
        assert not failed.success
        assert (
            instance.get_run_by_id(failed.run_id).status == dg.DagsterRunStatus.CANCELED
        )
        monkeypatch.setattr(checks_op, "apply_weekly_events", real)
        apply_all(instance, plan, tmp_path)
        assert latest_mat(instance, entry).storage_id == mat.storage_id


@pytest.mark.parametrize("invalid", ["failed", "no_target"])
def test_check_on_current_b0_target_is_not_silently_overwritten(
    tmp_path, bootstrap_entry, invalid, monkeypatch
):
    entry = bootstrap_entry
    with dg.DagsterInstance.ephemeral() as instance:
        seed_previous_events(instance, entry, passed=False)
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        assert plan["counts"]["historical_latest_failed"] == 3
        assert plan["counts"]["blocked_checks"] == 0
        for stage in ("register", "materializations"):
            apply_stage(instance, plan, stage=stage, checkpoint=tmp_path / "c.json")
        real = instance.report_dagster_event

        def write_invalid(event, *args, **kwargs):
            if event.event_type_value == "ASSET_CHECK_EVALUATION":
                evaluation = event.event_specific_data
                event = events.DagsterEvent(
                    event_type_value=event.event_type_value,
                    job_name=event.job_name,
                    step_key=event.step_key,
                    event_specific_data=AssetCheckEvaluation(
                        asset_key=evaluation.asset_key,
                        check_name=evaluation.check_name,
                        partition=evaluation.partition,
                        passed=invalid != "failed",
                        blocking=True,
                        severity=dg.AssetCheckSeverity.ERROR,
                        target_materialization_data=evaluation.target_materialization_data
                        if invalid != "no_target"
                        else None,
                        metadata=evaluation.metadata,
                    ),
                )
            return real(event, *args, **kwargs)

        monkeypatch.setattr(instance, "report_dagster_event", write_invalid)
        failed = execute_checks(instance, plan, tmp_path, raise_on_error=False)
        assert not failed.success
        monkeypatch.setattr(instance, "report_dagster_event", real)
        after = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        assert after["counts"]["blocked_checks"] == 1
        with pytest.raises(
            WeeklyCaptureError, match="event_existing_check_requires_review"
        ):
            apply_stage(instance, after, stage="checks", checkpoint=tmp_path / "c.json")


@pytest.mark.parametrize("change", ["revision", "batch", "plan", "none"])
def test_forged_boundary_rejected_before_instance_writes(
    tmp_path, bootstrap_entry, change
):
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance,
            [bootstrap_entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        identity = plan["entries"][0]["bootstrap_identity"]
        if change == "revision":
            identity["closure_revision"] += 1
        elif change == "batch":
            identity["batch_id"] = "11111111-1111-1111-1111-111111111111"
        elif change == "plan":
            identity["plan_hash"] = "a" * 64
        else:
            plan["entries"][0]["bootstrap_identity"] = None
        plan["plan_hash"] = stable_weekly_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        with pytest.raises(WeeklyCaptureError, match="event_audit_entry_mismatch"):
            apply_stage(
                instance, plan, stage="register", checkpoint=tmp_path / "c.json"
            )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_old_plan_and_missing_identity_are_rejected(bootstrap_entry):
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance,
            [bootstrap_entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
    original = deepcopy(plan)
    plan["version"] = 1
    plan["plan_hash"] = stable_weekly_hash(
        {k: v for k, v in plan.items() if k != "plan_hash"}
    )
    with pytest.raises(WeeklyCaptureError, match="event_plan_hash_mismatch"):
        events.verify_weekly_event_plan(plan)
    original["entries"][0].pop("bootstrap_identity")
    original["plan_hash"] = stable_weekly_hash(
        {k: v for k, v in original.items() if k != "plan_hash"}
    )
    with pytest.raises(WeeklyCaptureError, match="event_bootstrap_identity_invalid"):
        events.verify_weekly_event_plan(original)


def test_concurrent_matching_materialization_is_rejected(tmp_path, bootstrap_entry):
    entry = bootstrap_entry
    with dg.DagsterInstance.ephemeral() as instance:
        seed_previous_events(instance, entry)
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        apply_stage(instance, plan, stage="register", checkpoint=tmp_path / "c.json")
        seed_previous_events(
            instance,
            entry,
            metadata={
                events.BOOTSTRAP_TOKEN: entry["bootstrap_identity"],
                events.FILE_SHA256_TOKEN: entry["sha256"],
                events.TOKEN: "another-plan",
            },
            write_checks=False,
        )
        with pytest.raises(WeeklyCaptureError, match="event_materialization_changed"):
            apply_stage(
                instance, plan, stage="materializations", checkpoint=tmp_path / "c.json"
            )


def test_normal_readiness_survives_removed_bootstrap_evidence(
    tmp_path, bootstrap_entry
):
    from orchestrator.defs.checks import stock_weekly_checks as checks
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.stock_weekly_update_state import weekly_period_status

    entry = bootstrap_entry
    source = StockWeeklySource(entry["source"])
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        apply_all(instance, plan, tmp_path)
        assert (
            weekly_period_status(instance, tmp_path / "formal", source, entry["week"])
            == "ready"
        )
        capture_root = Path(entry["audit_path"]).parents[4]
        shutil.rmtree(capture_root)
        context = SimpleNamespace(instance=instance, partition_key=entry["week"])
        for name in events.weekly_check_names(source):
            definition = getattr(checks, name)
            result = definition.node_def.compute_fn.decorated_fn(
                context, LakeRootResource(root_path=str(tmp_path / "formal"))
            )
            assert result.passed
        assert (
            weekly_period_status(instance, tmp_path / "formal", source, entry["week"])
            == "ready"
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"count": 0},
        {"count": 34},
        {"start": -1},
        {"count": True},
        {"run_id": "invented"},
        {"expected_plan_hash": "invalid"},
    ],
)
def test_check_job_config_rejects_unapproved_inputs(overrides):
    from pydantic import ValidationError

    from orchestrator.defs.run_contracts.configs import (
        StockWeeklyBootstrapEventChecksConfig,
    )

    values = {
        "plan_path": "/private/tmp/plan.json",
        "checkpoint_path": "/private/tmp/c.json",
        "expected_plan_hash": "a" * 64,
    }
    with pytest.raises(ValidationError):
        StockWeeklyBootstrapEventChecksConfig(**{**values, **overrides})


@pytest.mark.parametrize("change", ["instance", "non_b0", "mixed"])
def test_real_job_rejects_wrong_instance_and_source_scope(
    tmp_path, bootstrap_entry, change
):
    entry = deepcopy(bootstrap_entry)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance,
            [entry],
            instance_identity={
                "artifact_root": instance.root_directory,
                "storage": None,
            },
        )
        if change == "instance":
            plan["instance_identity"]["artifact_root"] += "-wrong"
        elif change == "non_b0":
            plan["entries"][0]["bootstrap_identity"] = None
        else:
            other = deepcopy(entry)
            other.update(
                source="primary_unadjusted",
                bootstrap_identity=None,
            )
            other.update(
                previous_mat_id=None,
                previous_check_ids={
                    name: None
                    for name in (
                        "raw_tushare_stk_period_bar_week_" + kind + "_check"
                        for kind in ("file_contract", "key_partition", "delivery_reconciliation")
                    )
                },
                missing_checks=list(
                    "raw_tushare_stk_period_bar_week_" + kind + "_check"
                    for kind in ("file_contract", "key_partition", "delivery_reconciliation")
                ),
                missing_mat=True,
                blocked_checks=[],
            )
            plan["entries"].append(other)
        plan["plan_hash"] = stable_weekly_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        result = execute_checks(instance, plan, tmp_path, raise_on_error=False)
        assert not result.success
        assert (
            instance.get_run_by_id(result.run_id).status == dg.DagsterRunStatus.FAILURE
        )
        assert not instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=events._asset(entry)), limit=1
        ).records


def test_arbitrary_run_id_cannot_report_b0_checks(tmp_path, bootstrap_entry):
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance, [bootstrap_entry], instance_identity={}
        )
        fake = SimpleNamespace(
            instance=instance,
            job_name=events.BOOTSTRAP_CHECKS_JOB_NAME,
            run_id="invented",
        )
        with pytest.raises(
            WeeklyCaptureError, match="event_bootstrap_checks_require_real_run"
        ):
            events.apply_weekly_events(
                instance,
                plan,
                stage="checks",
                checkpoint=tmp_path / "c.json",
                count=1,
                check_context=fake,
            )
        assert instance.get_runs() == []


def test_check_job_is_formally_registered_and_never_automatic():
    from orchestrator.definitions import defs

    definitions = defs()
    job = definitions.resolve_job_def(events.BOOTSTRAP_CHECKS_JOB_NAME)
    assert job.graph.node_names() == ["report_stock_weekly_bootstrap_checks"]
    assert job.partitions_def is None
    sensors = Path(events.__file__).parents[1] / "sensors"
    for path in sensors.glob("*.py"):
        source = path.read_text()
        assert events.BOOTSTRAP_CHECKS_JOB_NAME not in source
        assert "BOOTSTRAP_CHECKS_JOB_NAME" not in source


def test_persistent_execution_adapter_runs_without_launcher_or_autocreate(
    tmp_path, bootstrap_entry, monkeypatch
):
    from dagster._core.storage.event_log.in_memory import InMemoryEventLogStorage

    from orchestrator.defs.bootstrap import stock_weekly_event_instance as adapter

    home = tmp_path / "persistent-instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(str(home)) as backing:
        identity = {"artifact_root": backing.root_directory, "storage": None}
        monkeypatch.setattr(
            adapter,
            "_configuration",
            lambda home: ("isolated", Path(backing.root_directory), identity),
        )
        calls = []

        def store(existing):
            def construct(url, *, should_autocreate_tables):
                calls.append(should_autocreate_tables)
                return existing

            return construct

        fresh = backing.get_ref().storage_data.rehydrate()
        monkeypatch.setattr(adapter, "PostgresRunStorage", store(fresh.run_storage))
        monkeypatch.setattr(
            adapter, "PostgresEventLogStorage", store(InMemoryEventLogStorage())
        )
        monkeypatch.setattr(
            adapter, "PostgresScheduleStorage", store(fresh.schedule_storage)
        )
        with adapter.open_weekly_event_instance(
            identity=identity, for_execution=True
        ) as (instance, _):
            assert instance.get_ref().run_launcher_data is None
            assert instance.get_ref().run_coordinator_data is not None
            seed_previous_events(instance, bootstrap_entry)
            plan = events.freeze_weekly_event_plan(
                instance, [bootstrap_entry], instance_identity=identity
            )
            apply_all(instance, plan, tmp_path)
            assert (
                events.freeze_weekly_event_plan(
                    instance, [bootstrap_entry], instance_identity=identity
                )["counts"]["checks"]
                == 0
            )
            assert all(
                run.status == dg.DagsterRunStatus.SUCCESS for run in instance.get_runs()
            )
        assert calls == [False, False, False]
