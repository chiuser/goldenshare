"""Temporary producer evidence, explicit check rules, and real check reexecution."""

from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg
import pytest
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.errors import DagsterExecutionInterruptedError
from dagster._core.execution.api import create_execution_plan, execute_run
from dagster._core.execution.plan.state import KnownExecutionState
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
    PARTITION_NAME_TAG,
)

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    announcement_atomic_json,
    announcement_file_fingerprint,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.checks import anns_d_checks as checks_module
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row
from tests.test_anns_d_range_checks import DAYS

archive = _archive_fixture


def _producer_record(store, day="2023-06-09", run_id="original", historical=False):
    # Contract source: existing ANNOUNCEMENT_FIELDS/write_page/build_day/promote_day.
    # The literal independent expectation is one six-field row, with nullable URL/time.
    page = store.write_page(
        [source_row(ann_date=day.replace("-", ""))],
        store.directory / "page.parquet",
        store.control,
    )
    delivery = store.build_day(day, [page])
    delivery.update(
        source_pages=[
            {
                "path": str(page),
                "fingerprint": announcement_file_fingerprint(page),
                "rows": 1,
            }
        ],
        capture_complete=True,
        last_page_rows=1,
    )
    identity = {"window_id": "test-window", "day": day, "policy": asdict(store.policy)}
    if historical:
        # Original producer's asdict(policy) included this field; saved evidence
        # remains unchanged when today's execution policy removes it.
        identity["policy"]["max_window_seconds"] = 3600
    checkpoint = AnnouncementCheckpoint(store.directory / "delivery.json", identity)
    checkpoint.save(phase="validated", delivery=delivery)
    store.promote_day(day, delivery, checkpoint)
    assert store.audit_file(store.target(day), day)["written_rows"] == 1
    mat = dg.AssetMaterialization(
        asset_key=ANNOUNCEMENT_ASSET,
        partition=day,
        metadata={
            "goldenshare/announcement_identity": identity,
            "goldenshare/announcement_checkpoint": str(checkpoint.path),
        },
    )
    record = SimpleNamespace(
        asset_materialization=mat,
        event_log_entry=SimpleNamespace(run_id=run_id),
        storage_id=17,
        timestamp=1.0,
    )
    return record, checkpoint, page


def _evaluate(store, monkeypatch, record, *, reconciliation=True, **kwargs):
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_ROOT", str(store.root))
    context = SimpleNamespace(
        instance=SimpleNamespace(
            fetch_materializations=lambda *a, **k: SimpleNamespace(
                records=[record] if record else []
            )
        ),
        run=SimpleNamespace(
            run_id="check-only", asset_selection=set(), step_keys_to_execute=None
        ),
    )
    return checks_module.evaluate_announcement_check(
        context,
        LakeRootResource(root_path=str(store.root)),
        day="2023-06-09",
        reconciliation=reconciliation,
        staging_root=store.staging,
        target_record=record,
        **kwargs,
    )


@pytest.mark.parametrize("historical", [False, True])
def test_real_day_producer_evidence_and_old_policy_remain_checkable(
    archive, monkeypatch, historical
):
    record, checkpoint, _ = _producer_record(archive, historical=historical)
    before = checkpoint.path.read_bytes()
    result = _evaluate(archive, monkeypatch, record)
    assert result.passed
    assert result.metadata["goldenshare/checked_row_count"].value == 1
    assert checkpoint.path.read_bytes() == before


def test_file_rule_remains_independent_when_delivery_materialization_is_missing(
    archive, monkeypatch
):
    _producer_record(archive)
    assert _evaluate(archive, monkeypatch, None, reconciliation=False).passed
    result = _evaluate(archive, monkeypatch, None, reconciliation=True)
    assert not result.passed
    assert result.metadata["goldenshare/failed_rule_names"].value == [
        "announcement_materialization_missing"
    ]


