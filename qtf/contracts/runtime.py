from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class InputPreflightPhase(StrEnum):
    DRAFT_PREVIEW = "DRAFT_PREVIEW"
    RUN_PREFLIGHT = "RUN_PREFLIGHT"


class InputPreflightStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class InputSourceKind(StrEnum):
    PROD = "PROD"


class RemediationOwner(StrEnum):
    PROD = "PROD"
    LAKE = "LAKE"


class ExperimentRunStatus(StrEnum):
    PLANNED = "PLANNED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    BLOCKED = "BLOCKED"


class ValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DatasetEvidence:
    dataset_key: str
    fields: tuple[str, ...]
    start_date: date | None
    end_date: date | None
    row_count: int
    unique_key_status: str
    missing_count: int
    duplicate_count: int
    content_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_key": self.dataset_key,
            "fields": list(self.fields),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "row_count": self.row_count,
            "unique_key_status": self.unique_key_status,
            "missing_count": self.missing_count,
            "duplicate_count": self.duplicate_count,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class InputPreflightIssueRecord:
    code: str
    severity: str
    dataset_key: str
    message: str
    remediation_owner: RemediationOwner
    trade_date: date | None = None
    field_name: str | None = None
    object_key: str | None = None
    evidence: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    input_scope: dict[str, object]
    estimator_inputs: dict[str, int]
    parameter_matrix: tuple[dict[str, object], ...]
    fixed_parameters: dict[str, object]
    future_horizons: tuple[int, ...]
    comparison_scope: str
    sample_split: dict[str, object]
    primary_objective: str
    success_definition: dict[str, object]
    hard_gates: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    budget: dict[str, int]
    estimator_version: str
    plan_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "input_scope": dict(self.input_scope),
            "estimator_inputs": dict(self.estimator_inputs),
            "parameter_matrix": list(self.parameter_matrix),
            "fixed_parameters": dict(self.fixed_parameters),
            "future_horizons": list(self.future_horizons),
            "comparison_scope": self.comparison_scope,
            "sample_split": dict(self.sample_split),
            "primary_objective": self.primary_objective,
            "success_definition": dict(self.success_definition),
            "hard_gates": list(self.hard_gates),
            "stop_conditions": list(self.stop_conditions),
            "budget": dict(self.budget),
            "estimator_version": self.estimator_version,
            "plan_hash": self.plan_hash,
        }


@dataclass(frozen=True, slots=True)
class InputPreflightRecord:
    id: int
    preflight_key: str
    request_key: str
    revision_id: int
    draft_hash: str | None
    phase: InputPreflightPhase
    status: InputPreflightStatus
    source_kind: InputSourceKind
    source_contract_hash: str
    as_of: datetime
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date | None
    effective_end_date: date | None
    dataset_evidence: tuple[DatasetEvidence, ...]
    universe_count: int
    group_count: int
    valid_group_day_count: int
    excluded_group_day_count: int
    plan: ExecutionPlan | None
    content_hash: str
    completed_at: datetime
    issues: tuple[InputPreflightIssueRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentRunRecord:
    id: int
    run_key: str
    request_key: str
    revision_id: int
    input_preflight_id: int | None
    task_run_id: int | None
    status: ExperimentRunStatus
    validation_status: ValidationStatus
    code_commit: str | None
    runtime_fingerprint: dict[str, object]
    formula_version: str
    source_content_hash: str | None
    result_hash: str | None
    completed_parameter_set_count: int
    failure_code: str | None
    failure_message: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
