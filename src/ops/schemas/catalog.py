from __future__ import annotations

from pydantic import BaseModel


class ParameterSpecResponse(BaseModel):
    key: str
    display_name: str
    param_type: str
    description: str
    required: bool
    options: list[str]
    multi_value: bool


class JobSpecCatalogItem(BaseModel):
    key: str
    spec_type: str = "job"
    display_name: str
    resource_key: str | None = None
    resource_display_name: str | None = None
    category: str
    description: str
    strategy_type: str
    executor_kind: str
    target_tables: list[str]
    supports_manual_run: bool
    supports_schedule: bool
    supports_retry: bool
    schedule_binding_count: int = 0
    active_schedule_count: int = 0
    supported_params: list[ParameterSpecResponse]


class WorkflowStepResponse(BaseModel):
    step_key: str
    job_key: str
    display_name: str
    depends_on: list[str]
    default_params: dict


class WorkflowSpecCatalogItem(BaseModel):
    key: str
    display_name: str
    description: str
    parallel_policy: str
    default_schedule_policy: str | None = None
    supports_schedule: bool
    supports_manual_run: bool
    schedule_binding_count: int = 0
    active_schedule_count: int = 0
    supported_params: list[ParameterSpecResponse]
    steps: list[WorkflowStepResponse]


class OpsCatalogResponse(BaseModel):
    job_specs: list[JobSpecCatalogItem]
    workflow_specs: list[WorkflowSpecCatalogItem]