@pytest.mark.parametrize(
    "failure",
    [
        AnnouncementError("announcement_disk_space"),
        PermissionError("fixture"),
        RuntimeError("unknown fixture"),
        AnnouncementCancelled("announcement_cancelled"),
    ],
)
def test_public_or_unknown_failures_are_not_converted_to_rule_false(
    archive, monkeypatch, failure
):
    record, _, _ = _producer_record(archive)

    def reject(*a, **k):
        raise failure

    monkeypatch.setattr(checks_module.AnnouncementStore, "audit_file", reject)
    with pytest.raises(type(failure)):
        _evaluate(archive, monkeypatch, record, reconciliation=False)


def test_changed_source_page_is_public_conflict(archive, monkeypatch):
    record, _, page = _producer_record(archive)
    page.write_bytes(b"changed source evidence")
    with pytest.raises(AnnouncementError, match="delivery_source_changed"):
        _evaluate(archive, monkeypatch, record)


def test_wrong_delivery_day_is_rule_false(archive, monkeypatch):
    record, _, _ = _producer_record(archive, day="2023-06-08")
    result = _evaluate(archive, monkeypatch, record)
    assert not result.passed
    assert result.metadata["goldenshare/failed_rule_names"].value == [
        "announcement_delivery_wrong_day"
    ]


