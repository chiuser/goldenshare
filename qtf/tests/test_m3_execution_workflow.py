from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qtf.adapters.persistence.models.research import ExperimentRevision, Research
from qtf.adapters.persistence.models.runtime import ExperimentRun, InputPreflight, InputPreflightIssue
from qtf.adapters.persistence.repositories.research_repository import SqlAlchemyResearchRepository
from qtf.adapters.persistence.repositories.runtime_repository import SqlAlchemyRuntimeRepository
from qtf.application.services.experiment_service import ExperimentService
from qtf.application.services.input_preflight_service import InputPreflightService
from qtf.application.services.plan_freeze_service import PlanFreezeService
from qtf.application.services.research_service import ResearchService
from qtf.contracts.errors import QtfDraftConflict, QtfInputPreflightBlocked, QtfPlanNotApproved, QtfStateConflict
from qtf.contracts.research import CreateResearchCommand, RevisionContent
from qtf.contracts.runtime import DatasetEvidence, ExperimentRunStatus, InputPreflightStatus, ValidationStatus
from qtf.engine.canonical_hash import canonical_json_hash
from qtf.modules.sector.executor import SectorExperimentExecutor
from qtf.modules.sector.factor_kernel import SectorObservation
from qtf.modules.sector.input_contract import (
    SECTOR_L2_SOURCE_CONTRACT,
    SectorHierarchyNode,
    SectorInputSnapshot,
)
from qtf.modules.sector.input_preflight import evaluate_sector_input
from src.foundation.models.base import Base


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach_schemas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("ATTACH DATABASE ':memory:' AS qtf")
        cursor.execute("ATTACH DATABASE ':memory:' AS ops")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            Research.__table__,
            ExperimentRevision.__table__,
            InputPreflight.__table__,
            InputPreflightIssue.__table__,
            ExperimentRun.__table__,
        ],
    )
    with Session(engine) as active:
        yield active


class StubSource:
    def __init__(self, snapshot: SectorInputSnapshot) -> None:
        self.snapshot = snapshot
        self.read_count = 0

    def read(self, _request):  # type: ignore[no-untyped-def]
        self.read_count += 1
        return self.snapshot


class StubStager:
    def __init__(self, session: Session, *, fail_after_flush: bool = False) -> None:
        self.session = session
        self.fail_after_flush = fail_after_flush

    def stage(self, intent) -> int:  # type: ignore[no-untyped-def]
        del intent
        if self.fail_after_flush:
            raise RuntimeError("staging failed")
        current_run_id = self.session.scalar(select(func.max(ExperimentRun.id))) or 0
        return 500 + int(current_run_id)


class UnitOfWork:
    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


class Observer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, str]] = []

    def stage(self, *, task_run_id: int, stage_key: str, title: str, sequence_no: int) -> None:
        del task_run_id, title, sequence_no
        if self.fail:
            raise RuntimeError("ops unavailable")
        self.events.append(("stage", stage_key))

    def progress(self, *, task_run_id: int, stage_key: str, completed: int, total: int, message: str) -> None:
        del task_run_id, completed, total, message
        if self.fail:
            raise RuntimeError("ops unavailable")
        self.events.append(("progress", stage_key))

    def issue(self, *, task_run_id: int, code: str, message: str) -> None:
        del task_run_id, message
        if self.fail:
            raise RuntimeError("ops unavailable")
        self.events.append(("issue", code))


class CancellationProbe:
    def __init__(self, values: list[bool] | None = None) -> None:
        self.values = list(values or [])

    def is_cancel_requested(self, _task_run_id: int) -> bool:
        return self.values.pop(0) if self.values else False


def test_draft_preflight_is_idempotent_and_missing_group_day_is_not_filled(session: Session) -> None:
    bundle = _create_complete_draft(session)
    snapshot = _snapshot(missing=(date(2026, 8, 4), "B"))
    source = StubSource(snapshot)
    service = InputPreflightService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        key_factory=lambda: "preflight-1",
    )

    first = service.preview(
        research_key=bundle.research.research_key,
        request_key="request-1",
        draft_version=1,
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 4),
    )
    session.commit()
    replay = service.preview(
        research_key=bundle.research.research_key,
        request_key="request-1",
        draft_version=1,
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 4),
    )

    assert first.status is InputPreflightStatus.PASS
    assert first.excluded_group_day_count == 1
    assert first.valid_group_day_count == 1
    assert any(issue.code == "INCOMPLETE_GROUP_DAY" for issue in first.issues)
    assert replay.id == first.id
    assert source.read_count == 1


