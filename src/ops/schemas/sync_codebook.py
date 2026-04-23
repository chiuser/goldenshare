from __future__ import annotations

from pydantic import BaseModel


class SyncCodebookItem(BaseModel):
    code: str
    label: str
    phase: str | None = None
    suggested_action: str | None = None


class SyncCodebookResponse(BaseModel):
    version: str
    updated_at: str
    error_codes: list[SyncCodebookItem]
    reason_codes: list[SyncCodebookItem]
