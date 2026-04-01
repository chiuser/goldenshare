from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateExecutionRequest(BaseModel):
    spec_type: str
    spec_key: str
    params_json: dict = {}


class ExecutionListItem(BaseModel):
    id: int
    spec_type: str
    spec_key: str
    spec_display_name: str | None = None
    schedule_display_name: str | None = None
    trigger_source: str
    status: str
    requested_by_username: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    rows_fetched: int
    rows_written: int
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: int | None = None
    progress_message: str | None = None
    last_progress_at: datetime | None = None
    summary_message: str | None = None
    error_code: str | None = None


class ExecutionListResponse(BaseModel):
    items: list[ExecutionListItem]
    total: int


class ExecutionStepItem(BaseModel):
    id: int
    step_key: str
    display_name: str
    sequence_no: int
    unit_kind: str | None = None
    unit_value: str | None = None
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    rows_fetched: int
    rows_written: int
    message: str | None = None


class ExecutionEventItem(BaseModel):
    id: int
    step_id: int | None = None
    event_type: str
    level: str
    message: str | None = None
    payload_json: dict
    occurred_at: datetime


class ExecutionLogItem(BaseModel):
    id: int
    execution_id: int | None = None
    job_name: str
    run_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    rows_fetched: int
    rows_written: int
    message: str | None = None


class ExecutionDetailResponse(BaseModel):
    id: int
    schedule_id: int | None = None
    spec_type: str
    spec_key: str
    spec_display_name: str | None = None
    schedule_display_name: str | None = None
    trigger_source: str
    status: str
    requested_by_username: str | None = None
    requested_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    params_json: dict
    summary_message: str | None = None
    rows_fetched: int
    rows_written: int
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: int | None = None
    progress_message: str | None = None
    last_progress_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    canceled_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    steps: list[ExecutionStepItem]
    events: list[ExecutionEventItem]


class ExecutionStepsResponse(BaseModel):
    execution_id: int
    items: list[ExecutionStepItem]


class ExecutionEventsResponse(BaseModel):
    execution_id: int
    items: list[ExecutionEventItem]


class ExecutionLogsResponse(BaseModel):
    execution_id: int
    items: list[ExecutionLogItem]
