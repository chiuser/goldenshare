from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.feishu_task_notification_service import FeishuTaskNotificationService
from src.ops.services.task_run_completion_service import TaskRunCompletionCursor, TaskRunCompletionService


LOGGER = logging.getLogger(__name__)


class TaskRunCompletionWorker:
    def __init__(
        self,
        *,
        completion_service: TaskRunCompletionService | None = None,
        notification_service: FeishuTaskNotificationService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.completion_service = completion_service or TaskRunCompletionService()
        self.notification_service = notification_service or FeishuTaskNotificationService()
        self.logger = logger or LOGGER
        self._cursor: TaskRunCompletionCursor | None = None

    def run_cycle(self, session: Session, *, batch_size: int | None = None) -> int:
        if self._cursor is None:
            self._cursor = self.completion_service.initialize_cursor(session)
            return 0

        limit = batch_size if batch_size is not None else get_settings().ops_task_completion_worker_batch_size
        task_runs = self.completion_service.load_completed_after(session, cursor=self._cursor, limit=limit)
        processed = 0
        for task_run in task_runs:
            self._process_task_run(session, task_run)
            self._cursor = TaskRunCompletionCursor(ended_at=task_run.ended_at, task_run_id=int(task_run.id))
            processed += 1
        return processed

    def _process_task_run(self, session: Session, task_run: TaskRun) -> None:
        summary = self.completion_service.build_completion_summary(
            session,
            task_run,
            public_base_url=get_settings().ops_public_base_url,
        )
        try:
            refreshed = self.completion_service.refresh_snapshot_for_task_run(session, task_run)
            if refreshed:
                self.logger.info("Refreshed dataset status snapshot after task_run#%s: %s", task_run.id, refreshed)
        except Exception:
            self.logger.exception("Failed to refresh dataset status snapshot after task_run#%s", task_run.id)

        try:
            self.notification_service.send_task_completion(summary)
        except Exception:
            self.logger.exception("Failed to send Feishu task completion notification for task_run#%s", task_run.id)
