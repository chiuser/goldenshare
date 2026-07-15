from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.ops.models.ops.task_run import TaskRun
from src.ops.services.index_daily_completeness_reconciliation_service import IndexDailyCompletenessReconciliationService
from src.ops.services.date_completeness_schedule_service import DateCompletenessScheduleCommandService
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService


class OperationsScheduler:
    def __init__(self) -> None:
        self.schedule_service = OperationsScheduleService()
        self.probe_runtime_service = ProbeRuntimeService()
        self.date_completeness_schedule_service = DateCompletenessScheduleCommandService()
        self.index_daily_reconciliation_service = IndexDailyCompletenessReconciliationService()

    def run_once(self, session: Session, *, now: datetime | None = None, limit: int = 100) -> list[TaskRun]:
        scheduled = self.schedule_service.enqueue_due_schedules(session, now=now, limit=limit)
        self.date_completeness_schedule_service.enqueue_due_schedules(session, now=now, limit=limit)
        probe_task_runs, _ = self.probe_runtime_service.run_once(session, now=now, limit=limit)
        self.index_daily_reconciliation_service.enqueue_due_audits(session, now=now)
        return [*scheduled, *probe_task_runs]
