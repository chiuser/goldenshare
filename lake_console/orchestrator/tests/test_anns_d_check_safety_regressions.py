"""F2/F3 regressions use real temporary source delivery and native plan snapshots.

The query boundary is replaced only where explicitly stated. File parsing,
capture evidence, SHA checks, the wrapper, and the evaluator remain real.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import create_execution_plan, execute_run
from dagster._core.execution.plan.state import KnownExecutionState
from dagster._core.snap.execution_plan_snapshot import (
    create_execution_plan_snapshot_id,
    snapshot_from_execution_plan,
)
from dagster._core.storage.tags import PARTITION_NAME_TAG

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    AnnouncementError,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.anns_d_window import (
    announcement_day_run_id,
    announcement_manual_window_tags,
    execute_announcement_window,
)
from orchestrator.defs.checks import anns_d_check_targets as targets
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.resources import LakeRootResource
from tests import test_anns_d_reused_delivery as producer_cases

delivery_case = producer_cases.delivery_case
DAY = producer_cases.DAY
ROOT_ID = "968f0341-320b-416d-89fb-2ed1e01283c3"


@pytest.fixture(autouse=True)
def native_root_identifier(monkeypatch):
    monkeypatch.setattr(producer_cases, "ROOT_RUN_ID", ROOT_ID)


def _real_file_wrapper(case, monkeypatch, latest):
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(case.root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(case.staging))
    # Selection/old-green eligibility is covered separately. This stand-in
    # isolates whether the real per-day evaluator revalidates those bytes.
    monkeypatch.setattr(
        checks,
        "prepare_announcement_check_targets",
        lambda *a: SimpleNamespace(
            records={DAY: case.record}, reuse_delivery=True, materializing=False,
            window_deliveries=json.loads(case.execution_path.read_text())["days"],
        ),
    )
    context = SimpleNamespace(
        partition_keys=(DAY,),
        run=SimpleNamespace(run_id="schema-retry"),
        instance=SimpleNamespace(
            get_run_by_id=lambda _: SimpleNamespace(status=dg.DagsterRunStatus.STARTED),
            fetch_materializations=lambda *a, **k: SimpleNamespace(records=[latest[0]]),
        ),
        log=SimpleNamespace(info=lambda _: None),
    )
    return checks._announcement_check_events(
        context, LakeRootResource(root_path=str(case.root)), reconciliation=False
    )


def test_file_recovery_rejects_valid_file_replaced_before_its_actual_audit(
    delivery_case, monkeypatch
):
    case = delivery_case
    store = AnnouncementStore(
        case.root,
        case.staging,
        "replacement",
        producer_cases.AnnouncementPolicy(interval_seconds=0),
        case.control,
    )
    replacement = store.write_page(
        [{**producer_cases.SOURCE_ROW, "title": "different valid announcement"}],
        store.directory / "replacement.parquet",
        case.control,
    )
    original_evaluate = checks.evaluate_announcement_check

    def replace_then_evaluate(*args, **kwargs):
        os.replace(replacement, store.target(DAY))
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(checks, "evaluate_announcement_check", replace_then_evaluate)
    events = _real_file_wrapper(case, monkeypatch, [case.record])
    with pytest.raises(
        AnnouncementError, match="delivery_file_changed|file_changed_during_check"
    ):
        next(events)


def test_file_recovery_rejects_new_materialization_even_when_file_bytes_match(
    delivery_case, monkeypatch
):
    case = delivery_case
    latest = [case.record]
    original_evaluate = checks.evaluate_announcement_check

    def replace_target_then_evaluate(*args, **kwargs):
        latest[0] = SimpleNamespace(
            asset_materialization=case.record.asset_materialization,
            event_log_entry=SimpleNamespace(run_id="another-run"),
            storage_id=case.record.storage_id + 1,
            timestamp=case.record.timestamp + 1,
        )
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(
        checks, "evaluate_announcement_check", replace_target_then_evaluate
    )
    events = _real_file_wrapper(case, monkeypatch, latest)
    with pytest.raises(AnnouncementError, match="delivery_changed_during_check"):
        next(events)


def _native_root_context(case, *, explicit_steps, snapshot_kind="file"):
    context, _ = producer_cases._reexecution_context(case)
    original_job = context.job_def
    check_job = original_job.get_subset(
        asset_selection=set(), asset_check_selection=context.run.asset_check_selection
    )
    snapshot_job = original_job if snapshot_kind == "file" else check_job
    plan = create_execution_plan(snapshot_job)
    snapshot = snapshot_from_execution_plan(plan, snapshot_job.get_job_snapshot_id())
    snapshot_id = create_execution_plan_snapshot_id(snapshot)
    root = dg.DagsterRun(
        job_name=snapshot_job.name,
        run_id=ROOT_ID,
        asset_selection=None,
        step_keys_to_execute=[ANNOUNCEMENT_ASSET] if explicit_steps else None,
        execution_plan_snapshot_id=snapshot_id,
    )
    calls = []

    def get_root(run_id):
        calls.append(("root", run_id))
        assert run_id == ROOT_ID
        return root

    def get_snapshot(identifier):
        calls.append(("snapshot", identifier))
        assert identifier == snapshot_id
        return snapshot

    context.job_def = check_job
    context.instance.get_run_by_id = get_root
    context.instance.get_execution_plan_snapshot = get_snapshot
    return context, root, calls


@pytest.mark.parametrize("explicit_steps", [True, False])
def test_manual_file_root_none_selection_uses_its_own_steps_or_native_plan(
    delivery_case, explicit_steps
):
    case = delivery_case
    context, _, calls = _native_root_context(case, explicit_steps=explicit_steps)
    assert not context.job_def.asset_layer.selected_asset_keys
    result = targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert result.window_identity is not None
    assert result.window_identity["window_id"] == case.tags["anns_d/window_id"]
    assert len([c for c in calls if c[0] == "root"]) == 1
    assert len([c for c in calls if c[0] == "snapshot"]) == (0 if explicit_steps else 1)


def test_file_recovery_rejects_replacement_after_reused_reference_helper(
    delivery_case, monkeypatch
):
    case = delivery_case
    store = AnnouncementStore(
        case.root,
        case.staging,
        "post-reference-replacement",
        producer_cases.AnnouncementPolicy(interval_seconds=0),
        case.control,
    )
    replacement = store.write_page(
        [{**producer_cases.SOURCE_ROW, "title": "replacement after reference SHA"}],
        store.directory / "replacement.parquet",
        case.control,
    )
    original = checks._verify_reused_delivery_references

    def replace_after_reference(*args, **kwargs):
        result = original(*args, **kwargs)
        os.replace(replacement, store.target(DAY))
        return result

    monkeypatch.setattr(
        checks, "_verify_reused_delivery_references", replace_after_reference
    )
    with pytest.raises(AnnouncementError, match="file_changed_during_check"):
        next(_real_file_wrapper(case, monkeypatch, [case.record]))


def test_file_recovery_stable_original_delivery_uses_two_target_sha_and_one_sql(
    delivery_case, monkeypatch
):
    case = delivery_case
    hashes, audits, latest_queries = [], [], []
    real_fingerprint = checks.announcement_file_fingerprint
    real_audit = AnnouncementStore.audit_file
    real_materialization = checks.announcement_materialization

    def fingerprint(path):
        hashes.append(Path(path))
        return real_fingerprint(path)

    def audit(store, path, day):
        audits.append((Path(path), day))
        return real_audit(store, path, day)

    def materialization(instance, day):
        latest_queries.append(day)
        return real_materialization(instance, day)

    monkeypatch.setattr(checks, "announcement_file_fingerprint", fingerprint)
    monkeypatch.setattr(AnnouncementStore, "audit_file", audit)
    monkeypatch.setattr(checks, "announcement_materialization", materialization)
    events = list(_real_file_wrapper(case, monkeypatch, [case.record]))
    assert len(events) == 2 and isinstance(events[-1], dg.Output)
    evaluation = events[0]
    assert evaluation.passed
    assert evaluation.partition == DAY
    assert evaluation.target_materialization_data.storage_id == 11
    assert evaluation.target_materialization_data.run_id == ROOT_ID
    assert hashes.count(audits[0][0]) == 2
    assert len(hashes) == 3  # one real source page, two target fingerprints
    assert len(audits) == 1
    assert latest_queries == [DAY]


def test_native_check_only_root_plan_stays_independent(delivery_case):
    case = delivery_case
    context, _, calls = _native_root_context(
        case, explicit_steps=False, snapshot_kind="check"
    )
    case.execution_path.unlink()
    result = targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert result.window_identity is None
    assert not result.materializing
    assert [kind for kind, _ in calls] == ["root", "snapshot"]


@pytest.mark.parametrize("missing_snapshot", [False, True])
def test_ambiguous_root_without_native_plan_evidence_is_refused(
    delivery_case, missing_snapshot
):
    case = delivery_case
    context, root, calls = _native_root_context(case, explicit_steps=False)
    if missing_snapshot:
        context.instance.get_run_by_id = lambda _: root._replace(
            execution_plan_snapshot_id=None
        )
    else:
        context.instance.get_execution_plan_snapshot = lambda _: None
    with pytest.raises(AnnouncementError, match="check_root_intent_unknown"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert len([c for c in calls if c[0] == "root"]) <= 1


def test_native_manual_file_root_missing_execution_is_not_independent(delivery_case):
    case = delivery_case
    context, _, _ = _native_root_context(case, explicit_steps=False)
    case.execution_path.unlink()
    with pytest.raises(AnnouncementError, match="check_execution_missing"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)


def _other_window_delivery(case):
    """Produce a second legitimate window, rather than hand-writing its evidence."""
    root_id = "827546f1-f6fe-48f2-a5f2-e9d5a28cd01f"
    policy = producer_cases.AnnouncementPolicy(interval_seconds=0)
    control = producer_cases.AnnouncementControl()
    tags = announcement_manual_window_tags(
        root_id, DAY, DAY, staging=case.staging, policy=policy
    )

    def store_factory(day):
        return AnnouncementStore(
            case.root,
            case.staging,
            announcement_day_run_id(tags["anns_d/window_id"], day),
            policy,
            control,
        )

    result = execute_announcement_window(
        (DAY,),
        tags=tags,
        policy=policy,
        control=control,
        store_factory=store_factory,
        call_factory=lambda day, store: (
            lambda *_: (
                [{**producer_cases.SOURCE_ROW, "title": "second legitimate window"}],
                producer_cases.SOURCE_FIELDS,
            )
        ),
    )[DAY]
    record = SimpleNamespace(
        asset_materialization=dg.AssetMaterialization(
            asset_key=ANNOUNCEMENT_ASSET,
            partition=DAY,
            metadata={
                "goldenshare/fingerprint": dict(result.delivery["fingerprint"]),
                "goldenshare/announcement_identity": dict(result.identity),
                "goldenshare/announcement_checkpoint": str(result.checkpoint_path),
            },
        ),
        storage_id=12,
        event_log_entry=SimpleNamespace(run_id=root_id),
        timestamp=1235.0,
    )
    assert tags["anns_d/window_id"] != case.tags["anns_d/window_id"]
    return tags, record


@pytest.mark.parametrize("root_kind", ["frozen", "manual", "independent"])
def test_child_cannot_replace_original_root_with_another_valid_window(
    delivery_case, root_kind
):
    case = delivery_case
    context, root, _ = _native_root_context(
        case,
        explicit_steps=False,
        snapshot_kind="check" if root_kind == "independent" else "file",
    )
    if root_kind == "frozen":
        root = root._replace(tags=case.tags)
        context.instance.get_run_by_id = lambda _: root
    other_tags, other_record = _other_window_delivery(case)
    context.run.tags = other_tags
    context.instance.fetch_materializations = lambda *a, **k: SimpleNamespace(
        records=[other_record]
    )
    with pytest.raises(AnnouncementError, match="check_execution_identity"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)


@pytest.mark.parametrize("root_has_tags", [False, True])
def test_child_same_frozen_manual_intent_is_accepted(delivery_case, root_has_tags):
    case = delivery_case
    context, root, _ = _native_root_context(case, explicit_steps=False)
    if root_has_tags:
        root = root._replace(tags=case.tags)
        context.instance.get_run_by_id = lambda _: root
    context.run.tags = dict(case.tags)
    result = targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert result.window_identity["window_id"] == case.tags["anns_d/window_id"]
    assert result.records[DAY] is case.record


@pytest.mark.parametrize("root_has_tags", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("anns_d/window_id", "another-valid-window"),
        ("anns_d/execution_version", "3"),
        ("anns_d/start_date", "2023-06-08"),
        ("anns_d/end_date", "2023-06-10"),
        ("anns_d/started_at", "1.0"),
        ("anns_d/automatic", "true"),
    ],
)
def test_child_explicit_identity_field_must_match_original_execution(
    delivery_case, root_has_tags, field, value
):
    case = delivery_case
    context, root, _ = _native_root_context(case, explicit_steps=False)
    if root_has_tags:
        root = root._replace(tags=case.tags)
        context.instance.get_run_by_id = lambda _: root
    context.run.tags = {field: value}
    with pytest.raises(AnnouncementError, match="check_execution_identity"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)


def test_current_full_job_uses_actual_asset_steps_despite_empty_run_selection(
    delivery_case,
):
    context, _ = producer_cases._reexecution_context(delivery_case)
    context.run.asset_selection = frozenset()
    context.run.step_keys_to_execute = [ANNOUNCEMENT_ASSET]
    assert targets.announcement_asset_is_executing(context)
    context.run.asset_selection = {dg.AssetKey(ANNOUNCEMENT_ASSET)}
    context.run.step_keys_to_execute = [
        f"{ANNOUNCEMENT_ASSET}_{ANNOUNCEMENT_CHECKS[0]}"
    ]
    assert not targets.announcement_asset_is_executing(context)


def test_native_from_failure_uses_none_selection_roots_frozen_file_plan(
    delivery_case, monkeypatch
):
    """Real ephemeral root/plan/check history and check-only retry; no source calls.

    The file/checkpoint came from the actual temporary producer fixture. Only
    the first delivery rule result is deliberately failed to create a retry.
    """
    case = delivery_case
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(case.root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(case.staging))
    state = {"fail": True, "asset_calls": 0, "root_reads": 0, "plan_reads": 0}
    original_evaluate = checks.evaluate_announcement_check

    @dg.asset(name=ANNOUNCEMENT_ASSET, partitions_def=anns_d_natural_days)
    def producer(context):
        state["asset_calls"] += 1
        return dg.MaterializeResult(metadata=case.record.asset_materialization.metadata)

    def evaluate(*args, **kwargs):
        result = original_evaluate(*args, **kwargs)
        if state["fail"] and kwargs["reconciliation"]:
            assert result.passed
            return dg.AssetCheckResult(passed=False)
        return result

    monkeypatch.setattr(checks, "evaluate_announcement_check", evaluate)
    definitions = dg.Definitions(
        assets=[producer],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[
            dg.define_asset_job("manual_none_root", executor_def=dg.in_process_executor)
        ],
        resources={"lake_root": LakeRootResource(root_path=str(case.root))},
    )
    job = definitions.resolve_job_def("manual_none_root")
    tags = {PARTITION_NAME_TAG: DAY}
    plan = create_execution_plan(job, tags=tags)
    with dg.DagsterInstance.ephemeral() as instance:
        parent = instance.create_run(
            job_name=job.name,
            run_id=ROOT_ID,
            run_config={},
            status=dg.DagsterRunStatus.NOT_STARTED,
            tags=tags,
            root_run_id=None,
            parent_run_id=None,
            step_keys_to_execute=None,
            execution_plan_snapshot=snapshot_from_execution_plan(
                plan, job.get_job_snapshot_id()
            ),
            job_snapshot=job.get_job_snapshot(),
            parent_job_snapshot=None,
            asset_selection=None,
            asset_check_selection=None,
            resolved_op_selection=None,
            op_selection=None,
            remote_job_origin=None,
            job_code_origin=None,
            asset_graph=definitions.resolve_asset_graph(),
        )
        assert parent.asset_selection is parent.step_keys_to_execute is None
        assert parent.resolved_op_selection is None
        initial = execute_run(InMemoryJob(job), parent, instance, raise_on_error=False)
        assert not initial.success
        parent = instance.get_run_by_id(ROOT_ID)
        steps, known = KnownExecutionState.build_resume_retry_reexecution(
            instance, parent
        )
        assert len(steps) == 1
        check_key = dg.AssetCheckKey(
            dg.AssetKey(ANNOUNCEMENT_ASSET), ANNOUNCEMENT_CHECKS[1]
        )
        retry_job = job.get_subset(
            asset_selection=set(), asset_check_selection={check_key}
        )
        assert not retry_job.asset_layer.selected_asset_keys
        retry_plan = create_execution_plan(
            retry_job, step_keys_to_execute=steps, known_state=known, tags=tags
        )
        child = instance.create_run_for_job(
            retry_job,
            execution_plan=retry_plan,
            tags=tags,
            root_run_id=ROOT_ID,
            parent_run_id=ROOT_ID,
        )
        get_run = instance.get_run_by_id
        get_plan = instance.get_execution_plan_snapshot

        def counted_run(run_id):
            state["root_reads"] += int(run_id == ROOT_ID)
            return get_run(run_id)

        def counted_plan(identifier):
            state["plan_reads"] += int(identifier == parent.execution_plan_snapshot_id)
            return get_plan(identifier)

        monkeypatch.setattr(instance, "get_run_by_id", counted_run)
        monkeypatch.setattr(instance, "get_execution_plan_snapshot", counted_plan)
        state["fail"] = False
        retry = execute_run(
            InMemoryJob(retry_job), child, instance, raise_on_error=False
        )
        assert retry.success
        assert state["asset_calls"] == 1
        events = instance.all_logs(child.run_id)
        assert not any(event.asset_materialization for event in events)
        evaluations = [
            e.asset_check_evaluation for e in events if e.asset_check_evaluation
        ]
        assert len(evaluations) == 1
        assert evaluations[0].passed and evaluations[0].partition == DAY
        assert evaluations[0].target_materialization_data.run_id == ROOT_ID
        # Framework execution can also load the plan/root; production target
        # selection itself is independently bounded in the metadata tests above.
        assert state["root_reads"] >= 1 and state["plan_reads"] >= 1
