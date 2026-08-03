from __future__ import annotations

from typing import Any, Literal

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


class TriggerModeCapabilityResponse(BaseModel):
    mode: Literal["schedule", "probe", "schedule_probe_fallback"]
    allowed_schedule_types: list[Literal["cron", "once"]]


class FilterCapabilityResponse(BaseModel):
    mode: Literal["dataset_default", "forbidden", "required_allowed_values"]
    required_fields: list[str]
    allowed_values: dict[str, list[str]]
    require_complete_allowed_values: bool


class ProbeWindowCapabilityResponse(BaseModel):
    mode: Literal["operator_default", "fixed"]
    start: str | None
    end: str | None


class ProbeIntegerCapabilityResponse(BaseModel):
    mode: Literal["operator_default", "minimum", "fixed"]
    value: int | None


class ProbeConfigCapabilityResponse(BaseModel):
    source: Literal["system_default"]
    source_label: str
    window: ProbeWindowCapabilityResponse
    probe_interval_seconds: ProbeIntegerCapabilityResponse
    max_triggers_per_day: ProbeIntegerCapabilityResponse


class ProbeConditionCapabilityResponse(BaseModel):
    kind: str
    label: str
    description: str
    allowed_trigger_modes: list[Literal["probe", "schedule_probe_fallback"]]
    calendar_policy: Literal["dataset_default", "forbidden"]
    time_input: Literal["dataset_default", "forbidden"]
    filters: FilterCapabilityResponse
    probe: ProbeConfigCapabilityResponse


class AutomationCapabilityResponse(BaseModel):
    version: Literal[1]
    default_trigger_mode: Literal["schedule", "probe", "schedule_probe_fallback"]
    trigger_options: list[TriggerModeCapabilityResponse]
    probe_conditions: list[ProbeConditionCapabilityResponse]


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
    freshness_policy: str | None = None
    date_selection_rule: str | None = None
    description: str
    target_tables: list[str]
    manual_enabled: bool
    schedule_enabled: bool
    automation_capability: AutomationCapabilityResponse | None
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
    automation_capability: AutomationCapabilityResponse | None
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
