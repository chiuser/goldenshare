from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuntimeTickRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=1000)


class RuntimeExecutionItem(BaseModel):
    id: int
    schedule_id: int | None = None
    spec_type: str
    spec_key: str
    spec_display_name: str | None = None
    trigger_source: str
    status: str
    requested_at: datetime
    rows_fetched: int
    rows_written: int
    summary_message: str | None = None


class SchedulerTickResponse(BaseModel):
    scheduled_count: int
    items: list[RuntimeExecutionItem]


class WorkerRunResponse(BaseModel):
    processed_count: int
    items: list[RuntimeExecutionItem]
