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


class IngestionError(RuntimeError):
    def __init__(self, structured_error: StructuredError) -> None:
        self.structured_error = structured_error
        super().__init__(structured_error.message)


class IngestionValidationError(IngestionError):
    pass


class IngestionPlanningError(IngestionError):
    pass


class IngestionSourceError(IngestionError):
    pass


class IngestionNormalizeError(IngestionError):
    pass


class IngestionWriteError(IngestionError):
    pass
