from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ActionParameterResponse(BaseModel):
    key: str
    display_name: str
    param_type: str
    description: str
    required: bool
    options: list[str]
    multi_value: bool
    default_value: Any | None = None


class ActionCatalogItem(BaseModel):
    key: str
    action_type: str
    display_name: str
    target_key: str
    target_display_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    domain_key: str
    domain_display_name: str
    date_selection_rule: str | None = None
    description: str
    target_tables: list[str]
    manual_enabled: bool
    schedule_enabled: bool
    retry_enabled: bool
    schedule_binding_count: int = 0
    active_schedule_count: int = 0
    parameters: list[ActionParameterResponse]


class WorkflowStepCatalogItem(BaseModel):
    step_key: str
    action_key: str
    display_name: str
    dataset_key: str | None = None
    depends_on: list[str]
    default_params: dict


class WorkflowCatalogItem(BaseModel):
    key: str
    display_name: str
    description: str
    group_key: str
    group_label: str
    group_order: int
    domain_key: str
    domain_display_name: str
    parallel_policy: str
    default_schedule_policy: str | None = None
    schedule_enabled: bool
    manual_enabled: bool
    schedule_binding_count: int = 0
    active_schedule_count: int = 0
    parameters: list[ActionParameterResponse]
    steps: list[WorkflowStepCatalogItem]


class SourceCatalogItem(BaseModel):
    source_key: str
    display_name: str


class OpsCatalogResponse(BaseModel):
    actions: list[ActionCatalogItem]
    workflows: list[WorkflowCatalogItem]
    sources: list[SourceCatalogItem]
