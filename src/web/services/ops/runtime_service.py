from __future__ import annotations

from sqlalchemy.orm import Session

from src.operations.runtime import OperationsScheduler, OperationsWorker


class OpsRuntimeCommandService:
    def __init__(self) -> None:
        self.scheduler = OperationsScheduler()
        self.worker = OperationsWorker()

    def scheduler_tick(self, session: Session, *, limit: int) -> list:
        return self.scheduler.run_once(session, limit=limit)

    def worker_run(self, session: Session, *, limit: int) -> list:
        processed = []
        for _ in range(limit):
            execution = self.worker.run_next(session)
            if execution is None:
                break
            processed.append(execution)
        return processed

    def run_execution(self, session: Session, *, execution_id: int):
        return self.worker.run_execution(session, execution_id)
