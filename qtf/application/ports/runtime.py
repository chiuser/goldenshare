from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TaskRunIntent:
    task_type: str
    resource_key: str
    action: str
    title: str
    request_payload: dict[str, object]
    requested_by_user_id: int


class TaskRunIntentStager(Protocol):
    def stage(self, intent: TaskRunIntent) -> int: ...


class RunObserver(Protocol):
    def stage(self, *, task_run_id: int, stage_key: str, title: str, sequence_no: int) -> None: ...

    def progress(
        self,
        *,
        task_run_id: int,
        stage_key: str,
        completed: int,
        total: int,
        message: str,
    ) -> None: ...

    def issue(self, *, task_run_id: int, code: str, message: str) -> None: ...


class CancellationProbe(Protocol):
    def is_cancel_requested(self, task_run_id: int) -> bool: ...


class RunUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