def _recovery_definitions(tmp_path, monkeypatch, state):
    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    started = datetime(2023, 6, 8, 8, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    policy = asdict(AnnouncementPolicy())
    tags = {
        "anns_d/window_id": "native-recovery",
        "anns_d/start_date": DAYS[0],
        "anns_d/end_date": DAYS[-1],
        "anns_d/started_at": str(started),
        "anns_d/automatic": "true",
        "anns_d/execution_version": "2",
        ASSET_PARTITION_RANGE_START_TAG: DAYS[0],
        ASSET_PARTITION_RANGE_END_TAG: DAYS[-1],
    }
    identity = {
        "execution_version": 2,
        "window_id": "native-recovery",
        "days": list(DAYS),
        "started_at": started,
        "automatic": True,
        "policy": policy,
        "contract_version": 1,
    }
    announcement_atomic_json(
        staging / "anns_d/windows/native-recovery/execution.json",
        {"identity": identity},
    )

    @dg.asset(name=ANNOUNCEMENT_ASSET, partitions_def=anns_d_natural_days)
    def producer(context):
        state["asset_calls"] += 1
        for day in context.partition_keys:
            context.add_asset_metadata(
                {
                    "goldenshare/announcement_identity": {
                        "window_id": "native-recovery",
                        "day": day,
                        "policy": policy,
                    }
                },
                partition_key=day,
            )
        return dg.MaterializeResult()

    def evaluate(context, lake_root, *, day, reconciliation, **kwargs):
        return dg.AssetCheckResult(
            passed=not (
                day == DAYS[0]
                and (
                    (
                        state["fail"]
                        and (reconciliation or state.get("both_fail", False))
                    )
                    or (state.get("fail_schema", False) and not reconciliation)
                )
            )
        )

    monkeypatch.setattr(checks_module, "evaluate_announcement_check", evaluate)
    checks = [
        checks_module.raw_tushare_anns_d_file_contract_check,
        checks_module.raw_tushare_anns_d_delivery_reconciliation_check,
    ]
    defs = dg.Definitions(
        assets=[producer],
        asset_checks=checks,
        jobs=[
            dg.define_asset_job(
                "native_recovery_fixture", executor_def=dg.in_process_executor
            )
        ],
        resources={"lake_root": LakeRootResource(root_path=str(root))},
    )
    return defs.resolve_job_def("native_recovery_fixture"), tags


@pytest.mark.parametrize("both_fail", [False, True])
def test_native_from_failure_only_reexecutes_failed_checks_and_keeps_parent_targets(
    tmp_path, monkeypatch, both_fail
):
    state = {"asset_calls": 0, "fail": True, "both_fail": both_fail}
    job, tags = _recovery_definitions(tmp_path, monkeypatch, state)
    with dg.DagsterInstance.ephemeral() as instance:
        original = job.execute_in_process(
            instance=instance, tags=tags, raise_on_error=False
        )
        assert not original.success
        parent = instance.get_run_by_id(original.run_id)
        steps, known = KnownExecutionState.build_resume_retry_reexecution(
            instance, parent
        )
        assert len(steps) == (2 if both_fail else 1)
        state["fail"] = False
        plan = create_execution_plan(
            job, step_keys_to_execute=steps, known_state=known, tags=tags
        )
        child = instance.create_run_for_job(
            job,
            execution_plan=plan,
            tags=tags,
            root_run_id=parent.run_id,
            parent_run_id=parent.run_id,
        )
        result = execute_run(InMemoryJob(job), child, instance, raise_on_error=False)
        assert result.success, [
            (e.dagster_event_type.value if e.dagster_event_type else None, e.message)
            for e in instance.all_logs(child.run_id)
        ]
        assert state["asset_calls"] == 1
        events = instance.all_logs(child.run_id)
        assert not any(e.asset_materialization for e in events)
        evaluations = [
            e.asset_check_evaluation for e in events if e.asset_check_evaluation
        ]
        assert len(evaluations) == (18 if both_fail else 9)
        assert all(
            e.target_materialization_data.run_id == parent.run_id for e in evaluations
        )
        assert sorted(
            e.partition for e in evaluations if e.check_name == ANNOUNCEMENT_CHECKS[1]
        ) == list(DAYS)


def _failed_reexecution(instance, job, previous, tags):
    parent = instance.get_run_by_id(previous.run_id)
    steps, known = KnownExecutionState.build_resume_retry_reexecution(instance, parent)
    plan = create_execution_plan(
        job, step_keys_to_execute=steps, known_state=known, tags=tags
    )
    child = instance.create_run_for_job(
        job,
        execution_plan=plan,
        tags=tags,
        root_run_id=parent.root_run_id or parent.run_id,
        parent_run_id=parent.run_id,
    )
    return child, execute_run(InMemoryJob(job), child, instance, raise_on_error=False)


def test_recovery_does_not_search_past_newer_failed_sibling_result(
    tmp_path, monkeypatch
):
    state = {"asset_calls": 0, "fail": True}
    job, tags = _recovery_definitions(tmp_path, monkeypatch, state)
    with dg.DagsterInstance.ephemeral() as instance:
        original = job.execute_in_process(
            instance=instance, tags=tags, raise_on_error=False
        )
        schema_only = job.get_subset(
            asset_selection=set(),
            asset_check_selection={
                dg.AssetCheckKey(
                    dg.AssetKey(ANNOUNCEMENT_ASSET), ANNOUNCEMENT_CHECKS[0]
                )
            },
        )
        state.update(fail=False, fail_schema=True)
        invalidated = schema_only.execute_in_process(
            instance=instance,
            tags={
                ASSET_PARTITION_RANGE_START_TAG: DAYS[0],
                ASSET_PARTITION_RANGE_END_TAG: DAYS[-1],
            },
            raise_on_error=False,
        )
        assert not invalidated.success
        state["fail_schema"] = False
        child, result = _failed_reexecution(instance, job, original, tags)
        assert not result.success
        assert state["asset_calls"] == 1
        evaluations = [
            e.asset_check_evaluation
            for e in instance.all_logs(child.run_id)
            if e.asset_check_evaluation
        ]
        assert not evaluations
        errors = [
            e.dagster_event.event_specific_data.error
            for e in instance.all_logs(child.run_id)
            if e.dagster_event and e.dagster_event.is_step_failure
        ]
        error = errors[0]
        while error.cause:
            error = error.cause
        assert "announcement_recovery_sibling_check" in error.message


def test_independent_single_day_check_only_can_itself_be_reexecuted(
    tmp_path, monkeypatch
):
    state = {"asset_calls": 0, "fail": False}
    job, tags = _recovery_definitions(tmp_path, monkeypatch, state)
    with dg.DagsterInstance.ephemeral() as instance:
        original = job.execute_in_process(
            instance=instance, tags=tags, raise_on_error=False
        )
        assert original.success
        check_job = job.get_subset(
            asset_selection=set(),
            asset_check_selection={
                dg.AssetCheckKey(
                    dg.AssetKey(ANNOUNCEMENT_ASSET), ANNOUNCEMENT_CHECKS[1]
                )
            },
        )
        independent_tags = {PARTITION_NAME_TAG: DAYS[0]}
        state["fail"] = True
        independent = check_job.execute_in_process(
            instance=instance, tags=independent_tags, raise_on_error=False
        )
        assert not independent.success
        state["fail"] = False
        child, result = _failed_reexecution(
            instance, check_job, independent, independent_tags
        )
        assert result.success
        assert state["asset_calls"] == 1
        records = instance.all_logs(child.run_id)
        assert not any(e.asset_materialization for e in records)
        evaluations = [
            e.asset_check_evaluation for e in records if e.asset_check_evaluation
        ]
        assert len(evaluations) == 1
        assert evaluations[0].partition == DAYS[0]
        assert evaluations[0].target_materialization_data.run_id == original.run_id


def _cancellation_wrapper(archive, monkeypatch, *, status, interruption=None):
    record, _, _ = _producer_record(archive, day=DAYS[0])
    monkeypatch.setattr(checks_module, "DEFAULT_LAKE_ROOT", str(archive.root))
    monkeypatch.setattr(
        checks_module, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging)
    )
    state = {"status": status}
    controls, audited = [], []
    original_store = checks_module.AnnouncementStore

    class ObservedStore(original_store):
        def __init__(self, root, staging, run_id, policy, control):
            controls.append(control)
            super().__init__(root, staging, run_id, policy, control)

        def audit_file(self, path, day):
            audited.append(day)
            assert self.control is controls[-1]
            assert not self.control.cancelled()
            if interruption is not None:
                raise interruption
            return super().audit_file(path, day)

    monkeypatch.setattr(checks_module, "AnnouncementStore", ObservedStore)
    target_calls = []

    def targets(*args):
        target_calls.append(True)
        return SimpleNamespace(
            records={day: record if day == DAYS[0] else None for day in DAYS},
            reuse_delivery=False,
            materializing=False,
        )

    monkeypatch.setattr(checks_module, "prepare_announcement_check_targets", targets)
    context = SimpleNamespace(
        partition_keys=DAYS,
        run=SimpleNamespace(run_id="cancel-fixture"),
        instance=SimpleNamespace(
            get_run_by_id=lambda _: SimpleNamespace(status=state["status"])
        ),
        log=SimpleNamespace(info=lambda _: None),
    )
    iterator = checks_module._announcement_check_events(
        context, LakeRootResource(root_path=str(archive.root)), reconciliation=False
    )
    return iterator, state, controls, audited, target_calls


