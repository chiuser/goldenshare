"""Asset recovery keeps the original run's dates, config, and window.

The source response and run lookup are replaced; the real asset wrapper,
capture/build/promote, checkpoints and temporary Lake files remain active.
Literal six-field responses retain the source's nullable URL and rec_time.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg
import pytest
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import (
    ReexecutionOptions,
    _reexecute_job,
    create_execution_plan,
    execute_run,
)
from dagster._core.execution.plan.state import KnownExecutionState
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
    PARTITION_NAME_TAG,
)

from orchestrator.defs import anns_d_window as window_module
from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementControl,
    AnnouncementWindowBudget,
    announcement_atomic_json,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_FIELDS,
    AnnouncementError,
)
from orchestrator.defs.anns_d_window import (
    announcement_day_run_id,
    announcement_manual_window_id,
    announcement_manual_window_tags,
    announcement_refresh_dates,
    announcement_schedule_tags,
    announcement_window_tags,
)
from orchestrator.defs.assets import anns_d as asset_module
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.anns_d import (
    AnnouncementPolicy,
    AnnouncementRawConfig,
)

DAY = "2023-06-09"
ROOT_ID = "e2cfdc0b-952d-4664-8957-d2a1ac04822b"


def _run(run_id, tags, *, root_id=None, interval=0):
    return SimpleNamespace(
        run_id=run_id,
        root_run_id=root_id,
        tags=dict(tags),
        run_config={
            "ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": interval}}}
        },
        status=dg.DagsterRunStatus.STARTED,
        asset_selection={dg.AssetKey(ANNOUNCEMENT_ASSET)},
        step_keys_to_execute=[ANNOUNCEMENT_ASSET],
        resolved_op_selection=None,
    )


@pytest.fixture
def asset_case(tmp_path, monkeypatch):
    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    calls, metadata, runs, queries = [], [], {}, []
    source_state = {
        "rows": [
            {
                "ann_date": "20230609",
                "ts_code": "155162.SH",
                "name": "19津投04",
                "title": "literal original A",
                "url": None,
                "rec_time": None,
            }
        ]
    }
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    # Only formal-volume availability is substituted. Real file IO uses tmp_path.
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda *_: None)

    def source(params, control):
        calls.append(params.copy())
        return [
            {**row, "ann_date": params["ann_date"]} for row in source_state["rows"]
        ], ANNOUNCEMENT_FIELDS

    monkeypatch.setattr(asset_module, "AnnouncementProcessCall", lambda *_: source)

    def get_run(run_id):
        queries.append(run_id)
        return runs.get(run_id)

    def invoke(run, *, days=(DAY,), interval=0):
        runs[run.run_id] = run
        context = SimpleNamespace(
            partition_keys=days,
            run=run,
            instance=SimpleNamespace(get_run_by_id=get_run),
            log=SimpleNamespace(info=lambda _: None),
            add_asset_metadata=lambda values, *, partition_key: metadata.append(
                (partition_key, values)
            ),
        )
        return asset_module.raw_tushare_anns_d.op.compute_fn.decorated_fn(
            context,
            AnnouncementRawConfig(interval_seconds=interval),
            LakeRootResource(root_path=str(root)),
            TushareResource(token="unused-isolated-placeholder"),
        )

    def files():
        return {
            str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob("*")
            if path.is_file()
        }

    return SimpleNamespace(
        root=root,
        staging=staging,
        calls=calls,
        metadata=metadata,
        runs=runs,
        queries=queries,
        invoke=invoke,
        files=files,
        source_state=source_state,
    )


def _completed_root(case):
    tags = announcement_window_tags("root-window-a", DAY, DAY)
    root = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY, **tags})
    assert isinstance(case.invoke(root), dg.MaterializeResult)
    assert case.calls == [{"ann_date": "20230609", "limit": 2000, "offset": 0}]
    return root, tags


def test_asset_retry_rejects_another_valid_window_before_any_file_or_source_action(
    asset_case,
):
    case = asset_case
    _completed_root(case)
    before, calls = case.files(), len(case.calls)
    case.source_state["rows"][0]["title"] = "literal different B"
    other = announcement_window_tags("child-window-b", DAY, DAY)
    child = _run("retry-b", {PARTITION_NAME_TAG: DAY, **other}, root_id=ROOT_ID)
    with pytest.raises(AnnouncementError):
        case.invoke(child)
    assert case.files() == before
    assert len(case.calls) == calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("anns_d/window_id", "another-window"),
        ("anns_d/start_date", "2023-06-08"),
        ("anns_d/end_date", "2023-06-10"),
        ("anns_d/started_at", "1.0"),
        ("anns_d/execution_version", "3"),
        ("anns_d/automatic", "true"),
        ("anns_d/automatic", "false"),
    ],
)
def test_every_partial_child_identity_conflict_is_rejected(asset_case, field, value):
    case = asset_case
    _completed_root(case)
    before, calls = case.files(), len(case.calls)
    child = _run(
        "partial-child",
        {PARTITION_NAME_TAG: DAY, field: value},
        root_id=ROOT_ID,
    )
    with pytest.raises(AnnouncementError, match="window_intent"):
        case.invoke(child)
    assert case.files() == before and len(case.calls) == calls


@pytest.mark.parametrize("root_has_tags", [False, True])
def test_same_root_completed_manual_delivery_does_not_repeat_source(
    asset_case, root_has_tags
):
    case = asset_case
    tags = {PARTITION_NAME_TAG: DAY}
    if root_has_tags:
        tags.update(announcement_window_tags("root-fixed-window", DAY, DAY))
    root = _run(ROOT_ID, tags)
    case.invoke(root)
    calls = len(case.calls)
    before_targets = {k: v for k, v in case.files().items() if k.startswith("lake/")}
    case.queries.clear()
    child = _run("same-root-retry", tags, root_id=ROOT_ID)
    assert isinstance(case.invoke(child), dg.MaterializeResult)
    assert len(case.calls) == calls
    assert {
        k: v for k, v in case.files().items() if k.startswith("lake/")
    } == before_targets
    assert case.queries.count(ROOT_ID) == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_root_failed_before_initialization_can_still_start_its_original_window(
    asset_case, automatic
):
    case = asset_case
    if automatic:
        tick = datetime(2023, 6, 8, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
        days = announcement_refresh_dates(tick)
        tags = {
            **announcement_schedule_tags(tick),
            ASSET_PARTITION_RANGE_START_TAG: days[0],
            ASSET_PARTITION_RANGE_END_TAG: days[-1],
        }
        assert days == (
            "2023-06-01",
            "2023-06-02",
            "2023-06-03",
            "2023-06-04",
            "2023-06-05",
            "2023-06-06",
            "2023-06-07",
            "2023-06-08",
            "2023-06-09",
        )
    else:
        days, tags = (DAY,), {PARTITION_NAME_TAG: DAY}
    case.runs[ROOT_ID] = _run(ROOT_ID, tags)
    assert case.files() == {}
    child = _run("pre-initialization-retry", tags, root_id=ROOT_ID)
    assert isinstance(case.invoke(child, days=days), dg.MaterializeResult)
    assert len(case.calls) == len(days)
    window_id = (
        tags["anns_d/window_id"]
        if automatic
        else announcement_manual_window_id(ROOT_ID, DAY, DAY)
    )
    document = json.loads(
        (case.staging / "anns_d/windows" / window_id / "execution.json").read_text()
    )
    assert document["identity"]["window_id"] == window_id
    assert document["identity"]["automatic"] is automatic
    if automatic:
        assert str(document["identity"]["started_at"]) == tags["anns_d/started_at"]
        # Reexecute this now-complete automatic window under the same original
        # root: all nine persisted days are reused without another source call.
        case.invoke(_run("completed-auto-retry", tags, root_id=ROOT_ID), days=days)
        assert len(case.calls) == 9
        restored = json.loads(
            (case.staging / "anns_d/windows" / window_id / "execution.json").read_text()
        )
        assert restored["identity"] == document["identity"]
        assert restored["requests"] == 9
        assert case.queries.count(ROOT_ID) == 2


@pytest.mark.parametrize("damage", ["date", "half-range", "both", "policy", "missing"])
def test_original_root_date_policy_or_missing_run_is_rejected_before_write(
    asset_case, damage
):
    case = asset_case
    root, tags = _completed_root(case)
    if damage == "date":
        child_tags, days, interval = (
            {PARTITION_NAME_TAG: "2023-06-08"},
            ("2023-06-08",),
            0,
        )
    else:
        child_tags, days, interval = {PARTITION_NAME_TAG: DAY, **tags}, (DAY,), 0
    if damage == "half-range":
        root.tags = {ASSET_PARTITION_RANGE_START_TAG: DAY}
    elif damage == "both":
        root.tags[ASSET_PARTITION_RANGE_START_TAG] = DAY
        root.tags[ASSET_PARTITION_RANGE_END_TAG] = DAY
    elif damage == "policy":
        interval = 1
    elif damage == "missing":
        del case.runs[ROOT_ID]
    before, count = case.files(), len(case.calls)
    child = _run("invalid-root-retry", child_tags, root_id=ROOT_ID, interval=interval)
    with pytest.raises(AnnouncementError):
        case.invoke(child, days=days, interval=interval)
    assert case.files() == before and len(case.calls) == count


@pytest.mark.parametrize("kind", ["admission", "budget", "execution", "day-checkpoint"])
def test_old_p2_manual_root_evidence_is_never_implicitly_migrated(asset_case, kind):
    case = asset_case
    case.runs[ROOT_ID] = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    if kind == "day-checkpoint":
        old_path = (
            case.staging
            / "anns_d"
            / f"run_id={announcement_day_run_id(ROOT_ID, DAY)}"
            / "delivery.json"
        )
    else:
        old_path = case.staging / "anns_d/windows" / ROOT_ID / f"{kind}.json"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b'{"historical_test_evidence":"must remain unchanged"}')
    before = case.files()
    child = _run("old-p2-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
    with pytest.raises(AnnouncementError, match="legacy_execution"):
        case.invoke(child)
    assert case.files() == before and case.calls == []


def test_independent_new_roots_make_distinct_fresh_observations(asset_case):
    case = asset_case
    case.invoke(_run(ROOT_ID, {PARTITION_NAME_TAG: DAY}))
    other_id = "4af7673d-b7ef-4d5f-b1ec-9b61b052bb05"
    case.invoke(_run(other_id, {PARTITION_NAME_TAG: DAY}))
    assert len(case.calls) == 2
    directories = list((case.staging / "anns_d/windows").iterdir())
    assert {path.name for path in directories} == {
        announcement_manual_window_id(identifier, DAY, DAY)
        for identifier in (ROOT_ID, other_id)
    }


@pytest.mark.parametrize("consumed", [False, True])
def test_manual_root_zero_initialization_or_consumed_budget_is_preserved(
    asset_case, consumed
):
    case = asset_case
    case.runs[ROOT_ID] = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    policy, control = AnnouncementPolicy(interval_seconds=0), AnnouncementControl()
    tags = announcement_manual_window_tags(
        ROOT_ID, DAY, DAY, staging=case.staging, policy=policy
    )
    identity = window_module.announcement_window_identity((DAY,), tags, policy)
    directory = case.staging / "anns_d/windows" / tags["anns_d/window_id"]
    budget = AnnouncementWindowBudget(
        directory / "budget.json",
        tags["anns_d/window_id"],
        policy,
        identity=identity,
        require_existing=True,
    )
    announcement_atomic_json(budget.path, budget.initial_document())
    if consumed:
        # The real initializer, then a real persisted claim ahead of its summary.
        window_module._initialize_execution(
            directory, identity, budget, control, case.staging
        )
        assert budget.claim(control, DAY) == 1
    assert not consumed or json.loads(budget.path.read_text())["requests"] == 1
    child = _run("budget-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
    case.invoke(child)
    document = json.loads((directory / "execution.json").read_text())
    assert document["identity"]["started_at"] == identity["started_at"]
    assert document["requests"] == (2 if consumed else 1)
    assert document["day_requests"] == {DAY: 2 if consumed else 1}
    assert len(case.calls) == 1


def test_consumed_budget_without_execution_is_rejected_without_change(asset_case):
    case = asset_case
    case.runs[ROOT_ID] = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    policy, control = AnnouncementPolicy(interval_seconds=0), AnnouncementControl()
    tags = announcement_manual_window_tags(
        ROOT_ID, DAY, DAY, staging=case.staging, policy=policy
    )
    identity = window_module.announcement_window_identity((DAY,), tags, policy)
    path = case.staging / "anns_d/windows" / tags["anns_d/window_id"] / "budget.json"
    budget = AnnouncementWindowBudget(
        path, tags["anns_d/window_id"], policy, identity=identity, require_existing=True
    )
    announcement_atomic_json(path, budget.initial_document())
    budget.claim(control, DAY)
    before = case.files()
    with pytest.raises(AnnouncementError, match="window_checkpoint"):
        case.invoke(
            _run("missing-execution-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
        )
    assert case.files() == before and case.calls == []


def test_existing_execution_without_budget_is_rejected_without_change(asset_case):
    case = asset_case
    root = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    case.invoke(root)
    window_id = announcement_manual_window_id(ROOT_ID, DAY, DAY)
    budget_path = case.staging / "anns_d/windows" / window_id / "budget.json"
    # Deliberate corruption of only this test's generated temporary JSON.
    budget_path.unlink()
    before, calls = case.files(), len(case.calls)
    with pytest.raises(AnnouncementError, match="budget_missing"):
        case.invoke(
            _run("missing-budget-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
        )
    assert case.files() == before and len(case.calls) == calls


def test_root_default_interval_is_the_existing_five_seconds(asset_case):
    case = asset_case
    root = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    root.run_config = {}
    case.runs[ROOT_ID] = root
    child = _run("default-policy-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
    context = SimpleNamespace(
        run=child,
        instance=SimpleNamespace(get_run_by_id=lambda _: root),
    )
    tags = asset_module._announcement_asset_window_tags(
        context, (DAY,), AnnouncementPolicy(), case.staging
    )
    assert tags["anns_d/window_id"] == announcement_manual_window_id(ROOT_ID, DAY, DAY)
    assert case.calls == [] and case.files() == {}


@pytest.mark.parametrize(
    "field,value", [("anns_d/start_date", "2023-06-08"), ("anns_d/automatic", "false")]
)
def test_new_run_also_rejects_partial_tags_instead_of_discarding_them(
    asset_case, field, value
):
    case = asset_case
    run = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY, field: value})
    with pytest.raises(AnnouncementError, match="window_intent"):
        case.invoke(run)
    assert case.files() == {} and case.calls == []


def test_native_from_failure_reexecutes_asset_with_original_window_and_requests(
    asset_case, monkeypatch
):
    """Native Dagster run, plan, from-failure, checks and storage are real.

    Only source transport and formal-volume availability are replaced.
    """
    from orchestrator.defs import anns_d_run_intent as run_intent
    from orchestrator.defs.checks import anns_d_checks as checks

    case = asset_case
    state = {"fail": True}
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(case.root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(case.staging))

    def source(params, control):
        case.calls.append(params.copy())
        if state["fail"]:
            raise AnnouncementError("announcement_source_call_failed")
        return case.source_state["rows"], ANNOUNCEMENT_FIELDS

    monkeypatch.setattr(asset_module, "AnnouncementProcessCall", lambda *_: source)
    definitions = dg.Definitions(
        assets=[asset_module.raw_tushare_anns_d],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[
            dg.define_asset_job(
                "native_asset_retry", executor_def=dg.in_process_executor
            )
        ],
        resources={
            "lake_root": LakeRootResource(root_path=str(case.root)),
            "tushare": TushareResource(token="unused-isolated-placeholder"),
        },
    )
    job = definitions.resolve_job_def("native_asset_retry")
    config = {"ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}}
    with dg.DagsterInstance.ephemeral() as instance:
        original = job.execute_in_process(
            instance=instance,
            partition_key=DAY,
            run_config=config,
            raise_on_error=False,
        )
        assert not original.success and len(case.calls) == 3
        parent = instance.get_run_by_id(original.run_id)
        window_id = announcement_manual_window_id(parent.run_id, DAY, DAY)
        execution_path = case.staging / "anns_d/windows" / window_id / "execution.json"
        before = json.loads(execution_path.read_text())
        assert before["requests"] == 3 and before["failed_days"] == [DAY]
        steps, known = KnownExecutionState.build_resume_retry_reexecution(
            instance, parent
        )
        assert ANNOUNCEMENT_ASSET in steps
        plan = create_execution_plan(
            job,
            run_config=parent.run_config,
            step_keys_to_execute=steps,
            known_state=known,
            tags=parent.tags,
        )
        child = instance.create_run_for_job(
            job,
            execution_plan=plan,
            run_config=parent.run_config,
            tags=parent.tags,
            root_run_id=parent.run_id,
            parent_run_id=parent.run_id,
        )
        intent_reads = []
        original_intent = run_intent._root_snapshot_file_intent

        def snapshot_intent(root, current_instance):
            intent_reads.append(root.run_id)
            return original_intent(root, current_instance)

        monkeypatch.setattr(run_intent, "_root_snapshot_file_intent", snapshot_intent)
        state["fail"] = False
        result = execute_run(InMemoryJob(job), child, instance, raise_on_error=False)
        assert result.success
        assert intent_reads == [parent.run_id]
        after = json.loads(execution_path.read_text())
        assert after["identity"] == before["identity"]
        assert after["requests"] == 4 and after["day_requests"] == {DAY: 4}
        assert after["failed_days"] == []
        events = instance.all_logs(child.run_id)
        materials = [
            event.asset_materialization
            for event in events
            if event.asset_materialization
        ]
        evaluations = [
            event.asset_check_evaluation
            for event in events
            if event.asset_check_evaluation
        ]
        assert len(materials) == 1 and materials[0].partition == DAY
        assert len(evaluations) == 2 and all(event.passed for event in evaluations)
        assert all(event.partition == DAY for event in evaluations)
        assert all(
            event.target_materialization_data.run_id == child.run_id
            for event in evaluations
        )


def test_asset_retry_rejects_partial_intent_without_window_id_before_any_action(
    asset_case,
):
    case = asset_case
    _completed_root(case)
    before, calls = case.files(), len(case.calls)
    child = _run(
        "retry-partial",
        {PARTITION_NAME_TAG: DAY, "anns_d/start_date": "2023-06-08"},
        root_id=ROOT_ID,
    )
    with pytest.raises(AnnouncementError):
        case.invoke(child)
    assert case.files() == before
    assert len(case.calls) == calls


def test_native_check_only_root_cannot_start_asset_through_full_job_reexecution(
    asset_case, monkeypatch
):
    """Real pinned _reexecute_job path; parent did not execute any asset.

    Its default interval remains five seconds, matching the root config rather
    than relying on a policy mismatch to reject the wrong execution.
    """
    from orchestrator.defs.checks import anns_d_checks as checks

    case = asset_case
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(case.root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(case.staging))
    definitions = dg.Definitions(
        assets=[asset_module.raw_tushare_anns_d],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[
            dg.define_asset_job(
                "native_check_root", executor_def=dg.in_process_executor
            )
        ],
        resources={
            "lake_root": LakeRootResource(root_path=str(case.root)),
            "tushare": TushareResource(token="unused-isolated-placeholder"),
        },
    )
    full_job = definitions.resolve_job_def("native_check_root")
    check_key = checks.raw_tushare_anns_d_file_contract_check.check_keys
    check_job = full_job.get_subset(
        asset_selection=set(), asset_check_selection=check_key
    )
    instance_directory = case.staging.parent / "native-instance"
    instance_directory.mkdir()
    with dg.DagsterInstance.ephemeral(tempdir=str(instance_directory)) as instance:
        parent_result = check_job.execute_in_process(
            instance=instance, partition_key=DAY, raise_on_error=False
        )
        parent = instance.get_run_by_id(parent_result.run_id)
        snapshot = instance.get_execution_plan_snapshot(
            parent.execution_plan_snapshot_id
        )
        assert not snapshot.asset_selection and snapshot.asset_check_keys == check_key
        assert not parent.asset_selection and case.calls == []
        before = case.files()
        result = _reexecute_job(
            InMemoryJob(full_job),
            run_config={},
            reexecution_options=ReexecutionOptions(parent_run_id=parent.run_id),
            tags=parent.tags,
            instance=instance,
            raise_on_error=False,
        )
        assert not result.success
        failures = [
            event.dagster_event.event_specific_data.error
            for event in instance.all_logs(result.run_id)
            if event.dagster_event and event.dagster_event.is_step_failure
        ]
        assert failures
        failure = failures[0]
        while failure.cause:
            failure = failure.cause
        assert "announcement_root_asset_not_selected" in failure.message
        assert case.calls == []
        assert {
            path: content
            for path, content in case.files().items()
            if path.startswith(("lake/", "staging/"))
        } == {
            path: content
            for path, content in before.items()
            if path.startswith(("lake/", "staging/"))
        }


def test_manual_root_with_unknown_selection_and_no_plan_is_refused(asset_case):
    case = asset_case
    root = _run(ROOT_ID, {PARTITION_NAME_TAG: DAY})
    # Deliberately remove original intent evidence; do not borrow the current job.
    root.asset_selection = root.step_keys_to_execute = root.resolved_op_selection = None
    case.runs[ROOT_ID] = root
    child = _run("unknown-root-retry", {PARTITION_NAME_TAG: DAY}, root_id=ROOT_ID)
    with pytest.raises(AnnouncementError, match="root_intent_unknown"):
        case.invoke(child)
    assert case.files() == {} and case.calls == []
