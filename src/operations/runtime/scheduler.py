from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.operations.services import OperationsScheduleService


class OperationsScheduler:
    def __init__(self) -> None:
        self.schedule_service = OperationsScheduleService()

    def run_once(self, session: Session, *, now: datetime | None = None, limit: int = 100) -> list[JobExecution]:
        return self.schedule_service.enqueue_due_schedules(session, now=now, limit=limit)
