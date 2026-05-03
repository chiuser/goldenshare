from __future__ import annotations

from typing import Any, Literal

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


ManualActionTimeMode = Literal["none", "point", "range"]
ManualActionTimeControl = Literal[
    "none",
    "trade_date",
    "trade_date_range",
    "calendar_date",
    "calendar_date_range",
    "month",
    "month_range",
    "month_window_range",
]
ManualActionSelectionRule = Literal[
    "none",
    "trading_day_only",
    "week_last_trading_day",
    "month_last_trading_day",
    "calendar_day",
    "week_friday",
    "month_end",
    "month_key",
    "month_window",
]


class ManualActionTimeModeResponse(BaseModel):
    mode: ManualActionTimeMode
    label: str
    description: str
    control: ManualActionTimeControl
    selection_rule: ManualActionSelectionRule
    date_field: str | None = None


class ManualActionTimeFormResponse(BaseModel):
    default_mode: ManualActionTimeMode
    modes: list[ManualActionTimeModeResponse]

    def find_mode(self, mode: str) -> ManualActionTimeModeResponse | None:
        return next((item for item in self.modes if item.mode == mode), None)


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
