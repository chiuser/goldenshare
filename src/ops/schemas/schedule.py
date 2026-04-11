from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateScheduleRequest(BaseModel):
    spec_type: str
    spec_key: str
    display_name: str
    schedule_type: str
    cron_expr: str | None = None
    timezone: str = "Asia/Shanghai"
    calendar_policy: str | None = None
    params_json: dict = {}
    retry_policy_json: dict = {}
    concurrency_policy_json: dict = {}
    next_run_at: datetime | None = None


class UpdateScheduleRequest(BaseModel):
    spec_type: str | None = None
    spec_key: str | None = None
    display_name: str | None = None
    schedule_type: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    calendar_policy: str | None = None
    params_json: dict | None = None
    retry_policy_json: dict | None = None
    concurrency_policy_json: dict | None = None
    next_run_at: datetime | None = None


class ScheduleListItem(BaseModel):
    id: int
    spec_type: str
    spec_key: str
    spec_display_name: str | None = None
    display_name: str
    status: str
    schedule_type: str
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
    spec_type: str
    spec_key: str
    spec_display_name: str | None = None
    display_name: str
    status: str
    schedule_type: str
    cron_expr: str | None = None
    timezone: str
    calendar_policy: str | None = None
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
    next_run_at: datetime | None = None
    count: int = 5


class SchedulePreviewResponse(BaseModel):
    schedule_type: str
    timezone: str
    preview_times: list[datetime]


class DeleteScheduleResponse(BaseModel):
    id: int
    status: str = "deleted"
