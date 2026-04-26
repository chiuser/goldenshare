from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuntimeTickRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=1000)


class RuntimeTaskRunItem(BaseModel):
    id: int
    schedule_id: int | None = None
    task_type: str
    resource_key: str | None = None
    title: str
    trigger_source: str
    status: str
    requested_at: datetime
    rows_fetched: int
    rows_saved: int
    primary_issue_title: str | None = None


class SchedulerTickResponse(BaseModel):
    scheduled_count: int
    items: list[RuntimeTaskRunItem]


class WorkerRunResponse(BaseModel):
    processed_count: int
    items: list[RuntimeTaskRunItem]