def test_blocked_preflight_contains_upstream_owner_and_cannot_freeze(session: Session) -> None:
    bundle = _create_complete_draft(session)
    source = StubSource(_snapshot(duplicate=True))
    preflight = InputPreflightService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        key_factory=lambda: "preflight-blocked",
    ).preview(
        research_key=bundle.research.research_key,
        request_key="blocked-request",
        draft_version=1,
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 4),
    )
    session.commit()

    assert preflight.status is InputPreflightStatus.BLOCKED
    assert preflight.plan is None
    assert {issue.remediation_owner.value for issue in preflight.issues} == {"PROD"}
    with pytest.raises(QtfInputPreflightBlocked, match="blocked"):
        PlanFreezeService(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
        ).freeze(
            research_key=bundle.research.research_key,
            draft_version=1,
            preflight_key=preflight.preflight_key,
            approved_plan_hash="0" * 64,
            acknowledged_exclusions=True,
            frozen_by_user_id=7,
        )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("bad_hierarchy", "HIERARCHY_PARENT_INVALID"),
        ("non_trading_date", "DC_DAILY_NON_TRADING_DATE"),
        ("invalid_amount", "DC_DAILY_VALUE_INVALID"),
    ],
)
def test_input_preflight_blocks_invalid_hierarchy_calendar_and_values(
    case: str,
    expected_code: str,
) -> None:
    now = datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc)
    if case == "bad_hierarchy":
        snapshot = _snapshot(
            hierarchy=(
                SectorHierarchyNode("P", "父行业", 1, None, "P", 1, "v1", now),
                SectorHierarchyNode("A", "子行业A", 2, "MISSING", "MISSING", 1, "v1", now),
                SectorHierarchyNode("B", "子行业B", 2, "P", "P", 2, "v1", now),
            )
        )
    elif case == "non_trading_date":
        snapshot = _snapshot(
            trade_dates=(date(2026, 8, 3),),
            include_observation_date=date(2026, 8, 4),
        )
    else:
        snapshot = _snapshot(invalid_amount=True)
    evaluation = evaluate_sector_input(
        snapshot,
        draft_effective_params=_draft_content().effective_params,
        success_definition=_draft_content().success_definition,
    )

    assert evaluation.status is InputPreflightStatus.BLOCKED
    assert evaluation.plan is None
    assert expected_code in {issue.code for issue in evaluation.issues}


def test_input_preflight_small_group_never_creates_an_evaluable_group_day() -> None:
    content = _draft_content(minimum_group_size=3)
    evaluation = evaluate_sector_input(
        _snapshot(),
        draft_effective_params=content.effective_params,
        success_definition=content.success_definition,
    )

    assert evaluation.status is InputPreflightStatus.BLOCKED
    assert evaluation.valid_group_days == ()
    assert {issue.code for issue in evaluation.issues} >= {"GROUP_BELOW_MINIMUM", "NO_VALID_GROUP_DAY"}


def test_draft_or_plan_change_invalidates_freeze(session: Session) -> None:
    bundle, preflight = _preview_pass(session)
    changed = replace(bundle.revision.content, problem_statement="changed after preview")
    SqlAlchemyResearchRepository(session).update_draft(
        revision_key=bundle.revision.revision_key,
        expected_draft_version=1,
        content=changed,
    )
    session.commit()

    with pytest.raises(QtfDraftConflict):
        PlanFreezeService(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
        ).freeze(
            research_key=bundle.research.research_key,
            draft_version=2,
            preflight_key=preflight.preflight_key,
            approved_plan_hash=preflight.plan.plan_hash,  # type: ignore[union-attr]
            acknowledged_exclusions=True,
            frozen_by_user_id=7,
        )


def test_newer_preflight_supersedes_old_plan(session: Session) -> None:
    bundle, first = _preview_pass(session)
    source = StubSource(_snapshot())
    second = InputPreflightService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        key_factory=lambda: "preflight-newer",
    ).preview(
        research_key=bundle.research.research_key,
        request_key="preflight-newer-request",
        draft_version=1,
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 4),
    )
    session.commit()
    assert second.id != first.id
    assert first.plan is not None

    with pytest.raises(QtfPlanNotApproved, match="superseded"):
        PlanFreezeService(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
        ).freeze(
            research_key=bundle.research.research_key,
            draft_version=1,
            preflight_key=first.preflight_key,
            approved_plan_hash=first.plan.plan_hash,
            acknowledged_exclusions=True,
            frozen_by_user_id=7,
        )


