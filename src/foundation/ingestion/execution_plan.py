from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class DatasetTimeInput:
    mode: str
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    month: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    date_field: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetActionRequest:
    dataset_key: str
    action: str
    time_input: DatasetTimeInput
    filters: dict[str, Any] = field(default_factory=dict)
    trigger_source: str = "manual"
    requested_by_user_id: int | None = None
    schedule_id: int | None = None
    workflow_key: str | None = None
    run_id: int | None = None


@dataclass(frozen=True, slots=True)
class ValidatedDatasetActionRequest:
    request_id: str
    dataset_key: str
    action: str
    run_profile: str
    trigger_source: str
    params: dict[str, Any] = field(default_factory=dict)
    source_key: str | None = None
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    run_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionTimeScope:
    mode: str
    start: date | str | None = None
    end: date | str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class PlanSource:
    source_key: str
    adapter_key: str
    api_name: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanPlanning:
    universe_policy: str
    enum_fanout_fields: tuple[str, ...]
    enum_fanout_defaults: dict[str, tuple[str, ...]]
    pagination_policy: str
    chunk_size: int | None
    max_units_per_execution: int | None
    unit_count: int


@dataclass(frozen=True, slots=True)
class PlanWriting:
    target_table: str
    raw_dao_name: str
    core_dao_name: str
    conflict_columns: tuple[str, ...] | None
    write_path: str


@dataclass(frozen=True, slots=True)
class PlanTransactionPolicy:
    commit_policy: str
    idempotent_write_required: bool
    write_volume_assessment: str


@dataclass(frozen=True, slots=True)
class PlanObservability:
    progress_label: str
    observed_field: str | None
    audit_applicable: bool


@dataclass(frozen=True, slots=True)
class PlanUnitSnapshot:
    unit_id: str
    dataset_key: str
    source_key: str
    trade_date: date | None
    request_params: dict[str, Any]
    progress_context: dict[str, Any]
    pagination_policy: str | None = None
    page_limit: int | None = None
    requested_source_key: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetExecutionPlan:
    plan_id: str
    dataset_key: str
    action: str
    run_profile: str
    time_scope: ExecutionTimeScope
    filters: dict[str, Any]
    source: PlanSource
    planning: PlanPlanning
    writing: PlanWriting
    transaction: PlanTransactionPolicy
    observability: PlanObservability
    units: tuple[PlanUnitSnapshot, ...]
