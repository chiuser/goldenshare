from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateResolutionReleaseRequest(BaseModel):
    dataset_key: str
    target_policy_version: int
    status: str = "previewing"
    rollback_to_release_id: int | None = None


class UpdateResolutionReleaseStatusRequest(BaseModel):
    status: str
    finished_at: datetime | None = None


class UpsertResolutionReleaseStageStatusItem(BaseModel):
    dataset_key: str
    source_key: str | None = None
    stage: str
    status: str
    rows_in: int | None = None
    rows_out: int | None = None
    message: str | None = None
    updated_at: datetime | None = None


class UpsertResolutionReleaseStageStatusRequest(BaseModel):
    items: list[UpsertResolutionReleaseStageStatusItem]


class ResolutionReleaseListItem(BaseModel):
    id: int
    dataset_key: str
    dataset_display_name: str | None = None
    target_policy_version: int
    status: str
    triggered_by_username: str | None = None
    triggered_at: datetime
    finished_at: datetime | None = None
    rollback_to_release_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ResolutionReleaseDetailResponse(ResolutionReleaseListItem):
    pass


class ResolutionReleaseListResponse(BaseModel):
    items: list[ResolutionReleaseListItem]
    total: int


class ResolutionReleaseStageStatusItem(BaseModel):
    id: int
    release_id: int
    dataset_key: str
    dataset_display_name: str | None = None
    source_key: str | None = None
    source_display_name: str | None = None
    stage: str
    stage_display_name: str | None = None
    status: str
    rows_in: int | None = None
    rows_out: int | None = None
    message: str | None = None
    updated_at: datetime


class ResolutionReleaseStageStatusListResponse(BaseModel):
    items: list[ResolutionReleaseStageStatusItem]
    total: int