def test_task_staging_failure_rolls_back_the_planned_qtf_run(session: Session) -> None:
    frozen = _freeze(session)
    service = ExperimentService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        task_run_stager=StubStager(session, fail_after_flush=True),
        key_factory=lambda: "run-rollback",
    )
    with pytest.raises(RuntimeError, match="staging failed"):
        service.create_run(
            revision_key=frozen.revision.revision_key,
            request_key="run-request",
            revision_hash=frozen.revision.revision_hash or "",
            requested_by_user_id=7,
        )
    session.rollback()

    assert session.scalar(select(func.count()).select_from(ExperimentRun)) == 0


def test_illegal_run_transition_is_rejected(session: Session) -> None:
    run, _ = _queued_run(session, request_key="run-illegal-transition")
    repository = SqlAlchemyRuntimeRepository(session)
    repository.update_run(run.run_key, status=ExperimentRunStatus.CANCELED.value)
    session.commit()

    with pytest.raises(QtfStateConflict, match="unsupported experiment run transition"):
        repository.update_run(run.run_key, status=ExperimentRunStatus.EXECUTING.value)


def test_executor_reads_once_for_all_candidates_and_observer_failure_does_not_rollback_qtf(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, frozen = _queued_run(session, request_key="run-success")
    source = StubSource(_snapshot(content_hash=str(frozen.revision.content.budget["input_scope"]["source_content_hash"])))
    calls: list[object] = []
    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", lambda **kwargs: calls.append(kwargs))
    observer = Observer(fail=True)

    outcome = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        unit_of_work=UnitOfWork(session),
        observer=observer,
        cancellation_probe=CancellationProbe(),
        release_commit="a" * 40,
    ).execute(run_key=run.run_key, task_run_id=99)

    persisted = SqlAlchemyRuntimeRepository(session).get_run_by_key(run.run_key)
    assert outcome.status == "success"
    assert outcome.observer_degraded is True
    assert source.read_count == 1
    assert len(calls) == 4
    assert persisted.status is ExperimentRunStatus.COMPLETED
    assert persisted.validation_status is ValidationStatus.PENDING
    assert persisted.completed_parameter_set_count == 4
    assert persisted.runtime_fingerprint["observer_status"] == "DEGRADED"


def test_each_new_run_rereads_source_but_each_run_shares_one_immutable_input(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_run, frozen = _queued_run(session, request_key="run-read-one")
    second_run, _ = _queued_run(session, request_key="run-read-two", frozen=frozen)
    source = StubSource(_snapshot(content_hash=str(frozen.revision.content.budget["input_scope"]["source_content_hash"])))
    calls: list[object] = []
    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", lambda **kwargs: calls.append(kwargs))

    for task_run_id, run in enumerate((first_run, second_run), start=100):
        outcome = SectorExperimentExecutor(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
            input_source=source,
            unit_of_work=UnitOfWork(session),
            observer=Observer(),
            cancellation_probe=CancellationProbe(),
            release_commit="c" * 40,
        ).execute(run_key=run.run_key, task_run_id=task_run_id)
        assert outcome.status == "success"

    assert source.read_count == 2
    assert len(calls) == 8


@pytest.mark.parametrize(
    ("cancel_values", "expected_calls", "expected_completed"),
    [([True], 0, 0), ([False, True], 1, 1)],
)
def test_executor_cancels_only_at_parameter_set_boundaries_without_half_results(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    cancel_values: list[bool],
    expected_calls: int,
    expected_completed: int,
) -> None:
    run, frozen = _queued_run(session, request_key=f"run-cancel-{expected_calls}")
    source = StubSource(_snapshot(content_hash=str(frozen.revision.content.budget["input_scope"]["source_content_hash"])))
    calls: list[object] = []
    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", lambda **kwargs: calls.append(kwargs))

    outcome = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(cancel_values),
        release_commit="d" * 40,
    ).execute(run_key=run.run_key, task_run_id=110 + expected_calls)

    persisted = SqlAlchemyRuntimeRepository(session).get_run_by_key(run.run_key)
    assert outcome.status == "canceled"
    assert persisted.status is ExperimentRunStatus.CANCELED
    assert len(calls) == expected_calls
    assert persisted.completed_parameter_set_count == expected_completed


def test_execution_budget_growth_blocks_before_formula_execution(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, frozen = _queued_run(session, request_key="run-budget-growth")
    approved_hash = str(frozen.revision.content.budget["input_scope"]["source_content_hash"])
    snapshot = _snapshot(content_hash=approved_hash)
    oversized_evidence = tuple(
        replace(item, row_count=item.row_count + 1_000_000)
        for item in snapshot.dataset_evidence
    )
    source = StubSource(replace(snapshot, dataset_evidence=oversized_evidence))
    calls: list[object] = []
    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", lambda **kwargs: calls.append(kwargs))

    outcome = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(),
        release_commit="e" * 40,
    ).execute(run_key=run.run_key, task_run_id=120)

    assert outcome.status_reason_code == "QTF_PLAN_BUDGET_EXCEEDED"
    assert calls == []


