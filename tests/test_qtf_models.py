from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qtf.adapters.persistence.models.research import ExperimentRevision, Research
from qtf.adapters.persistence.repositories.research_repository import SqlAlchemyResearchRepository
from qtf.application.services.research_service import ResearchService
from qtf.contracts.errors import QtfDraftConflict, QtfRequestConflict, QtfStateConflict
from qtf.contracts.research import CreateResearchCommand, ExperimentRevisionStatus, RevisionContent
from qtf.engine.canonical_hash import revision_content_hash
from src.app.model_registry import MODEL_MODULES, register_all_models
from src.foundation.models.base import Base


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260822_000143_add_qtf_research_state.py"


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


def test_app_registry_registers_only_the_two_m1_qtf_models() -> None:
    register_all_models()
    assert MODEL_MODULES[0] == "qtf.adapters.persistence.models.research"
    qtf_tables = {table.name for table in Base.metadata.tables.values() if table.schema == "qtf"}
    assert qtf_tables == {"research", "experiment_revision"}


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


def test_m1_migration_is_single_head_and_contains_only_research_state() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260822_000143"]

    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'down_revision = "20260822_000142"' in migration
    assert 'op.create_table(\n        "research"' in migration
    assert 'op.create_table(\n        "experiment_revision"' in migration
    for forbidden_table in ("input_preflight", "experiment_run", "run_gate_result", "candidate", "release"):
        assert f'op.create_table(\n        "{forbidden_table}"' not in migration


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
