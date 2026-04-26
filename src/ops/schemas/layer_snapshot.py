from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class LayerSnapshotHistoryItem(BaseModel):
    id: int
    snapshot_date: date
    dataset_key: str
    dataset_display_name: str | None = None
    source_key: str | None = None
    stage: str
    status: str
    rows_in: int | None = None
    rows_out: int | None = None
    error_count: int | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    lag_seconds: int | None = None
    message: str | None = None
    calculated_at: datetime


class LayerSnapshotHistoryResponse(BaseModel):
    items: list[LayerSnapshotHistoryItem]
    total: int


class LayerSnapshotLatestItem(BaseModel):
    snapshot_date: date
    dataset_key: str
    dataset_display_name: str | None = None
    source_key: str | None = None
    stage: str
    status: str
    rows_in: int | None = None
    rows_out: int | None = None
    error_count: int | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    lag_seconds: int | None = None
    message: str | None = None
    calculated_at: datetime


class LayerSnapshotLatestResponse(BaseModel):
    items: list[LayerSnapshotLatestItem]
    total: int
