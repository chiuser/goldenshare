from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
    MaintenanceTaskRunContext,
)
from src.ops.services.news_stock_linking_service import (
    NEWS_STOCK_LINKING_ACTION_KEY,
    NEWS_STOCK_RULE_VERSION,
    BatchProgressSink,
    NewsStockLinkingStats,
    NewsStockLinkingService,
)


NEWS_STOCK_PROGRESS_MIN_INTERVAL_SECONDS = 3.0


logger = logging.getLogger(__name__)


class NewsStockLinkingTaskExecutor:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        progress_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._progress_clock = progress_clock

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        if request.action_key != NEWS_STOCK_LINKING_ACTION_KEY:
            raise ValueError(f"unsupported news linking action: {request.action_key}")
        payload = self._freeze_payload(request.params)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        plan_hash = hashlib.sha256(encoded).hexdigest()
        return MaintenanceExecutionPlan(
            plan_hash=plan_hash,
            units=(
                MaintenanceExecutionUnit(
                    unit_key=f"news-stock-links:{payload['window_end']}",
                    payload=payload,
                ),
            ),
            expected_rows=0,
            metadata={"action_key": NEWS_STOCK_LINKING_ACTION_KEY, "window": payload},
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        return self._execute_unit(unit, progress_sink=None)

    def execute_unit_for_task_run(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        context: MaintenanceTaskRunContext,
    ) -> MaintenanceExecutionResult:
        payload = dict(unit.payload)
        reporter = _NewsStockLinkingProgressReporter(
            context=context,
            payload=payload,
            clock=self._progress_clock,
        )
        try:
            return self._execute_unit(unit, progress_sink=reporter.observe)
        finally:
            reporter.flush()

    def _execute_unit(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        progress_sink: BatchProgressSink | None,
    ) -> MaintenanceExecutionResult:
        payload = dict(unit.payload)
        window_end = _parse_datetime(payload.get("window_end"))
        window_start = _parse_datetime(payload.get("window_start"))
        rule_version = str(payload.get("rule_version") or NEWS_STOCK_RULE_VERSION)
        stats = NewsStockLinkingService(session_factory=self._session_factory).materialize(
            window_start=window_start,
            window_end=window_end,
            rule_version=rule_version,
            progress_sink=progress_sink,
        )
        return MaintenanceExecutionResult(
            rows_fetched=stats.rows_fetched,
            rows_saved=stats.rows_saved,
            rows_rejected=0,
            summary_message=(
                f"新闻—个股关联物化完成：news={stats.rows_fetched} "
                f"links_inserted={stats.links_inserted} links_updated={stats.links_updated} "
                f"links_deleted={stats.links_deleted}"
            ),
            metadata={
                **stats.as_diagnostics(),
                "window_start": payload.get("window_start"),
                "window_end": payload.get("window_end"),
                "cursor_end": payload.get("cursor_end"),
                "task_frozen_at": payload.get("task_frozen_at"),
                "run_mode": payload.get("run_mode"),
                "window_field": "news_time",
                "rule_version": rule_version,
                "news_scope": payload.get("news_scope", "all"),
            },
        )

    @staticmethod
    def _freeze_payload(params: Mapping[str, Any]) -> dict[str, Any]:
        if params.get("mode") not in (None, "") or params.get("overlap_seconds") not in (None, ""):
            raise ValueError("legacy news linking mode/overlap payload is not supported")
        run_mode = str(params.get("run_mode") or "").strip()
        if run_mode not in {"manual_range", "scheduled_incremental"}:
            raise ValueError("news linking run_mode must be manual_range or scheduled_incremental")
        if str(params.get("window_field") or "").strip() != "news_time":
            raise ValueError("news linking window_field must be news_time")
        window_end = _parse_datetime(params.get("window_end"))
        window_start = _parse_datetime(params.get("window_start"))
        cursor_end = _parse_datetime(params.get("cursor_end"))
        task_frozen_at = _parse_datetime(params.get("task_frozen_at"))
        if window_start >= window_end:
            raise ValueError("news linking window_start must be before window_end")
        if cursor_end > window_end:
            raise ValueError("news linking cursor_end must not be after window_end")
        news_scope = str(params.get("news_scope") or "").strip()
        if news_scope != "all":
            raise ValueError("news linking news_scope must be all")
        return {
            "run_mode": run_mode,
            "window_field": "news_time",
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "cursor_end": cursor_end.isoformat(),
            "task_frozen_at": task_frozen_at.isoformat(),
            "rule_version": str(params.get("rule_version") or NEWS_STOCK_RULE_VERSION),
            "news_scope": news_scope,
        }


class _NewsStockLinkingProgressReporter:
    def __init__(
        self,
        *,
        context: MaintenanceTaskRunContext,
        payload: Mapping[str, Any],
        clock: Callable[[], float],
    ) -> None:
        self._context = context
        self._payload = dict(payload)
        self._clock = clock
        self._latest_stats: NewsStockLinkingStats | None = None
        self._last_write_at: float | None = None

    def observe(self, stats: NewsStockLinkingStats) -> None:
        self._latest_stats = stats
        now = self._clock()
        if (
            self._last_write_at is None
            or now - self._last_write_at >= NEWS_STOCK_PROGRESS_MIN_INTERVAL_SECONDS
        ):
            self._write(stats)
            self._last_write_at = now

    def flush(self) -> None:
        if self._latest_stats is None:
            return
        self._write(self._latest_stats)
        self._last_write_at = self._clock()

    def _write(self, stats: NewsStockLinkingStats) -> None:
        current_object = {
            "entity": {"kind": "enum", "name": "新闻—个股关联"},
            "time": {
                key: value
                for key, value in {
                    "start": self._payload.get("window_start"),
                    "end": self._payload.get("window_end"),
                    "field": "news_time",
                }.items()
                if value not in (None, "")
            },
            "attributes": {
                "enum_value": (
                    f"批次 {stats.batch_count}：已处理新闻 {stats.rows_fetched}，"
                    f"已生成关联 {stats.rows_saved}"
                )
            },
        }
        diagnostics = {
            **stats.as_diagnostics(),
            "window_start": self._payload.get("window_start"),
            "window_end": self._payload.get("window_end"),
            "cursor_end": self._payload.get("cursor_end"),
            "task_frozen_at": self._payload.get("task_frozen_at"),
            "run_mode": self._payload.get("run_mode"),
            "window_field": "news_time",
            "rule_version": self._payload.get("rule_version") or NEWS_STOCK_RULE_VERSION,
            "news_scope": self._payload.get("news_scope") or "all",
        }
        message = str(current_object["attributes"]["enum_value"])
        try:
            self._context.run_context.update_progress(
                run_id=self._context.task_run_id,
                unit_done=0,
                unit_failed=0,
                total=1,
                message=message,
                rows_fetched=stats.rows_fetched,
                rows_saved=stats.rows_saved,
                rows_rejected=0,
                rows_deduplicated=stats.rows_deduplicated,
                ingestion_diagnostics=diagnostics,
                rejected_reason_counts={},
                rejected_reason_samples={},
                current_object=current_object,
            )
        except Exception:
            logger.warning(
                "news stock linking TaskRun progress write failed for task_run_id=%s",
                self._context.task_run_id,
                exc_info=True,
            )


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_optional_datetime(value)
    if parsed is None:
        raise ValueError("news linking window_end must be an aware datetime")
    return parsed


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("news linking window datetimes must include a timezone")
    return parsed
