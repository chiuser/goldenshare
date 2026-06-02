from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RealtimeConfigFieldOption(BaseModel):
    label: str
    value: str


class RealtimeConfigField(BaseModel):
    key: str
    label: str
    editable: bool
    control: str
    value_type: str
    options: list[RealtimeConfigFieldOption] = Field(default_factory=list)


class RealtimeConfigObjectSummary(BaseModel):
    object_key: str
    object_kind: str
    display_name: str
    enabled: bool
    version: int
    requires_collector_restart: bool


class RealtimeConfigObjectListResponse(BaseModel):
    items: list[RealtimeConfigObjectSummary]


class RealtimeConfigObjectDetailResponse(BaseModel):
    object_key: str
    display_name: str
    object_kind: str
    mode: str = "view"
    version: int
    requires_collector_restart: bool
    effective_config: dict[str, Any]
    locked_config: dict[str, Any]
    fields: list[RealtimeConfigField]


class RealtimeConfigDraftRequest(BaseModel):
    runtime_config: dict[str, Any]


class RealtimeConfigPublishRequest(BaseModel):
    version: int
    runtime_config: dict[str, Any]


class RealtimeConfigValidationErrorItem(BaseModel):
    field: str | None = None
    code: str
    message: str


class RealtimeConfigWarningItem(BaseModel):
    field: str | None = None
    message: str


class RealtimeConfigDiffItem(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class RealtimeConfigImpact(BaseModel):
    requires_collector_restart: bool
    affected_feeds: list[str]


class RealtimeConfigValidateResponse(BaseModel):
    valid: bool
    errors: list[RealtimeConfigValidationErrorItem]
    warnings: list[RealtimeConfigWarningItem]
    diff: list[RealtimeConfigDiffItem]
    impact: RealtimeConfigImpact


class RealtimeConfigPublishResponse(RealtimeConfigObjectDetailResponse):
    warnings: list[RealtimeConfigWarningItem]
    impact: RealtimeConfigImpact
    revision_id: int | None = None


class RealtimeConfigRevisionItem(BaseModel):
    id: int
    object_type: str
    object_id: str
    action: str
    before_json: dict | None = None
    after_json: dict | None = None
    changed_by_username: str | None = None
    changed_at: datetime


class RealtimeConfigRevisionListResponse(BaseModel):
    items: list[RealtimeConfigRevisionItem]
    total: int
