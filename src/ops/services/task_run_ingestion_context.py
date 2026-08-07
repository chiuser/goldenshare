from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.ingestion_run_context import IngestionRunContext
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode


class TaskRunIngestionContext(IngestionRunContext):
    """Ops 侧进度适配：数据维护执行器只更新 TaskRun 当前快照。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def is_cancel_requested(self, *, run_id: int) -> bool:
        cancel_requested_at = self.session.execute(
            select(TaskRun.cancel_requested_at).where(TaskRun.id == run_id)
        ).scalar_one_or_none()
        return isinstance(cancel_requested_at, datetime)

    def update_progress(
        self,
        *,
        run_id: int,
        current: int,
        total: int,
        message: str,
        rows_fetched: int | None = None,
        rows_saved: int | None = None,
        rows_rejected: int | None = None,
        rows_deduplicated: int | None = None,
        ingestion_diagnostics: dict[str, Any] | None = None,
        rejected_reason_counts: dict[str, int] | None = None,
        rejected_reason_samples: dict[str, list[dict[str, Any]]] | None = None,
        current_object: dict[str, Any] | None = None,
    ) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return
        progress_session = Session(bind=bind, autoflush=False, autocommit=False, future=True)
        try:
            task_run = progress_session.get(TaskRun, run_id)
            if task_run is None:
                return
            task_run.unit_done = max(int(current), 0)
            task_run.unit_total = max(int(total), 0)
            task_run.progress_percent = int((current / total) * 100) if total else None
            task_run.rows_fetched = int(rows_fetched if rows_fetched is not None else task_run.rows_fetched or 0)
            task_run.rows_saved = int(rows_saved if rows_saved is not None else task_run.rows_saved or 0)
            task_run.rows_rejected = int(rows_rejected if rows_rejected is not None else task_run.rows_rejected or 0)
            task_run.rows_deduplicated = int(
                rows_deduplicated if rows_deduplicated is not None else task_run.rows_deduplicated or 0
            )
            task_run.ingestion_diagnostics_json = self._sanitize_ingestion_diagnostics(ingestion_diagnostics)
            task_run.rejected_reason_counts_json = self._sanitize_reason_counts(rejected_reason_counts)
            task_run.rejected_reason_samples_json = self._sanitize_reason_samples(rejected_reason_samples)
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
        node.rows_deduplicated = task_run.rows_deduplicated
        node.ingestion_diagnostics_json = dict(task_run.ingestion_diagnostics_json or {})
        node.rejected_reason_counts_json = dict(task_run.rejected_reason_counts_json or {})
        node.rejected_reason_samples_json = dict(task_run.rejected_reason_samples_json or {})

    @staticmethod
    def _sanitize_reason_counts(value: dict[str, int] | None) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, int] = {}
        for raw_key, raw_count in value.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            normalized[key] = normalized.get(key, 0) + count
        return normalized

    @staticmethod
    def _sanitize_reason_samples(value: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, list[dict[str, Any]]] = {}
        for raw_key, raw_samples in value.items():
            key = str(raw_key or "").strip()
            if not key or not isinstance(raw_samples, list):
                continue
            bucket: list[dict[str, Any]] = []
            for sample in raw_samples:
                if len(bucket) >= 3:
                    break
                if isinstance(sample, dict):
                    bucket.append(dict(sample))
            if bucket:
                normalized[key] = bucket
        return normalized

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

    @staticmethod
    def _sanitize_ingestion_diagnostics(value: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        try:
            normalized = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return {"truncated": True, "reason": "not_json_serializable"}
        if not isinstance(normalized, dict):
            return {}
        source = normalized.get("source")
        pagination = source.get("pagination") if isinstance(source, dict) else None
        if isinstance(pagination, dict) and isinstance(pagination.get("unit_samples"), list):
            original_samples = list(pagination["unit_samples"])
            pagination["unit_samples"] = original_samples[:3]
            if len(original_samples) > 3:
                pagination["truncated"] = True
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= 16 * 1024:
            return normalized
        if isinstance(pagination, dict):
            pagination["unit_samples"] = []
            pagination["truncated"] = True
        normalized["truncated"] = True
        normalized["original_bytes"] = len(encoded)
        compact = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(compact) <= 16 * 1024:
            return normalized
        persistence = normalized.get("persistence")
        immutable_fact = persistence.get("immutable_fact") if isinstance(persistence, dict) else None
        return {
            "truncated": True,
            "original_bytes": len(encoded),
            "source": {"pagination": pagination if isinstance(pagination, dict) else {}},
            "persistence": {
                "immutable_fact": immutable_fact if isinstance(immutable_fact, dict) else {},
            },
        }
