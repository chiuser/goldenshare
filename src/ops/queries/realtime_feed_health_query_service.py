from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.realtime import (
    RealtimeMarketClock,
    RealtimeStateStore,
    RealtimeStateStoreUnavailable,
    get_realtime_stock_rt_daily_config,
)
from src.ops.schemas.realtime import OpsRealtimeStockRtDailyHealthResponse


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
OPS_HEALTH_POLL_INTERVAL_SECONDS = 60


class RealtimeFeedHealthQueryService:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))

    def build_stock_rt_daily_health(self, session: Session) -> OpsRealtimeStockRtDailyHealthResponse:
        config = get_realtime_stock_rt_daily_config()
        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock = RealtimeMarketClock().resolve(
            session,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            now=now,
        )
        enabled = config.enabled
        collection_status = "disabled" if not enabled else clock.collection_status
        page_polling_enabled = enabled and collection_status == "open"
        base_payload = {
            "feed_key": config.feed_key,
            "display_name": config.display_name,
            "enabled": enabled,
            "max_calls_per_minute": config.max_calls_per_minute,
            "poll_interval_seconds": config.poll_interval_seconds,
            "is_trading_day": clock.is_trading_day,
            "collection_sessions": list(clock.collection_sessions),
            "collection_status": collection_status,
            "stale_after_seconds": config.stale_after_seconds,
            "snapshot_ttl_seconds": config.storage.snapshot_ttl_seconds,
            "keep_recent_batches": config.storage.keep_recent_batches,
            "batch_stream_maxlen": config.storage.batch_stream_maxlen,
            "delta_stream_maxlen": config.storage.delta_stream_maxlen,
            "page_polling_enabled": page_polling_enabled,
            "recommended_poll_interval_seconds": OPS_HEALTH_POLL_INTERVAL_SECONDS,
        }

        try:
            redis_connected = self._store.ping()
            health = self._store.get_health(config.feed_key) or {}
            batch_id = self._store.get_current_batch_id(config.feed_key)
            meta = self._store.get_batch_meta(config.feed_key, batch_id) if batch_id else None
            snapshot_count = self._store.get_batch_snapshot_count(config.feed_key, batch_id) if batch_id else 0
        except RealtimeStateStoreUnavailable as exc:
            return OpsRealtimeStockRtDailyHealthResponse(
                **base_payload,
                status="unavailable",
                redis_connected=False,
                collector_running=False,
                last_error_message=str(exc),
                snapshot_count=0,
                source_row_count=0,
                request_count_last_minute=0,
                delta_count_last_batch=0,
            )

        meta = meta or {}
        current_batch_age_seconds = _age_seconds(meta.get("published_at"), now)
        status = _resolve_status(
            enabled=enabled,
            collection_status=collection_status,
            has_current_batch=bool(batch_id and meta),
            current_batch_age_seconds=current_batch_age_seconds,
            stale_after_seconds=config.stale_after_seconds,
            stored_status=_string_or_none(health.get("status")),
        )
        return OpsRealtimeStockRtDailyHealthResponse(
            **base_payload,
            status=status,
            redis_connected=redis_connected,
            collector_running=bool(health.get("collector_running") or health.get("collector_id")),
            collector_id=_string_or_none(health.get("collector_id")),
            last_request_at=_string_or_none(health.get("last_request_at")),
            last_success_at=_string_or_none(health.get("last_success_at") or meta.get("published_at")),
            last_error_at=_string_or_none(health.get("last_error_at")),
            last_error_message=_string_or_none(health.get("last_error_message")),
            current_batch_id=batch_id,
            current_batch_age_seconds=current_batch_age_seconds,
            current_batch_received_at=_string_or_none(meta.get("received_at")),
            current_batch_published_at=_string_or_none(meta.get("published_at")),
            snapshot_count=snapshot_count,
            source_row_count=_int_value(meta.get("source_row_count"), default=snapshot_count),
            source_elapsed_ms=_float_or_none(meta.get("source_elapsed_ms")),
            write_elapsed_ms=_float_or_none(meta.get("write_elapsed_ms")),
            request_count_last_minute=_int_value(health.get("request_count_last_minute"), default=0),
            last_batch_event_id=_string_or_none(health.get("last_batch_event_id")),
            last_delta_event_id=_string_or_none(health.get("last_delta_event_id")),
            delta_count_last_batch=_int_value(health.get("delta_count_last_batch"), default=0),
        )


def _resolve_status(
    *,
    enabled: bool,
    collection_status: str,
    has_current_batch: bool,
    current_batch_age_seconds: float | None,
    stale_after_seconds: int,
    stored_status: str | None,
) -> str:
    if not enabled:
        return "idle"
    if stored_status == "degraded":
        return "degraded"
    if not has_current_batch:
        return "unavailable" if collection_status == "open" else "idle"
    if collection_status == "open" and current_batch_age_seconds is not None and current_batch_age_seconds > stale_after_seconds:
        return "stale"
    if collection_status == "open":
        return "ok"
    return "idle"


def _age_seconds(raw_value: object, now: datetime) -> float | None:
    if raw_value is None:
        return None
    try:
        published_at = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - published_at.astimezone(CN_TIMEZONE)).total_seconds())


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _int_value(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
