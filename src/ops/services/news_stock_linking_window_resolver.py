from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.models.core_serving_light.news import NewsLight
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.news_stock_linking_service import (
    NEWS_STOCK_LINKING_ACTION_KEY,
    NEWS_STOCK_RULE_VERSION,
)


NEWS_STOCK_LINKING_WINDOW_FIELD = "news_time"
NEWS_STOCK_LINKING_RUN_MODES = frozenset({"manual_range", "scheduled_incremental"})


class NewsStockLinkingWindowEmpty(RuntimeError):
    """The successful cursor already reaches the current frozen trigger time."""
SHANGHAI = ZoneInfo("Asia/Shanghai")


class NewsStockLinkingWindowResolver:
    def freeze_payload(
        self,
        session: Session,
        *,
        trigger_source: str,
        time_input: dict[str, Any],
        request_payload: dict[str, Any],
        task_frozen_at: datetime,
    ) -> dict[str, Any]:
        frozen_at = self._aware_utc(task_frozen_at, "task_frozen_at")
        source = str(trigger_source or "").strip().lower()
        if source == "manual":
            return self._freeze_manual(
                time_input=time_input,
                request_payload=request_payload,
                task_frozen_at=frozen_at,
            )
        if source == "scheduled":
            return self._freeze_scheduled(
                session,
                request_payload=request_payload,
                task_frozen_at=frozen_at,
            )
        if source == "retry":
            return self.validate_frozen_payload(request_payload)
        raise WebAppError(
            status_code=422,
            code="news_stock_linking.trigger_source_invalid",
            message="新闻关联任务只支持手动、自动或重试触发",
        )

    def validate_frozen_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_key = str(payload.get("target_key") or "").strip()
        if target_key != NEWS_STOCK_LINKING_ACTION_KEY:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message="新闻关联任务缺少正确的维护目标",
            )
        if payload.get("mode") not in (None, "") or payload.get("overlap_seconds") not in (None, ""):
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.legacy_payload_forbidden",
                message="旧版 full/incremental 新闻关联任务不能按新契约执行或重试",
            )
        run_mode = str(payload.get("run_mode") or "").strip()
        if run_mode not in NEWS_STOCK_LINKING_RUN_MODES:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message="新闻关联任务缺少有效的 run_mode",
            )
        if str(payload.get("window_field") or "").strip() != NEWS_STOCK_LINKING_WINDOW_FIELD:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message="新闻关联任务窗口字段必须是 news_time",
            )
        window_start = self._parse_aware(payload.get("window_start"), "window_start")
        window_end = self._parse_aware(payload.get("window_end"), "window_end")
        cursor_end = self._parse_aware(payload.get("cursor_end"), "cursor_end")
        self._parse_aware(payload.get("task_frozen_at"), "task_frozen_at")
        if window_start >= window_end:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message="新闻关联任务 window_start 必须早于 window_end",
            )
        if cursor_end > window_end:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message="新闻关联任务 cursor_end 不能晚于 window_end",
            )
        return dict(payload)

    def require_manual_baseline(self, session: Session) -> datetime:
        cursor = self._max_success_cursor(session, run_mode="scheduled_incremental")
        if cursor is None:
            cursor = self._max_success_cursor(session, run_mode="manual_range")
        if cursor is None:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.baseline_required",
                message="请先成功执行一次新闻关联自然日范围任务，再启用自动增量",
            )
        return cursor

    def window_has_news(self, session: Session, payload: dict[str, Any]) -> bool:
        validated = self.validate_frozen_payload(payload)
        window_start = self._parse_aware(validated["window_start"], "window_start")
        window_end = self._parse_aware(validated["window_end"], "window_end")
        return session.scalar(
            select(NewsLight.row_key_hash)
            .where(NewsLight.news_time >= window_start)
            .where(NewsLight.news_time < window_end)
            .limit(1)
        ) is not None

    def _freeze_manual(
        self,
        *,
        time_input: dict[str, Any],
        request_payload: dict[str, Any],
        task_frozen_at: datetime,
    ) -> dict[str, Any]:
        if str(time_input.get("mode") or "").strip() != "range":
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.time_range_required",
                message="新闻关联手动任务必须填写自然日开始和截止日期",
            )
        start_date = self._parse_date(time_input.get("start_date"), "start_date")
        end_date = self._parse_date(time_input.get("end_date"), "end_date")
        if start_date > end_date:
            raise WebAppError(status_code=422, code="validation_error", message="开始日期不能晚于结束日期")
        window_start = datetime.combine(start_date, time.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
        window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=SHANGHAI).astimezone(
            timezone.utc
        )
        cursor_end = min(window_end, task_frozen_at)
        return {
            **request_payload,
            "target_type": "maintenance_action",
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
            "run_mode": "manual_range",
            "window_field": NEWS_STOCK_LINKING_WINDOW_FIELD,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "cursor_end": cursor_end.isoformat(),
            "task_frozen_at": task_frozen_at.isoformat(),
            "rule_version": str(request_payload.get("rule_version") or NEWS_STOCK_RULE_VERSION),
            "news_scope": "all",
        }

    def _freeze_scheduled(
        self,
        session: Session,
        *,
        request_payload: dict[str, Any],
        task_frozen_at: datetime,
    ) -> dict[str, Any]:
        cursor = self.require_manual_baseline(session)
        if cursor >= task_frozen_at:
            raise NewsStockLinkingWindowEmpty("新闻关联自动增量当前没有可推进的时间窗口")
        return {
            **request_payload,
            "target_type": "maintenance_action",
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
            "run_mode": "scheduled_incremental",
            "window_field": NEWS_STOCK_LINKING_WINDOW_FIELD,
            "window_start": cursor.isoformat(),
            "window_end": task_frozen_at.isoformat(),
            "cursor_end": task_frozen_at.isoformat(),
            "task_frozen_at": task_frozen_at.isoformat(),
            "rule_version": str(request_payload.get("rule_version") or NEWS_STOCK_RULE_VERSION),
            "news_scope": "all",
        }

    def _max_success_cursor(self, session: Session, *, run_mode: str) -> datetime | None:
        cursors: list[datetime] = []
        payloads = session.scalars(
            select(TaskRun.request_payload_json)
            .where(TaskRun.task_type == "maintenance_action")
            .where(TaskRun.status == "success")
        )
        for raw_payload in payloads:
            if not isinstance(raw_payload, dict):
                continue
            if raw_payload.get("target_key") != NEWS_STOCK_LINKING_ACTION_KEY:
                continue
            if raw_payload.get("run_mode") != run_mode:
                continue
            if raw_payload.get("window_field") != NEWS_STOCK_LINKING_WINDOW_FIELD:
                continue
            cursors.append(self._parse_aware(raw_payload.get("cursor_end"), "cursor_end"))
        return max(cursors) if cursors else None

    @staticmethod
    def _parse_date(value: Any, field_name: str) -> date:
        if value in (None, ""):
            raise WebAppError(status_code=422, code="validation_error", message=f"{field_name} 不能为空")
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"{field_name} 必须是 YYYY-MM-DD",
            ) from exc

    @classmethod
    def _parse_aware(cls, value: Any, field_name: str) -> datetime:
        if value in (None, ""):
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message=f"新闻关联任务缺少 {field_name}",
            )
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message=f"新闻关联任务 {field_name} 无法解析",
            ) from exc
        return cls._aware_utc(parsed, field_name)

    @staticmethod
    def _aware_utc(value: datetime, field_name: str) -> datetime:
        if value.tzinfo is None:
            raise WebAppError(
                status_code=422,
                code="news_stock_linking.payload_invalid",
                message=f"新闻关联任务 {field_name} 必须包含时区",
            )
        return value.astimezone(timezone.utc)
