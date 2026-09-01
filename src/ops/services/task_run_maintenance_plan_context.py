from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import MaintenancePlanCheckpoint


class TaskRunMaintenancePlanContext:
    """Persist PLAN progress without sharing the Biz read-only transaction."""

    def __init__(
        self,
        session: Session,
        *,
        task_run_id: int,
        action_key: str,
        executor_key: str,
    ) -> None:
        bind = session.get_bind()
        if bind is None:
            raise RuntimeError("maintenance PLAN context requires a database bind")
        self._bind = bind
        self.task_run_id = task_run_id
        self._action_key = action_key
        self._executor_key = executor_key

    def is_cancel_requested(self) -> bool:
        with Session(bind=self._bind, autoflush=False, autocommit=False, future=True) as session:
            value = session.execute(
                select(TaskRun.cancel_requested_at, TaskRun.status).where(
                    TaskRun.id == self.task_run_id
                )
            ).one_or_none()
            return bool(value and (isinstance(value.cancel_requested_at, datetime) or value.status == "canceling"))

    def update_phase(
        self,
        *,
        unit_done: int,
        unit_total: int,
        phase: str,
        current_object: Mapping[str, Any],
    ) -> None:
        with Session(bind=self._bind, autoflush=False, autocommit=False, future=True) as session:
            task_run = self._require_active_task_run(session)
            self._validate_progress(unit_done=unit_done, unit_total=unit_total)
            task_run.unit_total = unit_total
            task_run.unit_done = unit_done
            task_run.unit_failed = 0
            task_run.progress_percent = self._building_percent(unit_done, unit_total)
            task_run.current_object_json = self._current_object(current_object)
            diagnostics = self._diagnostics(
                phase=phase,
                unit_done=unit_done,
                unit_total=unit_total,
            )
            task_run.ingestion_diagnostics_json = diagnostics
            self._update_node(session, task_run=task_run, diagnostics=diagnostics)
            session.commit()

    def save_checkpoint(self, checkpoint: MaintenancePlanCheckpoint) -> None:
        self._validate_progress(
            unit_done=checkpoint.unit_done,
            unit_total=checkpoint.unit_total,
        )
        if checkpoint.unit_done != len(checkpoint.units) + len(checkpoint.gaps):
            raise ValueError("maintenance PLAN checkpoint completion count is inconsistent")
        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "snapshot_state": "BUILDING",
            "action_key": self._action_key,
            "executor_key": self._executor_key,
            "plan_hash": None,
            "apply_ready": False,
            "expected_rows": max(int(checkpoint.expected_rows), 0),
            "units": [
                {"unit_key": unit.unit_key, "payload": dict(unit.payload)}
                for unit in checkpoint.units
            ],
            "metadata": {
                **dict(checkpoint.metadata),
                "gaps": [dict(gap) for gap in checkpoint.gaps],
                "checkpoint_unit_done": checkpoint.unit_done,
                "checkpoint_unit_total": checkpoint.unit_total,
            },
        }
        snapshot["snapshot_integrity_hash"] = self._snapshot_hash(snapshot)
        with Session(bind=self._bind, autoflush=False, autocommit=False, future=True) as session:
            task_run = self._require_active_task_run(session)
            task_run.plan_snapshot_json = snapshot
            task_run.unit_total = checkpoint.unit_total
            task_run.unit_done = checkpoint.unit_done
            task_run.unit_failed = 0
            task_run.progress_percent = self._building_percent(
                checkpoint.unit_done,
                checkpoint.unit_total,
            )
            task_run.current_object_json = self._current_object(checkpoint.current_object)
            diagnostics = self._diagnostics(
                phase=checkpoint.phase,
                unit_done=checkpoint.unit_done,
                unit_total=checkpoint.unit_total,
            )
            task_run.ingestion_diagnostics_json = diagnostics
            self._update_node(session, task_run=task_run, diagnostics=diagnostics)
            session.commit()

    def _require_active_task_run(self, session: Session) -> TaskRun:
        task_run = session.get(TaskRun, self.task_run_id)
        if task_run is None:
            raise RuntimeError("maintenance PLAN TaskRun does not exist")
        if task_run.cancel_requested_at is not None or task_run.status == "canceling":
            raise IngestionCanceledError("maintenance PLAN cancellation requested")
        if task_run.status != "running":
            raise RuntimeError("maintenance PLAN TaskRun is not running")
        return task_run

    @staticmethod
    def _validate_progress(*, unit_done: int, unit_total: int) -> None:
        if unit_total <= 0 or unit_done < 0 or unit_done > unit_total:
            raise ValueError("maintenance PLAN checkpoint progress is invalid")

    @staticmethod
    def _building_percent(unit_done: int, unit_total: int) -> int:
        return min(int(unit_done / unit_total * 100), 99)

    @staticmethod
    def _current_object(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: dict(raw)
            for key in ("entity", "time", "attributes")
            if isinstance((raw := value.get(key)), Mapping)
        }

    @staticmethod
    def _diagnostics(*, phase: str, unit_done: int, unit_total: int) -> dict[str, Any]:
        return {
            "maintenance_plan": {
                "phase": str(phase),
                "unit_done": unit_done,
                "unit_total": unit_total,
                "checkpointed_at": datetime.now(timezone.utc).isoformat(),
            }
        }

    @staticmethod
    def _update_node(
        session: Session,
        *,
        task_run: TaskRun,
        diagnostics: Mapping[str, Any],
    ) -> None:
        if task_run.current_node_id is None:
            return
        node = session.get(TaskRunNode, task_run.current_node_id)
        if node is None or node.task_run_id != task_run.id or node.status != "running":
            return
        node.ingestion_diagnostics_json = dict(diagnostics)

    @staticmethod
    def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
        payload = {
            key: value
            for key, value in snapshot.items()
            if key != "snapshot_integrity_hash"
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
