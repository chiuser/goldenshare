from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateExecutionRequest(BaseModel):
    spec_type: str
    spec_key: str
    params_json: dict = {}


class ExecutionListItem(BaseModel):
    id: int
    spec_type: str
    spec_key: str
    dataset_key: str | None = None
    source_key: str | None = None
    stage: str | None = None
    policy_version: int | None = None
    run_scope: str | None = None
    run_profile: str | None = None
    workflow_profile: str | None = None
    correlation_id: str | None = None
    rerun_id: str | None = None
    resume_from_step_key: str | None = None
    status_reason_code: str | None = None
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
    failure_policy_effective: str | None = None
    depends_on_step_keys_json: list[str] = Field(default_factory=list)
    blocked_by_step_key: str | None = None
    skip_reason_code: str | None = None
    unit_total: int = 0
    unit_done: int = 0
    unit_failed: int = 0


class ExecutionEventItem(BaseModel):
    id: int
    step_id: int | None = None
    event_type: str
    level: str
    message: str | None = None
    payload_json: dict
    occurred_at: datetime
    event_id: str | None = None
    event_version: int | None = None
    correlation_id: str | None = None
    unit_id: str | None = None
    producer: str | None = None
    dedupe_key: str | None = None


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
    dataset_key: str | None = None
    source_key: str | None = None
    stage: str | None = None
    policy_version: int | None = None
    run_scope: str | None = None
    run_profile: str | None = None
    workflow_profile: str | None = None
    correlation_id: str | None = None
    rerun_id: str | None = None
    resume_from_step_key: str | None = None
    status_reason_code: str | None = None
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
