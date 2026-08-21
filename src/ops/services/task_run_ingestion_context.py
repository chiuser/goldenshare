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

    MAX_INGESTION_DIAGNOSTICS_BYTES = 16 * 1024
    MAX_PAGED_UNIT_RESULTS = 16
    PAGED_UNIT_PHASES = {
        "processing_page",
        "reconciling",
        "publishing",
        "failed",
        "canceled",
    }

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
        unit_done: int,
        unit_failed: int,
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
            committed_units = max(int(unit_done), 0)
            failed_units = max(int(unit_failed), 0)
            total_units = max(int(total), 0)
            handled_units = committed_units + failed_units
            task_run.unit_done = committed_units
            task_run.unit_failed = failed_units
            task_run.unit_total = total_units
            task_run.progress_percent = min(int((handled_units / total_units) * 100), 100) if total_units else None
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

    @classmethod
    def _sanitize_ingestion_diagnostics(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        try:
            normalized = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return {"truncated": True, "reason": "not_json_serializable"}
        if not isinstance(normalized, dict):
            return {}
        cls._sanitize_paged_unit_runtime(normalized)
        source = normalized.get("source")
        pagination = source.get("pagination") if isinstance(source, dict) else None
        if isinstance(pagination, dict) and isinstance(pagination.get("unit_samples"), list):
            original_samples = list(pagination["unit_samples"])
            pagination["unit_samples"] = original_samples[:3]
            if len(original_samples) > 3:
                pagination["truncated"] = True
        encoded = json.dumps(
            normalized, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) <= cls.MAX_INGESTION_DIAGNOSTICS_BYTES:
            return normalized
        if isinstance(pagination, dict):
            pagination["unit_samples"] = []
            pagination["truncated"] = True
        normalized["truncated"] = True
        normalized["original_bytes"] = len(encoded)
        compact = json.dumps(
            normalized, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(compact) <= cls.MAX_INGESTION_DIAGNOSTICS_BYTES:
            return normalized
        persistence = normalized.get("persistence")
        immutable_fact = (
            persistence.get("immutable_fact") if isinstance(persistence, dict) else None
        )
        runtime = normalized.get("runtime")
        paged_unit = runtime.get("paged_unit") if isinstance(runtime, dict) else None
        fallback = {
            "truncated": True,
            "original_bytes": len(encoded),
            "source": {"pagination": cls._compact_pagination(pagination)},
            "persistence": {
                "immutable_fact": cls._compact_immutable_fact(immutable_fact),
            },
        }
        if isinstance(paged_unit, dict):
            fallback["runtime"] = {"paged_unit": paged_unit}
        return fallback

    @classmethod
    def _sanitize_paged_unit_runtime(cls, diagnostics: dict[str, Any]) -> None:
        runtime = diagnostics.get("runtime")
        if not isinstance(runtime, dict):
            return
        paged_unit = runtime.get("paged_unit")
        if not isinstance(paged_unit, dict):
            runtime.pop("paged_unit", None)
            return
        active = cls._sanitize_paged_unit_active(paged_unit.get("active"))
        raw_completed = paged_unit.get("completed")
        completed: list[dict[str, Any]] = []
        completed_truncated = bool(paged_unit.get("completed_truncated"))
        if isinstance(raw_completed, list):
            completed_truncated = (
                completed_truncated or len(raw_completed) > cls.MAX_PAGED_UNIT_RESULTS
            )
            for item in raw_completed[: cls.MAX_PAGED_UNIT_RESULTS]:
                sanitized = cls._sanitize_paged_unit_result(item)
                if sanitized is not None:
                    completed.append(sanitized)
        runtime["paged_unit"] = {
            "active": active,
            "completed": completed,
            "completed_truncated": completed_truncated,
        }

    @classmethod
    def _sanitize_paged_unit_active(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        phase = cls._bounded_text(value.get("phase"), max_length=32)
        if phase not in cls.PAGED_UNIT_PHASES:
            return None
        unit_id = cls._bounded_text(value.get("unit_id"), max_length=256)
        if not unit_id:
            return None
        return {
            "unit_id": unit_id,
            "unit_index": cls._nonnegative_int(value.get("unit_index")),
            "unit_total": cls._nonnegative_int(value.get("unit_total")),
            "time": cls._sanitize_paged_unit_time(value.get("time")),
            "phase": phase,
            "current_page_number": cls._optional_nonnegative_int(
                value.get("current_page_number")
            ),
            "completed_page_count": cls._nonnegative_int(
                value.get("completed_page_count")
            ),
            "page_limit": cls._optional_nonnegative_int(value.get("page_limit")),
            "unit_rows_fetched": cls._nonnegative_int(value.get("unit_rows_fetched")),
            "unit_rows_normalized_before_dedupe": cls._nonnegative_int(
                value.get("unit_rows_normalized_before_dedupe")
            ),
            "unit_rows_staged_unique": cls._nonnegative_int(
                value.get("unit_rows_staged_unique")
            ),
            "unit_rows_deduplicated": cls._nonnegative_int(
                value.get("unit_rows_deduplicated")
            ),
            "unit_rows_rejected": cls._nonnegative_int(value.get("unit_rows_rejected")),
            "retry_count": cls._nonnegative_int(value.get("retry_count")),
            "observed_short_page": bool(value.get("observed_short_page")),
            "terminal_page_rows": cls._optional_nonnegative_int(
                value.get("terminal_page_rows")
            ),
        }

    @classmethod
    def _sanitize_paged_unit_result(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        unit_id = cls._bounded_text(value.get("unit_id"), max_length=256)
        if not unit_id:
            return None
        return {
            "unit_id": unit_id,
            "unit_index": cls._nonnegative_int(value.get("unit_index")),
            "time": cls._sanitize_paged_unit_time(value.get("time")),
            "page_count": cls._nonnegative_int(value.get("page_count")),
            "retry_count": cls._nonnegative_int(value.get("retry_count")),
            "terminal_page_rows": cls._nonnegative_int(value.get("terminal_page_rows")),
            "observed_short_page": bool(value.get("observed_short_page")),
            "rows_fetched": cls._nonnegative_int(value.get("rows_fetched")),
            "rows_normalized_before_dedupe": cls._nonnegative_int(
                value.get("rows_normalized_before_dedupe")
            ),
            "rows_staged_unique": cls._nonnegative_int(value.get("rows_staged_unique")),
            "rows_deduplicated": cls._nonnegative_int(value.get("rows_deduplicated")),
            "rows_rejected": cls._nonnegative_int(value.get("rows_rejected")),
            "rows_inserted_new": cls._nonnegative_int(value.get("rows_inserted_new")),
            "rows_matched_existing": cls._nonnegative_int(
                value.get("rows_matched_existing")
            ),
            "rows_committed": cls._nonnegative_int(value.get("rows_committed")),
            "final_scope_count": cls._nonnegative_int(value.get("final_scope_count")),
        }

    @classmethod
    def _sanitize_paged_unit_time(cls, value: Any) -> dict[str, str | None]:
        record = value if isinstance(value, dict) else {}
        return {
            "field": cls._bounded_text(record.get("field"), max_length=64),
            "point": cls._bounded_text(record.get("point"), max_length=64),
        }

    @staticmethod
    def _bounded_text(value: Any, *, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:max_length] if text else None

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError, OverflowError):
            return 0

    @classmethod
    def _optional_nonnegative_int(cls, value: Any) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return normalized if normalized >= 0 else None

    @classmethod
    def _compact_pagination(cls, value: Any) -> dict[str, Any]:
        record = value if isinstance(value, dict) else {}
        return {
            "unit_count_with_pagination": cls._nonnegative_int(
                record.get("unit_count_with_pagination")
            ),
            "total_page_count": cls._nonnegative_int(record.get("total_page_count")),
            "total_retry_count": cls._nonnegative_int(record.get("total_retry_count")),
            "total_rows_merged": cls._nonnegative_int(record.get("total_rows_merged")),
            "multi_page_unit_count": cls._nonnegative_int(
                record.get("multi_page_unit_count")
            ),
            "max_pages_per_unit": cls._nonnegative_int(
                record.get("max_pages_per_unit")
            ),
            "short_page_unit_count": cls._nonnegative_int(
                record.get("short_page_unit_count")
            ),
            "unit_samples": [],
            "truncated": True,
        }

    @classmethod
    def _compact_immutable_fact(cls, value: Any) -> dict[str, int]:
        record = value if isinstance(value, dict) else {}
        keys = (
            "rows_normalized_before_dedupe",
            "rows_inserted_new",
            "rows_matched_existing",
            "scope_existing_count",
            "scope_source_unique_count",
            "final_scope_count",
        )
        return {
            key: cls._nonnegative_int(record.get(key)) for key in keys if key in record
        }
