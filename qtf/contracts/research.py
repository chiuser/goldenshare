from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ResearchStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ExperimentRevisionStatus(StrEnum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class RevisionContent:
    problem_statement: str
    success_definition: dict[str, object]
    non_goals: list[object]
    source_contract: dict[str, object]
    universe_spec: dict[str, object]
    comparison_spec: dict[str, object]
    formula_key: str
    formula_version: str
    parameter_schema_key: str
    parameter_schema_version: str
    effective_params: dict[str, object]
    validation_spec: dict[str, object]
    budget: dict[str, object]

    def hash_payload(self) -> dict[str, object]:
        return {
            "problem_statement": self.problem_statement,
            "success_definition": self.success_definition,
            "non_goals": self.non_goals,
            "source_contract": self.source_contract,
            "universe_spec": self.universe_spec,
            "comparison_spec": self.comparison_spec,
            "formula_key": self.formula_key,
            "formula_version": self.formula_version,
            "parameter_schema_key": self.parameter_schema_key,
            "parameter_schema_version": self.parameter_schema_version,
            "effective_params": self.effective_params,
            "validation_spec": self.validation_spec,
            "budget": self.budget,
        }


@dataclass(frozen=True, slots=True)
class CreateResearchCommand:
    request_key: str
    title: str
    template_key: str
    capability_key: str
    created_by_user_id: int
    initial_revision: RevisionContent


@dataclass(frozen=True, slots=True)
class ResearchRecord:
    id: int
    research_key: str
    create_request_key: str
    title: str
    template_key: str
    capability_key: str
    status: ResearchStatus
    latest_revision_no: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExperimentRevisionRecord:
    id: int
    revision_key: str
    request_key: str
    research_id: int
    revision_no: int
    parent_revision_id: int | None
    status: ExperimentRevisionStatus
    content: RevisionContent
    draft_version: int
    revision_hash: str | None
    frozen_by_user_id: int | None
    frozen_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResearchBundle:
    research: ResearchRecord
    revision: ExperimentRevisionRecord
