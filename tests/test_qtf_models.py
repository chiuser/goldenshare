from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qtf.adapters.persistence.models.research import ExperimentRevision, Research
from qtf.adapters.persistence.models.runtime import ExperimentRun, InputPreflight, InputPreflightIssue
from qtf.adapters.persistence.models.validation import (
    RunConclusion,
    RunGateResult,
    RunParameterResult,
    SectorSignalEvent,
)
from qtf.adapters.persistence.repositories.research_repository import SqlAlchemyResearchRepository
from qtf.application.services.research_service import ResearchService
from qtf.contracts.errors import QtfDraftConflict, QtfRequestConflict, QtfStateConflict
from qtf.contracts.research import CreateResearchCommand, ExperimentRevisionStatus, RevisionContent
from qtf.engine.canonical_hash import revision_content_hash
from src.app.model_registry import MODEL_MODULES, register_all_models
from src.foundation.models.base import Base


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260822_000143_add_qtf_research_state.py"
M3_MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260823_000144_add_qtf_run_preflight_state.py"
M4_MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260824_000149_add_qtf_validation_evidence.py"


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach_qtf(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("ATTACH DATABASE ':memory:' AS qtf")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[Research.__table__, ExperimentRevision.__table__],
    )
    with Session(engine) as active_session:
        yield active_session


def test_app_registry_registers_m1_m3_and_m4_qtf_models() -> None:
    register_all_models()
    assert MODEL_MODULES[0] == "qtf.adapters.persistence.models.research"
    qtf_tables = {table.name for table in Base.metadata.tables.values() if table.schema == "qtf"}
    assert qtf_tables == {
        "research",
        "experiment_revision",
        "input_preflight",
        "input_preflight_issue",
        "experiment_run",
        "run_gate_result",
        "run_parameter_result",
        "sector_signal_event",
        "run_conclusion",
    }


def test_research_creation_is_idempotent_and_conflicting_replay_is_rejected(session: Session) -> None:
    service = _service(session)
    command = _command()

    created = service.create_research(command)
    session.commit()
    replayed = service.create_research(command)

    assert replayed.research.id == created.research.id
    assert replayed.revision.id == created.revision.id
    assert session.scalar(select(Research).where(Research.create_request_key == command.request_key)) is not None
    assert len(list(session.scalars(select(Research)))) == 1
    assert len(list(session.scalars(select(ExperimentRevision)))) == 1

    conflicting = CreateResearchCommand(
        request_key=command.request_key,
        title="different title",
        template_key=command.template_key,
        capability_key=command.capability_key,
        created_by_user_id=command.created_by_user_id,
        initial_revision=command.initial_revision,
    )
    with pytest.raises(QtfRequestConflict):
        service.create_research(conflicting)


def test_only_current_draft_version_can_be_updated(session: Session) -> None:
    service = _service(session)
    created = service.create_research(_command())
    session.commit()
    changed = _content(problem_statement="updated research question")

    saved = service.save_draft(
        revision_key=created.revision.revision_key,
        expected_draft_version=1,
        content=changed,
    )
    session.commit()

    assert saved.revision.draft_version == 2
    assert saved.revision.content == changed
    with pytest.raises(QtfDraftConflict):
        service.save_draft(
            revision_key=created.revision.revision_key,
            expected_draft_version=1,
            content=_content(problem_statement="stale overwrite"),
        )


def test_frozen_revision_rejects_content_and_status_mutation(session: Session) -> None:
    created = _service(session).create_research(_command())
    revision = session.scalar(
        select(ExperimentRevision).where(ExperimentRevision.revision_key == created.revision.revision_key)
    )
    assert revision is not None
    revision.status = ExperimentRevisionStatus.FROZEN.value
    revision.revision_hash = revision_content_hash(created.revision.content)
    revision.frozen_by_user_id = 7
    revision.frozen_at = datetime.now(timezone.utc)
    session.commit()

    revision.problem_statement = "must not change"
    with pytest.raises(QtfStateConflict, match="immutable"):
        session.flush()
    session.rollback()

    persisted = session.scalar(
        select(ExperimentRevision).where(ExperimentRevision.revision_key == created.revision.revision_key)
    )
    assert persisted is not None
    persisted.status = ExperimentRevisionStatus.DRAFT.value
    with pytest.raises(QtfStateConflict, match="immutable"):
        session.flush()


def test_retired_revision_is_not_editable(session: Session) -> None:
    service = _service(session)
    created = service.create_research(_command())
    revision = session.get(ExperimentRevision, created.revision.id)
    assert revision is not None
    revision.status = ExperimentRevisionStatus.RETIRED.value
    session.commit()

    with pytest.raises(QtfStateConflict, match="only DRAFT"):
        service.save_draft(
            revision_key=created.revision.revision_key,
            expected_draft_version=1,
            content=_content(problem_statement="must not revive"),
        )


