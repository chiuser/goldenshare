from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class StructuredError:
    error_code: str
    error_type: str
    phase: str
    message: str
    retryable: bool
    unit_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class SyncV2Error(RuntimeError):
    def __init__(self, structured_error: StructuredError) -> None:
        self.structured_error = structured_error
        super().__init__(structured_error.message)


class SyncV2ValidationError(SyncV2Error):
    pass


class SyncV2PlanningError(SyncV2Error):
    pass


class SyncV2SourceError(SyncV2Error):
    pass


class SyncV2NormalizeError(SyncV2Error):
    pass


class SyncV2WriteError(SyncV2Error):
    pass
