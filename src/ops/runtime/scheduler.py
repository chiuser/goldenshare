from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.ops.models.ops.task_run import TaskRun
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService


class OperationsScheduler:
    def __init__(self) -> None:
        self.schedule_service = OperationsScheduleService()
        self.probe_runtime_service = ProbeRuntimeService()

    def run_once(self, session: Session, *, now: datetime | None = None, limit: int = 100) -> list[TaskRun]:
        scheduled = self.schedule_service.enqueue_due_schedules(session, now=now, limit=limit)
        probe_executions, _ = self.probe_runtime_service.run_once(session, now=now, limit=limit)
        return [*scheduled, *probe_executions]
