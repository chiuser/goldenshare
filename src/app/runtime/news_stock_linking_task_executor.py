from __future__ import annotations

from datetime import datetime
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.services.news_stock_linking_service import (
    NEWS_STOCK_LINKING_ACTION_KEY,
    NEWS_STOCK_RULE_VERSION,
    NewsStockLinkingService,
)


class NewsStockLinkingTaskExecutor:
    def __init__(self, *, session_factory) -> None:  # type: ignore[no-untyped-def]
        self._session_factory = session_factory

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
        payload = dict(unit.payload)
        window_end = _parse_datetime(payload.get("window_end"))
        window_start = _parse_optional_datetime(payload.get("window_start"))
        overlap_seconds = int(payload.get("overlap_seconds") or 0)
        rule_version = str(payload.get("rule_version") or NEWS_STOCK_RULE_VERSION)
        stats = NewsStockLinkingService(session_factory=self._session_factory).materialize(
            window_start=window_start,
            window_end=window_end,
            overlap_seconds=overlap_seconds,
            rule_version=rule_version,
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
                "rule_version": rule_version,
                "news_scope": payload.get("news_scope", "all"),
            },
        )

    @staticmethod
    def _freeze_payload(params: Mapping[str, Any]) -> dict[str, Any]:
        mode = str(params.get("mode") or "incremental").strip().lower()
        if mode not in {"full", "incremental"}:
            raise ValueError("news linking mode must be full or incremental")
        window_end = _parse_datetime(params.get("window_end"))
        raw_start = params.get("window_start")
        window_start = _parse_optional_datetime(raw_start)
        if mode == "full":
            window_start = None
        elif window_start is None:
            raise ValueError("incremental news linking requires window_start")
        if window_start is not None and window_start >= window_end:
            raise ValueError("news linking window_start must be before window_end")
        return {
            "mode": mode,
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat(),
            "overlap_seconds": max(int(params.get("overlap_seconds") or 0), 0),
            "rule_version": str(params.get("rule_version") or NEWS_STOCK_RULE_VERSION),
            "news_scope": str(params.get("news_scope") or "all"),
        }


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
