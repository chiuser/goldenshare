from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.ops.job_execution import JobExecution
from src.models.ops.job_execution_event import JobExecutionEvent
from src.models.ops.sync_run_log import SyncRunLog


@dataclass(slots=True)
class ReconciledExecution:
    id: int
    previous_status: str
    new_status: str
    reason: str


class OperationsExecutionReconciliationService:
    def preview_stale_executions(
        self,
        session: Session,
        *,
        stale_for_minutes: int = 30,
        limit: int = 200,
        now: datetime | None = None,
    ) -> list[ReconciledExecution]:
        threshold = self._threshold(stale_for_minutes=stale_for_minutes, now=now)
        executions = self._load_open_executions(session=session, limit=limit)
        return [
            self._build_preview_item(session=session, execution=execution, threshold=threshold)
            for execution in executions
            if self._is_stale(session=session, execution=execution, threshold=threshold)
        ]

    def reconcile_stale_executions(
        self,
        session: Session,
        *,
        stale_for_minutes: int = 30,
        limit: int = 200,
        now: datetime | None = None,
    ) -> list[ReconciledExecution]:
        threshold = self._threshold(stale_for_minutes=stale_for_minutes, now=now)
        executions = self._load_open_executions(session=session, limit=limit)
        reconciled: list[ReconciledExecution] = []
        for execution in executions:
            if not self._is_stale(session=session, execution=execution, threshold=threshold):
                continue
            item = self._apply_reconciliation(session=session, execution=execution, now=now or datetime.now(timezone.utc))
            reconciled.append(item)
        session.commit()
        return reconciled

    @staticmethod
    def _threshold(*, stale_for_minutes: int, now: datetime | None) -> datetime:
        base_now = now or datetime.now(timezone.utc)
        return base_now - timedelta(minutes=max(1, stale_for_minutes))

    @staticmethod
    def _load_open_executions(session: Session, *, limit: int) -> list[JobExecution]:
        return list(
            session.scalars(
                select(JobExecution)
                .where(JobExecution.status.in_(("queued", "running")))
                .order_by(JobExecution.requested_at.asc(), JobExecution.id.asc())
                .limit(max(1, min(limit, 1000)))
            )
        )

    def _is_stale(self, *, session: Session, execution: JobExecution, threshold: datetime) -> bool:
        return self._last_activity_at(session=session, execution=execution) < threshold

    def _build_preview_item(
        self,
        *,
        session: Session,
        execution: JobExecution,
        threshold: datetime,
    ) -> ReconciledExecution:
        _ = threshold
        new_status, reason = self._target_status_and_reason(execution)
        return ReconciledExecution(
            id=execution.id,
            previous_status=execution.status,
            new_status=new_status,
            reason=reason,
        )

    def _apply_reconciliation(
        self,
        *,
        session: Session,
        execution: JobExecution,
        now: datetime,
    ) -> ReconciledExecution:
        new_status, reason = self._target_status_and_reason(execution)
        previous_status = execution.status
        execution.status = new_status
        execution.ended_at = now
        if new_status == "canceled":
            execution.canceled_at = execution.canceled_at or now
            execution.summary_message = "任务在停止后未正常收尾，系统已将状态修正为已取消。"
            execution.error_code = None
            execution.error_message = None
            event_type = "canceled"
            level = "WARNING"
        else:
            execution.summary_message = "任务长时间没有新进展，系统已将状态修正为执行失败。"
            execution.error_code = "stale_execution"
            execution.error_message = reason
            event_type = "failed"
            level = "ERROR"

        execution.progress_message = execution.progress_message or execution.summary_message
        execution.last_progress_at = execution.last_progress_at or now
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type=event_type,
                level=level,
                message=reason,
                payload_json={"reconciled": True, "previous_status": previous_status, "new_status": new_status},
                occurred_at=now,
            )
        )
        session.add(execution)
        return ReconciledExecution(
            id=execution.id,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
        )

    def _last_activity_at(self, *, session: Session, execution: JobExecution) -> datetime:
        event_last = session.scalar(
            select(func.max(JobExecutionEvent.occurred_at)).where(JobExecutionEvent.execution_id == execution.id)
        )
        log_last = session.scalar(
            select(func.max(func.coalesce(SyncRunLog.ended_at, SyncRunLog.started_at))).where(SyncRunLog.execution_id == execution.id)
        )
        candidates = [
            execution.last_progress_at,
            execution.started_at,
            execution.queued_at,
            execution.requested_at,
            execution.cancel_requested_at,
            event_last,
            log_last,
        ]
        normalized = [self._normalize_datetime(value) for value in candidates if value is not None]
        return max(normalized) if normalized else datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _target_status_and_reason(execution: JobExecution) -> tuple[str, str]:
        if execution.cancel_requested_at is not None:
            return "canceled", "任务已经收到停止请求，但长时间没有完成收尾，系统已修正为已取消。"
        return "failed", "任务长时间没有任何新进展，推定已经中断，系统已修正为执行失败。"

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
