from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.dao.etf_series_active_dao import EtfSeriesActiveDAO
from src.foundation.realtime import (
    STOCK_RT_MIN_ALLOWED_FREQS,
    RealtimeMarketClock,
    RealtimeStateStore,
    RealtimeStateStoreUnavailable,
    get_realtime_etf_rt_daily_config,
    get_realtime_stock_rt_daily_config,
    get_realtime_stock_rt_min_config,
    normalize_stock_rt_min_freq,
)
from src.ops.schemas.realtime import (
    OpsRealtimeEtfRtDailyHealthResponse,
    OpsRealtimeStockRtDailyHealthResponse,
    OpsRealtimeStockRtMinHealthItem,
    OpsRealtimeStockRtMinHealthResponse,
)


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
OPS_HEALTH_POLL_INTERVAL_SECONDS = 60


class RealtimeFeedHealthValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        config = get_realtime_stock_rt_daily_config(session)
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

    def build_etf_rt_daily_health(self, session: Session) -> OpsRealtimeEtfRtDailyHealthResponse:
        config = get_realtime_etf_rt_daily_config(session)
        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock = RealtimeMarketClock().resolve(
            session,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            now=now,
        )
        active_codes = EtfSeriesActiveDAO(session).list_active_codes("etf_rt_daily")
        enabled = config.enabled
        collection_status = "disabled" if not enabled else clock.collection_status
        page_polling_enabled = enabled and collection_status == "open"
        base_payload = {
            "feed_key": config.feed_key,
            "display_name": config.display_name,
            "enabled": enabled,
            "active_pool_count": len(active_codes),
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
            active_snapshot_count = len(self._store.get_snapshots(config.feed_key, batch_id, active_codes)) if batch_id and active_codes else 0
        except RealtimeStateStoreUnavailable as exc:
            return OpsRealtimeEtfRtDailyHealthResponse(
                **base_payload,
                status="unavailable",
                redis_connected=False,
                collector_running=False,
                last_error_message=str(exc),
                source_snapshot_count=0,
                active_snapshot_count=0,
                snapshot_count=0,
                source_row_count=0,
                request_count_last_minute=0,
                delta_count_last_batch=0,
                invalid_count=0,
                invalid_reason_counts={},
                segment_counts={},
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
        return OpsRealtimeEtfRtDailyHealthResponse(
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
            source_snapshot_count=snapshot_count,
            active_snapshot_count=active_snapshot_count,
            snapshot_count=snapshot_count,
            source_row_count=_int_value(meta.get("source_row_count"), default=snapshot_count),
            source_elapsed_ms=_float_or_none(meta.get("source_elapsed_ms")),
            write_elapsed_ms=_float_or_none(meta.get("write_elapsed_ms")),
            request_count_last_minute=_int_value(health.get("request_count_last_minute"), default=0),
            last_batch_event_id=_string_or_none(health.get("last_batch_event_id")),
            last_delta_event_id=_string_or_none(health.get("last_delta_event_id")),
            delta_count_last_batch=_int_value(health.get("delta_count_last_batch"), default=0),
            invalid_count=_int_value(health.get("invalid_count", meta.get("invalid_count")), default=0),
            invalid_reason_counts=_dict_int_values(health.get("invalid_reason_counts") or meta.get("invalid_reason_counts")),
            segment_counts=_dict_int_values(health.get("segment_counts") or meta.get("segment_counts")),
        )

    def build_stock_rt_min_health(self, session: Session, *, freq: str | None = None) -> OpsRealtimeStockRtMinHealthResponse:
        config = get_realtime_stock_rt_min_config(session)
        requested_freqs = _requested_min_freqs(freq)
        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock = RealtimeMarketClock().resolve(
            session,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            now=now,
        )
        page_polling_enabled = config.enabled and clock.collection_status == "open" and bool(
            set(requested_freqs).intersection(config.enabled_freqs)
        )
        try:
            redis_connected = self._store.ping()
        except RealtimeStateStoreUnavailable as exc:
            items = [
                _build_unavailable_min_item(
                    freq=item_freq,
                    feed_key=config.feed_key_for_freq(item_freq),
                    enabled=config.enabled and item_freq in config.enabled_freqs,
                    redis_message=str(exc),
                    redis_connected=False,
                    collection_status="disabled" if not (config.enabled and item_freq in config.enabled_freqs) else clock.collection_status,
                    is_trading_day=clock.is_trading_day,
                    collection_sessions=list(clock.collection_sessions),
                    max_calls_per_minute=config.max_calls_per_minute,
                    poll_interval_seconds=config.poll_interval_seconds,
                    stale_after_seconds=config.stale_after_seconds,
                    snapshot_ttl_seconds=config.storage.snapshot_ttl_seconds,
                    keep_recent_batches=config.storage.keep_recent_batches,
                    batch_stream_maxlen=config.storage.batch_stream_maxlen,
                    delta_stream_maxlen=config.storage.delta_stream_maxlen,
                )
                for item_freq in requested_freqs
            ]
            return OpsRealtimeStockRtMinHealthResponse(
                display_name=config.display_name,
                status=_aggregate_status([item.status for item in items]),
                enabled=config.enabled,
                configured_freqs=list(config.enabled_freqs),
                supported_freqs=list(STOCK_RT_MIN_ALLOWED_FREQS),
                page_polling_enabled=page_polling_enabled,
                recommended_poll_interval_seconds=OPS_HEALTH_POLL_INTERVAL_SECONDS,
                items=items,
            )

        items = []
        for item_freq in requested_freqs:
            item_enabled = config.enabled and item_freq in config.enabled_freqs
            collection_status = "disabled" if not item_enabled else clock.collection_status
            feed_key = config.feed_key_for_freq(item_freq)
            if not item_enabled:
                items.append(
                    _build_disabled_min_item(
                        freq=item_freq,
                        feed_key=feed_key,
                        redis_connected=redis_connected,
                        collection_status=collection_status,
                        is_trading_day=clock.is_trading_day,
                        collection_sessions=list(clock.collection_sessions),
                        max_calls_per_minute=config.max_calls_per_minute,
                        poll_interval_seconds=config.poll_interval_seconds,
                        stale_after_seconds=config.stale_after_seconds,
                        snapshot_ttl_seconds=config.storage.snapshot_ttl_seconds,
                        keep_recent_batches=config.storage.keep_recent_batches,
                        batch_stream_maxlen=config.storage.batch_stream_maxlen,
                        delta_stream_maxlen=config.storage.delta_stream_maxlen,
                    )
                )
                continue
            items.append(
                self._build_enabled_stock_rt_min_item(
                    freq=item_freq,
                    feed_key=feed_key,
                    redis_connected=redis_connected,
                    collection_status=collection_status,
                    is_trading_day=clock.is_trading_day,
                    collection_sessions=list(clock.collection_sessions),
                    max_calls_per_minute=config.max_calls_per_minute,
                    poll_interval_seconds=config.poll_interval_seconds,
                    stale_after_seconds=config.stale_after_seconds,
                    snapshot_ttl_seconds=config.storage.snapshot_ttl_seconds,
                    keep_recent_batches=config.storage.keep_recent_batches,
                    batch_stream_maxlen=config.storage.batch_stream_maxlen,
                    delta_stream_maxlen=config.storage.delta_stream_maxlen,
                    now=now,
                )
            )
        return OpsRealtimeStockRtMinHealthResponse(
            display_name=config.display_name,
            status=_aggregate_status([item.status for item in items]),
            enabled=config.enabled,
            configured_freqs=list(config.enabled_freqs),
            supported_freqs=list(STOCK_RT_MIN_ALLOWED_FREQS),
            page_polling_enabled=page_polling_enabled,
            recommended_poll_interval_seconds=OPS_HEALTH_POLL_INTERVAL_SECONDS,
            items=items,
        )

    def _build_enabled_stock_rt_min_item(
        self,
        *,
        freq: str,
        feed_key: str,
        redis_connected: bool,
        collection_status: str,
        is_trading_day: bool,
        collection_sessions: list[str],
        max_calls_per_minute: int,
        poll_interval_seconds: int,
        stale_after_seconds: int,
        snapshot_ttl_seconds: int,
        keep_recent_batches: int,
        batch_stream_maxlen: int,
        delta_stream_maxlen: int,
        now: datetime,
    ) -> OpsRealtimeStockRtMinHealthItem:
        try:
            health = self._store.get_health(feed_key) or {}
            batch_id = self._store.get_current_batch_id(feed_key)
            meta = self._store.get_batch_meta(feed_key, batch_id) if batch_id else None
            snapshot_count = self._store.get_batch_snapshot_count(feed_key, batch_id) if batch_id else 0
        except RealtimeStateStoreUnavailable as exc:
            return _build_unavailable_min_item(
                freq=freq,
                feed_key=feed_key,
                enabled=True,
                redis_message=str(exc),
                redis_connected=False,
                collection_status=collection_status,
                is_trading_day=is_trading_day,
                collection_sessions=collection_sessions,
                max_calls_per_minute=max_calls_per_minute,
                poll_interval_seconds=poll_interval_seconds,
                stale_after_seconds=stale_after_seconds,
                snapshot_ttl_seconds=snapshot_ttl_seconds,
                keep_recent_batches=keep_recent_batches,
                batch_stream_maxlen=batch_stream_maxlen,
                delta_stream_maxlen=delta_stream_maxlen,
            )

        meta = meta or {}
        current_batch_age_seconds = _age_seconds(meta.get("published_at"), now)
        status = _resolve_status(
            enabled=True,
            collection_status=collection_status,
            has_current_batch=bool(batch_id and meta),
            current_batch_age_seconds=current_batch_age_seconds,
            stale_after_seconds=stale_after_seconds,
            stored_status=_string_or_none(health.get("status")),
        )
        return OpsRealtimeStockRtMinHealthItem(
            freq=freq,
            feed_key=feed_key,
            status=status,
            enabled=True,
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
            max_calls_per_minute=max_calls_per_minute,
            poll_interval_seconds=poll_interval_seconds,
            is_trading_day=is_trading_day,
            collection_sessions=collection_sessions,
            collection_status=collection_status,
            stale_after_seconds=stale_after_seconds,
            snapshot_ttl_seconds=snapshot_ttl_seconds,
            keep_recent_batches=keep_recent_batches,
            batch_stream_maxlen=batch_stream_maxlen,
            delta_stream_maxlen=delta_stream_maxlen,
            last_batch_event_id=_string_or_none(health.get("last_batch_event_id")),
            last_delta_event_id=_string_or_none(health.get("last_delta_event_id")),
            delta_count_last_batch=_int_value(health.get("delta_count_last_batch"), default=0),
            invalid_count=_int_value(health.get("invalid_count", meta.get("invalid_count")), default=0),
            invalid_reason_counts=_dict_int_values(health.get("invalid_reason_counts") or meta.get("invalid_reason_counts")),
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


def _requested_min_freqs(freq: str | None) -> tuple[str, ...]:
    if freq is None or not str(freq).strip():
        return STOCK_RT_MIN_ALLOWED_FREQS
    try:
        return (normalize_stock_rt_min_freq(freq),)
    except ValueError as exc:
        raise RealtimeFeedHealthValidationError("INVALID_FREQ", "实时分钟频率无效") from exc


def _build_disabled_min_item(
    *,
    freq: str,
    feed_key: str,
    redis_connected: bool,
    collection_status: str,
    is_trading_day: bool,
    collection_sessions: list[str],
    max_calls_per_minute: int,
    poll_interval_seconds: int,
    stale_after_seconds: int,
    snapshot_ttl_seconds: int,
    keep_recent_batches: int,
    batch_stream_maxlen: int,
    delta_stream_maxlen: int,
) -> OpsRealtimeStockRtMinHealthItem:
    return OpsRealtimeStockRtMinHealthItem(
        freq=freq,
        feed_key=feed_key,
        status="idle",
        enabled=False,
        redis_connected=redis_connected,
        collector_running=False,
        snapshot_count=0,
        source_row_count=0,
        request_count_last_minute=0,
        max_calls_per_minute=max_calls_per_minute,
        poll_interval_seconds=poll_interval_seconds,
        is_trading_day=is_trading_day,
        collection_sessions=collection_sessions,
        collection_status=collection_status,
        stale_after_seconds=stale_after_seconds,
        snapshot_ttl_seconds=snapshot_ttl_seconds,
        keep_recent_batches=keep_recent_batches,
        batch_stream_maxlen=batch_stream_maxlen,
        delta_stream_maxlen=delta_stream_maxlen,
        delta_count_last_batch=0,
        invalid_count=0,
        invalid_reason_counts={},
    )


def _build_unavailable_min_item(
    *,
    freq: str,
    feed_key: str,
    enabled: bool,
    redis_message: str,
    redis_connected: bool,
    collection_status: str,
    is_trading_day: bool,
    collection_sessions: list[str],
    max_calls_per_minute: int,
    poll_interval_seconds: int,
    stale_after_seconds: int,
    snapshot_ttl_seconds: int,
    keep_recent_batches: int,
    batch_stream_maxlen: int,
    delta_stream_maxlen: int,
) -> OpsRealtimeStockRtMinHealthItem:
    if not enabled:
        return _build_disabled_min_item(
            freq=freq,
            feed_key=feed_key,
            redis_connected=redis_connected,
            collection_status=collection_status,
            is_trading_day=is_trading_day,
            collection_sessions=collection_sessions,
            max_calls_per_minute=max_calls_per_minute,
            poll_interval_seconds=poll_interval_seconds,
            stale_after_seconds=stale_after_seconds,
            snapshot_ttl_seconds=snapshot_ttl_seconds,
            keep_recent_batches=keep_recent_batches,
            batch_stream_maxlen=batch_stream_maxlen,
            delta_stream_maxlen=delta_stream_maxlen,
        )
    return OpsRealtimeStockRtMinHealthItem(
        freq=freq,
        feed_key=feed_key,
        status="unavailable",
        enabled=True,
        redis_connected=redis_connected,
        collector_running=False,
        last_error_message=redis_message,
        snapshot_count=0,
        source_row_count=0,
        request_count_last_minute=0,
        max_calls_per_minute=max_calls_per_minute,
        poll_interval_seconds=poll_interval_seconds,
        is_trading_day=is_trading_day,
        collection_sessions=collection_sessions,
        collection_status=collection_status,
        stale_after_seconds=stale_after_seconds,
        snapshot_ttl_seconds=snapshot_ttl_seconds,
        keep_recent_batches=keep_recent_batches,
        batch_stream_maxlen=batch_stream_maxlen,
        delta_stream_maxlen=delta_stream_maxlen,
        delta_count_last_batch=0,
        invalid_count=0,
        invalid_reason_counts={},
    )


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "idle"
    for candidate in ("unavailable", "degraded", "stale", "ok"):
        if candidate in statuses:
            return candidate
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


def _dict_int_values(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    results: dict[str, int] = {}
    for key, raw_count in value.items():
        results[str(key)] = _int_value(raw_count, default=0)
    return results
