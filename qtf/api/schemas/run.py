from __future__ import annotations

from datetime import datetime

from pydantic import Field

from qtf.api.schemas.common import QtfApiModel
from qtf.api.schemas.research import SampleSplitView


class CreateRunRequest(QtfApiModel):
    request_key: str = Field(min_length=1, max_length=96)
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CancelRunRequest(QtfApiModel):
    request_key: str = Field(min_length=1, max_length=96)
    current_version: str = Field(min_length=1, max_length=24)
    comment: str | None = Field(default=None, max_length=1_000)


class RunCreateResponse(QtfApiModel):
    run_key: str
    run_status: str
    validation_status: str
    task_run_id: int


class RunUpdateView(QtfApiModel):
    occurred_at: datetime
    stage_key: str
    message: str


class RunProgressView(QtfApiModel):
    percent: int | None
    completed_parameter_set_count: int
    total_parameter_set_count: int
    current_stage_key: str | None
    can_cancel: bool
    observer_status: str
    latest_updates: list[RunUpdateView]


class RunStageView(QtfApiModel):
    stage_key: str
    label: str
    status: str
    summary: str | None


class FrozenPlanSummary(QtfApiModel):
    object_count: int
    comparison_scope: str
    candidate_count: int
    sample_split: SampleSplitView
    source_kind: str


class RunFailureView(QtfApiModel):
    code: str
    message: str
    retryable: bool


class RunDetailResponse(QtfApiModel):
    run_key: str
    research_key: str
    revision_key: str
    revision_no: int
    run_status: str
    validation_status: str
    formula_version: str
    code_commit: str | None
    source_content_hash: str | None
    started_at: datetime | None
    ended_at: datetime | None
    progress: RunProgressView
    stages: list[RunStageView]
    frozen_plan_summary: FrozenPlanSummary
    failure: RunFailureView | None
