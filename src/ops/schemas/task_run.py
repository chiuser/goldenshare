from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskRunTimeInput(BaseModel):
    mode: str = "none"
    trade_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    month: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    date_field: str | None = None


class CreateTaskRunRequest(BaseModel):
    task_type: str = "dataset_action"
    resource_key: str | None = None
    action: str = "maintain"
    time_input: TaskRunTimeInput = Field(default_factory=TaskRunTimeInput)
    filters: dict[str, Any] = Field(default_factory=dict)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    schedule_id: int | None = None


class TaskRunCreateResponse(BaseModel):
    id: int
    status: str
    title: str
    resource_key: str | None = None
    created_at: datetime


class TaskRunTimeScope(BaseModel):
    kind: str
    start: str | None = None
    end: str | None = None
    label: str


class TaskRunListItem(BaseModel):
    id: int
    task_type: str
    resource_key: str | None = None
    action_key: str | None = None
    action: str
    title: str
    trigger_source: str
    status: str
    status_reason_code: str | None = None
    requested_by_username: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    time_scope: TaskRunTimeScope | None = None
    time_scope_label: str | None = None
    schedule_display_name: str | None = None
    unit_total: int
    unit_done: int
    unit_failed: int
    progress_percent: int | None = None
    rows_fetched: int
    rows_saved: int
    rows_rejected: int
    primary_issue_id: int | None = None
    primary_issue_title: str | None = None


class TaskRunListResponse(BaseModel):
    items: list[TaskRunListItem]
    total: int


class TaskRunSummaryResponse(BaseModel):
    total: int
    queued: int
    running: int
    success: int
    failed: int
    canceled: int


class TaskRunInfo(BaseModel):
    id: int
    task_type: str
    resource_key: str | None = None
    action_key: str | None = None
    action: str
    title: str
    trigger_source: str
    status: str
    status_reason_code: str | None = None
    requested_by_username: str | None = None
    schedule_display_name: str | None = None
    time_input: dict[str, Any]
    filters: dict[str, Any]
    time_scope: TaskRunTimeScope | None = None
    time_scope_label: str | None = None
    requested_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    canceled_at: datetime | None = None


class TaskRunDisplayField(BaseModel):
    label: str
    value: str


class TaskRunDisplayObject(BaseModel):
    title: str
    description: str | None = None
    fields: list[TaskRunDisplayField] = Field(default_factory=list)


class TaskRunProgress(BaseModel):
    unit_total: int
    unit_done: int
    unit_failed: int
    progress_percent: int | None = None
    rows_fetched: int
    rows_saved: int
    rows_rejected: int
    current_object: TaskRunDisplayObject | None = None


class TaskRunIssueSummary(BaseModel):
    id: int
    severity: str
    code: str
    title: str
    operator_message: str | None = None
    suggested_action: str | None = None
    object: TaskRunDisplayObject | None = None
    has_technical_detail: bool
    occurred_at: datetime


class TaskRunNodeItem(BaseModel):
    id: int
    parent_node_id: int | None = None
    node_key: str
    node_type: str
    sequence_no: int
    title: str
    resource_key: str | None = None
    status: str
    time_input: dict[str, Any]
    context: dict[str, Any]
    rows_fetched: int
    rows_saved: int
    rows_rejected: int
    issue_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None


class TaskRunActions(BaseModel):
    can_retry: bool
    can_cancel: bool
    can_copy_params: bool


class TaskRunViewResponse(BaseModel):
    run: TaskRunInfo
    progress: TaskRunProgress
    primary_issue: TaskRunIssueSummary | None = None
    nodes: list[TaskRunNodeItem]
    node_total: int
    nodes_truncated: bool = False
    actions: TaskRunActions


class TaskRunIssueDetailResponse(BaseModel):
    id: int
    task_run_id: int
    node_id: int | None = None
    severity: str
    code: str
    title: str
    operator_message: str | None = None
    suggested_action: str | None = None
    object: TaskRunDisplayObject | None = None
    technical_message: str | None = None
    technical_payload: dict[str, Any]
    source_phase: str | None = None
    occurred_at: datetime