def test_formula_failure_never_creates_a_successful_qtf_state(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, frozen = _queued_run(session, request_key="run-formula-failure")
    source = StubSource(_snapshot(content_hash=str(frozen.revision.content.budget["input_scope"]["source_content_hash"])))

    def _fail_formula(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("formula failed")

    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", _fail_formula)
    outcome = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(),
        release_commit="f" * 40,
    ).execute(run_key=run.run_key, task_run_id=130)

    persisted = SqlAlchemyRuntimeRepository(session).get_run_by_key(run.run_key)
    assert outcome.status == "failed"
    assert persisted.status is ExperimentRunStatus.FAILED
    assert persisted.validation_status is ValidationStatus.PENDING
    assert persisted.completed_parameter_set_count == 0
    assert persisted.result_hash is None


def test_invalid_release_commit_and_changed_source_block_before_formula_execution(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, frozen = _queued_run(session, request_key="run-invalid-commit")
    source = StubSource(_snapshot())
    calls: list[object] = []
    monkeypatch.setattr("qtf.modules.sector.executor.compute_sector_heat", lambda **kwargs: calls.append(kwargs))

    invalid = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(),
        release_commit="not-a-commit",
    ).execute(run_key=run.run_key, task_run_id=99)
    assert invalid.status == "failed"
    assert source.read_count == 0
    assert calls == []

    changed_run, _ = _queued_run(session, request_key="run-changed-source", frozen=frozen)
    changed_source = StubSource(_snapshot(content_hash="f" * 64))
    blocked = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=changed_source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(),
        release_commit="b" * 40,
    ).execute(run_key=changed_run.run_key, task_run_id=100)
    assert blocked.status == "failed"
    assert blocked.status_reason_code == "QTF_INPUT_CHANGED_DURING_RUN"
    assert changed_source.read_count == 1
    assert calls == []

    contract_run, _ = _queued_run(session, request_key="run-changed-contract", frozen=frozen)
    changed_contract_source = StubSource(
        replace(
            _snapshot(content_hash=str(frozen.revision.content.budget["input_scope"]["source_content_hash"])),
            source_contract_hash="0" * 64,
        )
    )
    contract_blocked = SectorExperimentExecutor(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=changed_contract_source,
        unit_of_work=UnitOfWork(session),
        observer=Observer(),
        cancellation_probe=CancellationProbe(),
        release_commit="b" * 40,
    ).execute(run_key=contract_run.run_key, task_run_id=101)
    assert contract_blocked.status_reason_code == "QTF_INPUT_CHANGED_DURING_RUN"
    assert calls == []


def _create_complete_draft(session: Session):  # type: ignore[no-untyped-def]
    content = _draft_content()
    bundle = ResearchService(
        SqlAlchemyResearchRepository(session),
        key_factory=lambda kind: f"{kind}-{session.scalar(select(func.count()).select_from(Research)) or 0}",
    ).create_research(
        CreateResearchCommand(
            request_key=f"research-request-{session.scalar(select(func.count()).select_from(Research)) or 0}",
            title="二级行业转热",
            template_key="sector_l2_turn_hot_v1",
            capability_key="sector_heat_research",
            created_by_user_id=7,
            initial_revision=content,
        )
    )
    session.commit()
    return bundle


def _preview_pass(session: Session):  # type: ignore[no-untyped-def]
    bundle = _create_complete_draft(session)
    source = StubSource(_snapshot())
    preflight = InputPreflightService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        input_source=source,
        key_factory=lambda: f"preflight-{bundle.revision.id}",
    ).preview(
        research_key=bundle.research.research_key,
        request_key=f"preflight-request-{bundle.revision.id}",
        draft_version=1,
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 4),
    )
    session.commit()
    return bundle, preflight


def _freeze(session: Session):  # type: ignore[no-untyped-def]
    bundle, preflight = _preview_pass(session)
    assert preflight.plan is not None
    frozen = PlanFreezeService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
    ).freeze(
        research_key=bundle.research.research_key,
        draft_version=1,
        preflight_key=preflight.preflight_key,
        approved_plan_hash=preflight.plan.plan_hash,
        acknowledged_exclusions=True,
        frozen_by_user_id=7,
    )
    session.commit()
    return frozen


