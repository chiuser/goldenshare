from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError


class ScheduleProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: str | None = "15:30"
    window_end: str | None = "17:00"
    probe_interval_seconds: int = 300
    max_triggers_per_day: int = 1
    condition_kind: str = "freshness_latest_open"

    @model_validator(mode="before")
    @classmethod
    def reject_operator_owned_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "source_key" in value:
            raise PydanticCustomError(
                "source_key.operator_forbidden",
                "source_key 由系统默认来源决定，运营端不能提交",
            )
        if "workflow_dataset_keys" in value:
            raise PydanticCustomError(
                "workflow_dataset_keys.operator_forbidden",
                "工作流自动任务不支持探测目标数据集",
            )
        return value


class ScheduleProbeConfigResponse(BaseModel):
    source: Literal["system_default"]
    source_label: str
    window_start: str | None
    window_end: str | None
    probe_interval_seconds: int
    max_triggers_per_day: int
    condition_kind: str


class CreateScheduleRequest(BaseModel):
    target_type: str
    target_key: str
    display_name: str
    schedule_type: str
    trigger_mode: str = "schedule"
    cron_expr: str | None = None
    timezone: str = "Asia/Shanghai"
    calendar_policy: str | None = None
    probe_config: ScheduleProbeConfig | None = None
    params_json: dict = {}
    retry_policy_json: dict = {}
    concurrency_policy_json: dict = {}
    next_run_at: datetime | None = None


class UpdateScheduleRequest(BaseModel):
    target_type: str | None = None
    target_key: str | None = None
    display_name: str | None = None
    schedule_type: str | None = None
    trigger_mode: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    calendar_policy: str | None = None
    probe_config: ScheduleProbeConfig | None = None
    params_json: dict | None = None
    retry_policy_json: dict | None = None
    concurrency_policy_json: dict | None = None
    next_run_at: datetime | None = None


class ScheduleListItem(BaseModel):
    id: int
    target_type: str
    target_key: str
    manual_action_key: str | None = None
    target_display_name: str
    display_name: str
    status: str
    schedule_type: str
    trigger_mode: str = "schedule"
    cron_expr: str | None = None
    timezone: str
    calendar_policy: str | None = None
    next_run_at: datetime | None = None
    last_triggered_at: datetime | None = None
    created_by_username: str | None = None
    updated_by_username: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    items: list[ScheduleListItem]
    total: int


class ScheduleDetailResponse(BaseModel):
    id: int
    target_type: str
    target_key: str
    manual_action_key: str | None = None
    target_display_name: str
    display_name: str
    status: str
    schedule_type: str
    trigger_mode: str = "schedule"
    cron_expr: str | None = None
    timezone: str
    calendar_policy: str | None = None
    probe_config: ScheduleProbeConfigResponse | None = None
    params_json: dict
    retry_policy_json: dict
    concurrency_policy_json: dict
    next_run_at: datetime | None = None
    last_triggered_at: datetime | None = None
    created_by_username: str | None = None
    updated_by_username: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleRevisionItem(BaseModel):
    id: int
    object_type: str
    object_id: str
    action: str
    before_json: dict | None = None
    after_json: dict | None = None
    changed_by_username: str | None = None
    changed_at: datetime


class ScheduleRevisionListResponse(BaseModel):
    items: list[ScheduleRevisionItem]
    total: int


class SchedulePreviewRequest(BaseModel):
    schedule_type: str
    cron_expr: str | None = None
    timezone: str = "Asia/Shanghai"
    calendar_policy: str | None = None
    next_run_at: datetime | None = None
    count: int = 5


class SchedulePreviewResponse(BaseModel):
    schedule_type: str
    timezone: str
    preview_times: list[datetime]


class DeleteScheduleResponse(BaseModel):
    id: int
    status: str = "deleted"
