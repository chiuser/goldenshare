from __future__ import annotations

from datetime import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.ops.models.ops.job_execution import JobExecution


class JobExecutionSyncContext(SyncExecutionContext):
    """ops 侧适配层：将 foundation 同步进度 contract 对接到 JobExecution 模型。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def is_cancel_requested(self, *, execution_id: int) -> bool:
        cancel_requested_at = self.session.execute(
            select(JobExecution.cancel_requested_at).where(JobExecution.id == execution_id)
        ).scalar_one_or_none()
        return isinstance(cancel_requested_at, datetime)

    def update_progress(
        self,
        *,
        execution_id: int,
        current: int,
        total: int,
        message: str,
    ) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return
        progress_session = Session(bind=bind, autoflush=False, autocommit=False, future=True)
        try:
            execution = progress_session.get(JobExecution, execution_id)
            if execution is None:
                return
            execution.progress_current = current
            execution.progress_total = total
            execution.progress_percent = int((current / total) * 100) if total else None
            execution.progress_message = message
            execution.last_progress_at = datetime.now(timezone.utc)
            progress_session.commit()
        finally:
            progress_session.close()