@pytest.mark.parametrize(
    "status", [dg.DagsterRunStatus.CANCELING, dg.DagsterRunStatus.CANCELED]
)
def test_real_wrapper_checks_current_run_cancellation_before_entering_days(
    archive, monkeypatch, status
):
    iterator, _, controls, audited, targets = _cancellation_wrapper(
        archive, monkeypatch, status=status
    )
    with pytest.raises(AnnouncementCancelled, match="announcement_cancelled"):
        next(iterator)
    assert not targets and not controls and not audited


def test_real_wrapper_passes_live_control_to_audit_and_stops_after_first_day(
    archive, monkeypatch
):
    iterator, state, controls, audited, _ = _cancellation_wrapper(
        archive, monkeypatch, status=dg.DagsterRunStatus.STARTED
    )
    first = next(iterator)
    assert first.partition == DAYS[0] and first.passed
    assert audited == [DAYS[0]] and len(controls) == 1
    state["status"] = dg.DagsterRunStatus.CANCELING
    assert controls[0].cancelled()
    with pytest.raises(AnnouncementCancelled, match="announcement_cancelled"):
        next(iterator)
    assert audited == [DAYS[0]]


def test_real_wrapper_does_not_swallow_dagster_execution_interrupt(
    archive, monkeypatch
):
    iterator, _, _, audited, _ = _cancellation_wrapper(
        archive,
        monkeypatch,
        status=dg.DagsterRunStatus.STARTED,
        interruption=DagsterExecutionInterruptedError(),
    )
    with pytest.raises(DagsterExecutionInterruptedError):
        next(iterator)
    assert audited == [DAYS[0]]
