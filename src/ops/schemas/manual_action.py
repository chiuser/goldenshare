from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.ops.schemas.catalog import ActionParameterResponse


class ManualActionDateModelResponse(BaseModel):
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None = None
    audit_applicable: bool
    not_applicable_reason: str | None = None


class ManualActionTimeFormResponse(BaseModel):
    control: str
    default_mode: str
    allowed_modes: list[str]
    selection_rule: str
    point_label: str
    range_label: str


class ManualActionItemResponse(BaseModel):
    action_key: str
    action_type: str
    display_name: str
    description: str
    resource_key: str | None = None
    resource_display_name: str | None = None
    date_model: ManualActionDateModelResponse | None = None
    time_form: ManualActionTimeFormResponse
    filters: list[ActionParameterResponse]
    search_keywords: list[str]
    action_order: int
    route_keys: list[str]


class ManualActionGroupResponse(BaseModel):
    group_key: str
    group_label: str
    group_order: int
    actions: list[ManualActionItemResponse]


class ManualActionListResponse(BaseModel):
    groups: list[ManualActionGroupResponse]


class ManualActionTimeInput(BaseModel):
    mode: str = "none"
    trade_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    month: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    ann_date: str | None = None
    date_field: str | None = None


class ManualActionTaskRunCreateRequest(BaseModel):
    time_input: ManualActionTimeInput = Field(default_factory=ManualActionTimeInput)
    filters: dict[str, Any] = Field(default_factory=dict)