def test_database_constraints_reject_invalid_status_and_duplicate_revision_request(session: Session) -> None:
    created = _service(session).create_research(_command())
    session.commit()
    research = session.get(Research, created.research.id)
    assert research is not None
    research.status = "INVALID"
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    original = session.get(ExperimentRevision, created.revision.id)
    assert original is not None
    duplicate = ExperimentRevision(
        revision_key="revision-duplicate",
        request_key=original.request_key,
        research_id=original.research_id,
        revision_no=2,
        parent_revision_id=None,
        status=ExperimentRevisionStatus.DRAFT.value,
        problem_statement=original.problem_statement,
        success_definition_json=original.success_definition_json,
        non_goals_json=original.non_goals_json,
        source_contract_json=original.source_contract_json,
        universe_spec_json=original.universe_spec_json,
        comparison_spec_json=original.comparison_spec_json,
        formula_key=original.formula_key,
        formula_version=original.formula_version,
        parameter_schema_key=original.parameter_schema_key,
        parameter_schema_version=original.parameter_schema_version,
        effective_params_json=original.effective_params_json,
        validation_spec_json=original.validation_spec_json,
        budget_json=original.budget_json,
        draft_version=1,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()


def test_m1_migration_contains_only_research_state_and_m3_follows_it() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("20260822_000143") is not None
    m3_revision = script.get_revision("20260823_000144")
    assert m3_revision is not None
    assert m3_revision.down_revision == "20260822_000143"

    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'down_revision = "20260822_000142"' in migration
    assert 'op.create_table(\n        "research"' in migration
    assert 'op.create_table(\n        "experiment_revision"' in migration
    for forbidden_table in ("input_preflight", "experiment_run", "run_gate_result", "candidate", "release"):
        assert f'op.create_table(\n        "{forbidden_table}"' not in migration


def test_m3_models_keep_task_run_as_a_logical_reference() -> None:
    for model in (InputPreflight, InputPreflightIssue, ExperimentRun):
        assert not inspect(model).relationships
    assert not ExperimentRun.__table__.c.task_run_id.foreign_keys
    assert {foreign_key.target_fullname for foreign_key in ExperimentRun.__table__.foreign_keys} == {
        "qtf.experiment_revision.id",
        "qtf.input_preflight.id",
    }


def test_m3_migration_contains_only_preflight_and_run_state() -> None:
    migration = M3_MIGRATION_PATH.read_text(encoding="utf-8")
    for table in ("input_preflight", "input_preflight_issue", "experiment_run"):
        assert f'op.create_table(\n        "{table}"' in migration
    for forbidden in ("run_gate_result", "run_parameter_result", "sector_signal_event", "candidate", "release"):
        assert f'op.create_table(\n        "{forbidden}"' not in migration
    assert "ops.task_run" not in migration
    assert 'down_revision = "20260822_000143"' in migration


def test_m4_migration_follows_real_head_and_contains_only_validation_evidence() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "20260824_000149"
    revision = script.get_revision("20260824_000149")
    assert revision is not None
    assert revision.down_revision == "20260824_000148"

    migration = M4_MIGRATION_PATH.read_text(encoding="utf-8")
    for table in (
        "run_gate_result",
        "run_parameter_result",
        "sector_signal_event",
        "run_conclusion",
    ):
        assert f'op.create_table(\n        "{table}"' in migration
    for forbidden in ("candidate", "candidate_action", "release"):
        assert f'op.create_table(\n        "{forbidden}"' not in migration


def test_m4_models_have_only_qtf_run_foreign_keys_and_no_orm_relationships() -> None:
    for model in (RunGateResult, RunParameterResult, SectorSignalEvent, RunConclusion):
        assert not inspect(model).relationships
        assert {key.target_fullname for key in model.__table__.foreign_keys} == {
            "qtf.experiment_run.id"
        }


def test_m4_model_constraints_accept_evidence_and_reject_nomination() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach_qtf(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("ATTACH DATABASE ':memory:' AS qtf")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            Research.__table__,
            ExperimentRevision.__table__,
            InputPreflight.__table__,
            ExperimentRun.__table__,
            RunGateResult.__table__,
            RunParameterResult.__table__,
            SectorSignalEvent.__table__,
            RunConclusion.__table__,
        ],
    )
    with Session(engine) as active:
        bundle = _service(active).create_research(_command())
        active.flush()
        run = ExperimentRun(
            run_key="run-m4-model",
            request_key="run-m4-model-request",
            revision_id=bundle.revision.id,
            status="COMPLETED",
            validation_status="VALID",
            runtime_fingerprint_json={},
            formula_version="1",
            completed_parameter_set_count=1,
        )
        active.add(run)
        active.flush()
        now = datetime.now(timezone.utc)
        active.add_all(
            [
                RunGateResult(
                    run_id=run.id,
                    gate_key="INPUT",
                    status="PASS",
                    summary="输入合同一致",
                    evidence_json={"validation_contract_version": 1},
                    checked_at=now,
                ),
                RunParameterResult(
                    result_key="result-m4-model",
                    run_id=run.id,
                    parameter_set_key="parameter-set-1",
                    parameter_values_json={"baseline_days": 60},
                    entry_metrics_json={"1": {"success_rate": 0.5}},
                    retention_metrics_json={"1": {"success_rate": 0.6}},
                    baseline_metrics_json={},
                    lift_metrics_json={},
                    coverage_metrics_json={},
                    sample_metrics_json={},
                    confidence_intervals_json={},
                    metrics_json={},
                    effect_status="SUPPORTED",
                    result_hash="a" * 64,
                ),
                SectorSignalEvent(
                    run_id=run.id,
                    parameter_set_key="parameter-set-1",
                    signal_trade_date=date(2026, 8, 1),
                    sector_code="BK0001",
                    parent_sector_code="BK0000",
                    sector_level=2,
                    entry_type="ENTRY",
                    signal_state_json={"heat_state": 72.0},
                    signal_rank_pct=Decimal("88.000000"),
                    future_outcomes_json={"1": "SUCCESS", "3": "UNEVALUABLE"},
                    input_completeness_json={"complete": True},
                    event_hash="b" * 64,
                ),
                RunConclusion(
                    run_id=run.id,
                    request_key="conclusion-m4-model",
                    conclusion="OBSERVED",
                    actor_user_id=7,
                    comment="继续观察",
                    concluded_at=now,
                ),
            ]
        )
        active.commit()

        conclusion = active.scalar(select(RunConclusion).where(RunConclusion.run_id == run.id))
        assert conclusion is not None and conclusion.conclusion == "OBSERVED"

        active.add(
            RunGateResult(
                run_id=run.id,
                gate_key="INPUT",
                status="PASS",
                summary="重复门禁",
                evidence_json={},
                checked_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            active.commit()
        active.rollback()

        active.add(
            RunParameterResult(
                result_key="result-m4-duplicate",
                run_id=run.id,
                parameter_set_key="parameter-set-1",
                parameter_values_json={},
                entry_metrics_json={},
                retention_metrics_json={},
                baseline_metrics_json={},
                lift_metrics_json={},
                coverage_metrics_json={},
                sample_metrics_json={},
                confidence_intervals_json={},
                metrics_json={},
                effect_status="SUPPORTED",
                result_hash="c" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            active.commit()
        active.rollback()

        active.add(
            SectorSignalEvent(
                run_id=run.id,
                parameter_set_key="parameter-set-1",
                signal_trade_date=date(2026, 8, 1),
                sector_code="BK0001",
                parent_sector_code="BK0000",
                sector_level=2,
                entry_type="ENTRY",
                signal_state_json={},
                signal_rank_pct=Decimal("50.000000"),
                future_outcomes_json={},
                input_completeness_json={},
                event_hash="d" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            active.commit()
        active.rollback()

        conclusion = active.scalar(select(RunConclusion).where(RunConclusion.run_id == run.id))
        assert conclusion is not None
        conclusion.conclusion = "NOMINATED"
        with pytest.raises(IntegrityError):
            active.commit()


def test_qtf_models_do_not_create_user_or_ops_orm_relationships() -> None:
    research_mapper = inspect(Research)
    revision_mapper = inspect(ExperimentRevision)
    assert not research_mapper.relationships
    assert not revision_mapper.relationships
    assert not Research.__table__.c.created_by_user_id.foreign_keys
    assert not ExperimentRevision.__table__.c.frozen_by_user_id.foreign_keys
    assert {foreign_key.target_fullname for foreign_key in ExperimentRevision.__table__.foreign_keys} == {
        "qtf.experiment_revision.id",
        "qtf.research.id",
    }


def _service(session: Session) -> ResearchService:
    return ResearchService(
        SqlAlchemyResearchRepository(session),
        key_factory=lambda kind: f"{kind}-key",
    )


def _command() -> CreateResearchCommand:
    return CreateResearchCommand(
        request_key="create-request-1",
        title="L2 sector warming research",
        template_key="sector_l2_turn_hot_v1",
        capability_key="sector_heat_research",
        created_by_user_id=7,
        initial_revision=_content(),
    )


def _content(*, problem_statement: str = "find warming L2 sectors") -> RevisionContent:
    return RevisionContent(
        problem_statement=problem_statement,
        success_definition={"future_horizons": [1, 3, 5]},
        non_goals=["per-sector tuning", "production release"],
        source_contract={"source_kind": "prod"},
        universe_spec={"classification": "DC", "level": 2},
        comparison_spec={"scope": "siblings"},
        formula_key="sector_heat_research_v1",
        formula_version="1.0.0",
        parameter_schema_key="sector_l2_heat_params_v1",
        parameter_schema_version="1.0.0",
        effective_params={"trend_days": [5, 10], "baseline_days": [60, 120]},
        validation_spec={"sample_split": "ordered"},
        budget={"max_parameter_sets": 8},
    )
