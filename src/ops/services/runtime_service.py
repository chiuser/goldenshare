from __future__ import annotations

from sqlalchemy.orm import Session

from src.ops.runtime import OperationsScheduler, OperationsWorker


class OpsRuntimeCommandService:
    def __init__(self) -> None:
        self.scheduler = OperationsScheduler()
        self.worker = OperationsWorker()

    def scheduler_tick(self, session: Session, *, limit: int) -> list:
        return self.scheduler.run_once(session, limit=limit)

    def worker_run(self, session: Session, *, limit: int) -> list:
        processed = []
        for _ in range(limit):
            task_run = self.worker.run_next(session)
            if task_run is None:
                break
            processed.append(task_run)
        return processed

    def run_task_run(self, session: Session, *, task_run_id: int):
        return self.worker.run_task_run(session, task_run_id)
