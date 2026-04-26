from __future__ import annotations

from pydantic import BaseModel


class IngestionCodebookItem(BaseModel):
    code: str
    label: str
    phase: str | None = None
    suggested_action: str | None = None


class IngestionCodebookResponse(BaseModel):
    version: str
    updated_at: str
    error_codes: list[IngestionCodebookItem]
    reason_codes: list[IngestionCodebookItem]
