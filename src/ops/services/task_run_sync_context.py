from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode


class TaskRunSyncContext(SyncExecutionContext):
    """Ops 侧进度适配：同步引擎只更新 TaskRun 当前快照。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def is_cancel_requested(self, *, execution_id: int) -> bool:
        cancel_requested_at = self.session.execute(
            select(TaskRun.cancel_requested_at).where(TaskRun.id == execution_id)
        ).scalar_one_or_none()
        return isinstance(cancel_requested_at, datetime)

    def update_progress(
        self,
        *,
        execution_id: int,
        current: int,
        total: int,
        message: str,
        rows_fetched: int | None = None,
        rows_saved: int | None = None,
        rows_rejected: int | None = None,
        current_object: dict[str, Any] | None = None,
    ) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return
        progress_session = Session(bind=bind, autoflush=False, autocommit=False, future=True)
        try:
            task_run = progress_session.get(TaskRun, execution_id)
            if task_run is None:
                return
            task_run.unit_done = max(int(current), 0)
            task_run.unit_total = max(int(total), 0)
            task_run.progress_percent = int((current / total) * 100) if total else None
            task_run.rows_fetched = int(rows_fetched if rows_fetched is not None else task_run.rows_fetched or 0)
            task_run.rows_saved = int(rows_saved if rows_saved is not None else task_run.rows_saved or 0)
            task_run.rows_rejected = int(rows_rejected if rows_rejected is not None else task_run.rows_rejected or 0)
            task_run.current_object_json = self._sanitize_current_object(current_object)
            self._update_current_running_node(progress_session, task_run)
            progress_session.commit()
        except Exception:
            progress_session.rollback()
        finally:
            progress_session.close()

    @staticmethod
    def _update_current_running_node(progress_session: Session, task_run: TaskRun) -> None:
        if task_run.current_node_id is None:
            return
        node = progress_session.get(TaskRunNode, task_run.current_node_id)
        if node is None or node.task_run_id != task_run.id or node.status != "running":
            return
        node.rows_fetched = task_run.rows_fetched
        node.rows_saved = task_run.rows_saved
        node.rows_rejected = task_run.rows_rejected

    @staticmethod
    def _sanitize_current_object(value: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        allowed = {
            key: value.get(key)
            for key in ("entity", "time", "attributes")
            if isinstance(value.get(key), dict)
        }
        return allowed
