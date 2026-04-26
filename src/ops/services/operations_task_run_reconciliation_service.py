from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue


@dataclass(slots=True)
class ReconciledTaskRun:
    id: int
    previous_status: str
    new_status: str
    reason: str


class OperationsTaskRunReconciliationService:
    def preview_stale_task_runs(
        self,
        session: Session,
        *,
        stale_for_minutes: int = 30,
        limit: int = 200,
        now: datetime | None = None,
    ) -> list[ReconciledTaskRun]:
        threshold = self._threshold(stale_for_minutes=stale_for_minutes, now=now)
        task_runs = self._load_open_task_runs(session=session, limit=limit)
        return [
            self._build_preview_item(task_run=task_run)
            for task_run in task_runs
            if self._is_stale(task_run=task_run, threshold=threshold)
        ]

    def reconcile_stale_task_runs(
        self,
        session: Session,
        *,
        stale_for_minutes: int = 30,
        limit: int = 200,
        now: datetime | None = None,
    ) -> list[ReconciledTaskRun]:
        threshold = self._threshold(stale_for_minutes=stale_for_minutes, now=now)
        task_runs = self._load_open_task_runs(session=session, limit=limit)
        reconciled: list[ReconciledTaskRun] = []
        for task_run in task_runs:
            if not self._is_stale(task_run=task_run, threshold=threshold):
                continue
            reconciled.append(self._apply_reconciliation(session=session, task_run=task_run, now=now or datetime.now(timezone.utc)))
        session.commit()
        return reconciled

    @staticmethod
    def _threshold(*, stale_for_minutes: int, now: datetime | None) -> datetime:
        base_now = now or datetime.now(timezone.utc)
        return base_now - timedelta(minutes=max(1, stale_for_minutes))

    @staticmethod
    def _load_open_task_runs(session: Session, *, limit: int) -> list[TaskRun]:
        return list(
            session.scalars(
                select(TaskRun)
                .where(TaskRun.status.in_(("queued", "running", "canceling")))
                .order_by(TaskRun.requested_at.asc(), TaskRun.id.asc())
                .limit(max(1, min(limit, 1000)))
            )
        )

    @staticmethod
    def _is_stale(*, task_run: TaskRun, threshold: datetime) -> bool:
        candidates = [
            task_run.started_at,
            task_run.queued_at,
            task_run.requested_at,
            task_run.cancel_requested_at,
            task_run.updated_at,
        ]
        normalized = [OperationsTaskRunReconciliationService._normalize_datetime(value) for value in candidates if value is not None]
        return (max(normalized) if normalized else datetime.min.replace(tzinfo=timezone.utc)) < threshold

    def _build_preview_item(self, *, task_run: TaskRun) -> ReconciledTaskRun:
        new_status, reason = self._target_status_and_reason(task_run)
        return ReconciledTaskRun(id=task_run.id, previous_status=task_run.status, new_status=new_status, reason=reason)

    def _apply_reconciliation(self, *, session: Session, task_run: TaskRun, now: datetime) -> ReconciledTaskRun:
        new_status, reason = self._target_status_and_reason(task_run)
        previous_status = task_run.status
        task_run.status = new_status
        task_run.ended_at = now
        if new_status == "canceled":
            task_run.canceled_at = task_run.canceled_at or now
            task_run.status_reason_code = "stale_cancel_reconciled"
        else:
            task_run.status_reason_code = "stale_task_run"
            issue = TaskRunIssue(
                task_run_id=task_run.id,
                node_id=task_run.current_node_id,
                severity="error",
                code="stale_task_run",
                title="任务长时间无进展",
                operator_message="任务长时间没有新进展，系统已将状态修正为执行失败。",
                suggested_action="请确认业务数据后再决定是否重新提交。",
                technical_message=reason,
                technical_payload_json={"source_phase": "reconcile", "previous_status": previous_status, "new_status": new_status},
                object_json=dict(task_run.current_object_json or {}),
                source_phase="reconcile",
                fingerprint=f"{task_run.id}:stale_task_run",
                occurred_at=now,
            )
            session.add(issue)
            session.flush()
            task_run.primary_issue_id = issue.id
        return ReconciledTaskRun(id=task_run.id, previous_status=previous_status, new_status=new_status, reason=reason)

    @staticmethod
    def _target_status_and_reason(task_run: TaskRun) -> tuple[str, str]:
        if task_run.cancel_requested_at is not None:
            return "canceled", "任务已经收到停止请求，但长时间没有完成收尾，系统已修正为已取消。"
        return "failed", "任务长时间没有任何新进展，推定已经中断，系统已修正为执行失败。"

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