def _queued_run(session: Session, *, request_key: str, frozen=None):  # type: ignore[no-untyped-def]
    frozen = frozen or _freeze(session)
    service = ExperimentService(
        research_repository=SqlAlchemyResearchRepository(session),
        runtime_repository=SqlAlchemyRuntimeRepository(session),
        task_run_stager=StubStager(session),
        key_factory=lambda: f"run-{request_key}",
    )
    run = service.create_run(
        revision_key=frozen.revision.revision_key,
        request_key=request_key,
        revision_hash=frozen.revision.revision_hash or "",
        requested_by_user_id=7,
    )
    session.commit()
    return run, frozen


def _draft_content(*, minimum_group_size: int = 2) -> RevisionContent:
    values = {
        "baseline_days": [60, 120],
        "trend_days": [5, 10],
        "amount_lookback_days": 20,
        "ewma_lambda": 0.3,
        "price_weight": 0.5,
        "amount_weight": 0.5,
        "z_clip": 3.0,
        "signal_threshold": 70.0,
        "reset_threshold": 60.0,
        "up_move_share_min": 0.6,
        "future_horizons": [1, 3, 5],
        "comparison_scope": "SIBLINGS",
        "minimum_group_size": minimum_group_size,
        "ranking_rule": {"kind": "PERCENTILE_GTE", "threshold": 80.0},
        "event_cluster_rule": "RESET_ONLY",
    }
    return RevisionContent(
        problem_statement="寻找未来继续热的二级行业",
        success_definition={"selected_keys": ["FUTURE_SIBLING_RANK_CONTINUATION"], "future_horizons": [1, 3, 5]},
        non_goals=["PER_SECTOR_TUNING", "PRODUCTION_RELEASE"],
        source_contract=SECTOR_L2_SOURCE_CONTRACT,
        universe_spec={"classification": "EASTMONEY", "industry_level": 2, "published_only": True},
        comparison_spec={"scope": "SIBLINGS", "parent_level": 1},
        formula_key="sector_heat_research_v1",
        formula_version="1",
        parameter_schema_key="sector_l2_heat_params_v1",
        parameter_schema_version="1",
        effective_params={
            "values": values,
            "sources": {key: "CANDIDATE" if key in {"baseline_days", "trend_days"} else "FIXED" for key in values},
        },
        validation_spec={},
        budget={},
    )


def _snapshot(
    *,
    missing: tuple[date, str] | None = None,
    duplicate: bool = False,
    content_hash: str | None = None,
    hierarchy: tuple[SectorHierarchyNode, ...] | None = None,
    trade_dates: tuple[date, ...] | None = None,
    include_observation_date: date | None = None,
    invalid_amount: bool = False,
) -> SectorInputSnapshot:
    now = datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc)
    trade_dates = trade_dates or (date(2026, 8, 3), date(2026, 8, 4))
    hierarchy = hierarchy or (
        SectorHierarchyNode("P", "父行业", 1, None, "P", 1, "v1", now),
        SectorHierarchyNode("A", "子行业A", 2, "P", "P", 1, "v1", now),
        SectorHierarchyNode("B", "子行业B", 2, "P", "P", 2, "v1", now),
    )
    observation_dates = tuple(dict.fromkeys((*trade_dates, *((include_observation_date,) if include_observation_date else ()))))
    observations = [
        SectorObservation(day, sector, "", float(index), -1.0 if invalid_amount and index == 1 else 100.0 + index)
        for index, (day, sector) in enumerate(
            ((day, sector) for day in observation_dates for sector in ("A", "B")),
            start=1,
        )
        if (day, sector) != missing
    ]
    if duplicate:
        observations.append(observations[0])
    evidence = tuple(
        DatasetEvidence(key, ("field",), trade_dates[0], trade_dates[-1], count, "PASS", 0, 0, canonical_json_hash({"key": key, "count": count}))
        for key, count in (
            ("core_serving.trade_calendar", len(trade_dates)),
            ("core_serving.wealth_sector_hierarchy", len(hierarchy)),
            ("core_serving.dc_daily", len(observations)),
        )
    )
    source_hash = canonical_json_hash(SECTOR_L2_SOURCE_CONTRACT)
    return SectorInputSnapshot(
        as_of=now,
        trade_dates=trade_dates,
        hierarchy=hierarchy,
        observations=tuple(observations),
        dataset_evidence=evidence,
        content_hash=content_hash or canonical_json_hash({"source": source_hash, "observations": len(observations)}),
        source_contract_hash=source_hash,
    )
