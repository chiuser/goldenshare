from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qtf.adapters.persistence.models.research import ExperimentRevision, Research
from qtf.contracts.errors import QtfDraftConflict, QtfStateConflict
from qtf.contracts.research import (
    ExperimentRevisionRecord,
    ExperimentRevisionStatus,
    ResearchBundle,
    ResearchRecord,
    ResearchStatus,
    RevisionContent,
)


class SqlAlchemyResearchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_bundle_by_create_request_key(self, request_key: str) -> ResearchBundle | None:
        research = self._session.scalar(
            select(Research).where(Research.create_request_key == request_key)
        )
        if research is None:
            return None
        revision = self._session.scalar(
            select(ExperimentRevision).where(
                ExperimentRevision.research_id == research.id,
                ExperimentRevision.revision_no == 1,
            )
        )
        if revision is None:
            raise QtfStateConflict("research exists without its initial revision")
        return _bundle_record(research, revision)

    def create_research_with_initial_revision(
        self,
        *,
        research_key: str,
        revision_key: str,
        request_key: str,
        title: str,
        template_key: str,
        capability_key: str,
        created_by_user_id: int,
        content: RevisionContent,
    ) -> tuple[ResearchBundle, bool]:
        try:
            with self._session.begin_nested():
                research = Research(
                    research_key=research_key,
                    create_request_key=request_key,
                    title=title,
                    template_key=template_key,
                    capability_key=capability_key,
                    status=ResearchStatus.DRAFT.value,
                    latest_revision_no=1,
                    created_by_user_id=created_by_user_id,
                )
                self._session.add(research)
                self._session.flush()
                revision = _new_revision(
                    revision_key=revision_key,
                    request_key=request_key,
                    research_id=research.id,
                    content=content,
                )
                self._session.add(revision)
                self._session.flush()
            return _bundle_record(research, revision), True
        except IntegrityError:
            existing = self.find_bundle_by_create_request_key(request_key)
            if existing is None:
                raise
            return existing, False

    def update_draft(
        self,
        *,
        revision_key: str,
        expected_draft_version: int,
        content: RevisionContent,
    ) -> ResearchBundle:
        revision = self._session.scalar(
            select(ExperimentRevision).where(ExperimentRevision.revision_key == revision_key)
        )
        if revision is None:
            raise QtfStateConflict("revision does not exist")
        if revision.status != ExperimentRevisionStatus.DRAFT.value:
            raise QtfStateConflict("only DRAFT revisions can be edited")
        if revision.draft_version != expected_draft_version:
            raise QtfDraftConflict("draft version changed; reload before saving")

        _apply_content(revision, content)
        revision.draft_version += 1
        revision.revision_hash = None
        self._session.flush()

        research = self._session.get(Research, revision.research_id)
        if research is None:
            raise QtfStateConflict("revision exists without its research")
        return _bundle_record(research, revision)


def _new_revision(
    *,
    revision_key: str,
    request_key: str,
    research_id: int,
    content: RevisionContent,
) -> ExperimentRevision:
    revision = ExperimentRevision(
        revision_key=revision_key,
        request_key=request_key,
        research_id=research_id,
        revision_no=1,
        parent_revision_id=None,
        status=ExperimentRevisionStatus.DRAFT.value,
        draft_version=1,
        revision_hash=None,
        frozen_by_user_id=None,
        frozen_at=None,
    )
    _apply_content(revision, content)
    return revision


def _apply_content(revision: ExperimentRevision, content: RevisionContent) -> None:
    revision.problem_statement = content.problem_statement
    revision.success_definition_json = deepcopy(content.success_definition)
    revision.non_goals_json = deepcopy(content.non_goals)
    revision.source_contract_json = deepcopy(content.source_contract)
    revision.universe_spec_json = deepcopy(content.universe_spec)
    revision.comparison_spec_json = deepcopy(content.comparison_spec)
    revision.formula_key = content.formula_key
    revision.formula_version = content.formula_version
    revision.parameter_schema_key = content.parameter_schema_key
    revision.parameter_schema_version = content.parameter_schema_version
    revision.effective_params_json = deepcopy(content.effective_params)
    revision.validation_spec_json = deepcopy(content.validation_spec)
    revision.budget_json = deepcopy(content.budget)


def _bundle_record(research: Research, revision: ExperimentRevision) -> ResearchBundle:
    return ResearchBundle(
        research=ResearchRecord(
            id=research.id,
            research_key=research.research_key,
            create_request_key=research.create_request_key,
            title=research.title,
            template_key=research.template_key,
            capability_key=research.capability_key,
            status=ResearchStatus(research.status),
            latest_revision_no=research.latest_revision_no,
            created_by_user_id=research.created_by_user_id,
            created_at=research.created_at,
            updated_at=research.updated_at,
        ),
        revision=ExperimentRevisionRecord(
            id=revision.id,
            revision_key=revision.revision_key,
            request_key=revision.request_key,
            research_id=revision.research_id,
            revision_no=revision.revision_no,
            parent_revision_id=revision.parent_revision_id,
            status=ExperimentRevisionStatus(revision.status),
            content=RevisionContent(
                problem_statement=revision.problem_statement,
                success_definition=deepcopy(revision.success_definition_json),
                non_goals=deepcopy(revision.non_goals_json),
                source_contract=deepcopy(revision.source_contract_json),
                universe_spec=deepcopy(revision.universe_spec_json),
                comparison_spec=deepcopy(revision.comparison_spec_json),
                formula_key=revision.formula_key,
                formula_version=revision.formula_version,
                parameter_schema_key=revision.parameter_schema_key,
                parameter_schema_version=revision.parameter_schema_version,
                effective_params=deepcopy(revision.effective_params_json),
                validation_spec=deepcopy(revision.validation_spec_json),
                budget=deepcopy(revision.budget_json),
            ),
            draft_version=revision.draft_version,
            revision_hash=revision.revision_hash,
            frozen_by_user_id=revision.frozen_by_user_id,
            frozen_at=revision.frozen_at,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
        ),
    )
