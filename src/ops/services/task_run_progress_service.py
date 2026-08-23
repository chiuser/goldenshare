from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode


SessionFactory = Callable[[], Session]


class TaskRunProgressService:
    """Best-effort Ops observer. Every call owns and commits its own session."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def stage(self, *, task_run_id: int, stage_key: str, title: str, sequence_no: int) -> None:
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            for previous in session.scalars(
                select(TaskRunNode).where(
                    TaskRunNode.task_run_id == task_run_id,
                    TaskRunNode.node_type == "qtf_stage",
                    TaskRunNode.status == "running",
                    TaskRunNode.node_key != stage_key,
                )
            ):
                previous.status = "success"
                previous.ended_at = now
            node = session.scalar(
                select(TaskRunNode).where(
                    TaskRunNode.task_run_id == task_run_id,
                    TaskRunNode.node_key == stage_key,
                )
            )
            if node is None:
                node = TaskRunNode(
                    task_run_id=task_run_id,
                    parent_node_id=None,
                    node_key=stage_key,
                    node_type="qtf_stage",
                    sequence_no=sequence_no,
                    title=title,
                    resource_key="sector_heat_research",
                    status="running",
                    time_input_json={},
                    context_json={},
                    started_at=now,
                )
                session.add(node)
                session.flush()
            task_run = session.get(TaskRun, task_run_id)
            if task_run is not None:
                task_run.current_node_id = node.id
                task_run.current_object_json = {"stageKey": stage_key, "message": title}
            session.commit()

    def progress(
        self,
        *,
        task_run_id: int,
        stage_key: str,
        completed: int,
        total: int,
        message: str,
    ) -> None:
        with self._session_factory() as session:
            node = session.scalar(
                select(TaskRunNode).where(
                    TaskRunNode.task_run_id == task_run_id,
                    TaskRunNode.node_key == stage_key,
                )
            )
            if node is not None:
                node.status = "running" if completed < total else "success"
                node.context_json = {"completed": completed, "total": total, "message": message}
                if completed >= total:
                    node.ended_at = datetime.now(timezone.utc)
            task_run = session.get(TaskRun, task_run_id)
            if task_run is not None:
                task_run.unit_total = total
                task_run.unit_done = completed
                task_run.progress_percent = int(completed * 100 / total) if total > 0 else None
                task_run.current_object_json = {"stageKey": stage_key, "message": message}
            session.commit()

    def issue(self, *, task_run_id: int, code: str, message: str) -> None:
        with self._session_factory() as session:
            fingerprint = hashlib.sha256(f"{task_run_id}:{code}:{message}".encode("utf-8")).hexdigest()
            existing = session.scalar(
                select(TaskRunIssue).where(
                    TaskRunIssue.task_run_id == task_run_id,
                    TaskRunIssue.fingerprint == fingerprint,
                )
            )
            if existing is None:
                session.add(
                    TaskRunIssue(
                        task_run_id=task_run_id,
                        node_id=None,
                        severity="warning" if code == "canceled" else "error",
                        code=code,
                        title="量化运行提示" if code == "canceled" else "量化运行未完成",
                        operator_message=message,
                        suggested_action="查看运行详情后决定是否新建 Run。",
                        technical_message=None,
                        technical_payload_json={},
                        object_json={},
                        source_phase="qtf_execute",
                        fingerprint=fingerprint,
                        occurred_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
