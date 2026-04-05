from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.ops.models.ops.sync_run_log import SyncRunLog


class SyncRunLogDAO(BaseDAO[SyncRunLog]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, SyncRunLog)

    def start_log(self, job_name: str, run_type: str, execution_id: int | None = None) -> SyncRunLog:
        log = SyncRunLog(
            execution_id=execution_id,
            job_name=job_name,
            run_type=run_type,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        self.session.commit()
        self.session.refresh(log)
        return log

    def finish_log(self, log: SyncRunLog, status: str, rows_fetched: int, rows_written: int, message: str | None = None) -> None:
        log.status = status
        log.ended_at = datetime.now(timezone.utc)
        log.rows_fetched = rows_fetched
        log.rows_written = rows_written
        log.message = message
