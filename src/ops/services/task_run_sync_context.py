from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.ops.models.ops.task_run import TaskRun


class TaskRunSyncContext(SyncExecutionContext):
    """Ops 侧进度适配：同步引擎只更新 TaskRun 当前快照。"""

    MAX_CONTEXT_KEYS = {
        "unit",
        "ts_code",
        "security_name",
        "index_code",
        "index_name",
        "board_code",
        "board_name",
        "trade_date",
        "freq",
        "start_date",
        "end_date",
        "enum_field",
        "enum_value",
    }

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
    ) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return
        progress_session = Session(bind=bind, autoflush=False, autocommit=False, future=True)
        try:
            task_run = progress_session.get(TaskRun, execution_id)
            if task_run is None:
                return
            payload = self._parse_message(message)
            task_run.unit_done = max(int(current), 0)
            task_run.unit_total = max(int(total), 0)
            task_run.progress_percent = int((current / total) * 100) if total else None
            task_run.rows_fetched = int(payload.get("rows_fetched") or task_run.rows_fetched or 0)
            task_run.rows_saved = int(payload.get("rows_saved") or task_run.rows_saved or 0)
            task_run.rows_rejected = int(payload.get("rows_rejected") or task_run.rows_rejected or 0)
            task_run.current_context_json = dict(payload.get("context") or {})
            progress_session.commit()
        finally:
            progress_session.close()

    @classmethod
    def _parse_message(cls, message: str) -> dict[str, Any]:
        kv_pairs = dict(re.findall(r"([a-zA-Z_]+)=([^\s]+)", message or ""))
        fetched = cls._safe_int(kv_pairs.get("fetched"))
        written = cls._safe_int(kv_pairs.get("committed") or kv_pairs.get("written"))
        rejected = cls._safe_int(kv_pairs.get("rejected"))
        context = {
            key: cls._format_context_value(value)
            for key, value in kv_pairs.items()
            if key in cls.MAX_CONTEXT_KEYS and value not in (None, "")
        }
        return {
            "rows_fetched": fetched,
            "rows_saved": written,
            "rows_rejected": rejected,
            "context": context,
        }

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_context_value(value: Any) -> str:
        return str(value).replace("_", " ").strip()
