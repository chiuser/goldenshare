from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExternalTaskDefinition:
    task_type: str
    validate_context: Callable[[object], None]
    resolve_title: Callable[[object], str]


@dataclass(frozen=True, slots=True)
class ExternalTaskExecutionOutcome:
    status: str
    summary_message: str | None = None
    status_reason_code: str | None = None
    rows_fetched: int = 0
    rows_saved: int = 0
    rows_rejected: int = 0


class ExternalTaskExecutor(Protocol):
    def execute(
        self,
        *,
        task_run_id: int,
        request_payload: Mapping[str, object],
    ) -> ExternalTaskExecutionOutcome: ...
