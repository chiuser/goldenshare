from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from src.foundation.config.settings import Settings, get_settings
from src.foundation.realtime.constants import (
    STOCK_RT_DAILY_DISPLAY_NAME,
    STOCK_RT_DAILY_FEED_KEY,
    STOCK_RT_DAILY_SOURCE_API_NAME,
    STOCK_RT_MIN_DISPLAY_NAME,
    STOCK_RT_MIN_SOURCE_API_NAME,
)


STOCK_RT_MIN_ALLOWED_FREQS = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")


@dataclass(frozen=True, slots=True)
class RealtimeFeedStorageConfig:
    snapshot_ttl_seconds: int
    keep_recent_batches: int
    batch_stream_maxlen: int
    delta_stream_maxlen: int


@dataclass(frozen=True, slots=True)
class RealtimeStockRtDailyConfig:
    feed_key: str
    display_name: str
    source_api_name: str
    exchange: str
    enabled: bool
    poll_interval_seconds: int
    collection_sessions: str
    max_calls_per_minute: int
    lease_ttl_seconds: int
    stale_after_seconds: int
    storage: RealtimeFeedStorageConfig
    ts_code_pattern: str


@dataclass(frozen=True, slots=True)
class RealtimeStockRtMinConfig:
    display_name: str
    source_api_name: str
    exchange: str
    enabled: bool
    enabled_freqs: tuple[str, ...]
    poll_interval_seconds: int
    collection_sessions: str
    max_calls_per_minute: int
    lease_ttl_seconds: int
    stale_after_seconds: int
    storage: RealtimeFeedStorageConfig
    ts_code_pattern: str
    source_timeout_seconds: int

    def feed_key_for_freq(self, freq: str) -> str:
        normalized_freq = normalize_stock_rt_min_freq(freq)
        return f"tushare_stock_rt_min_{normalized_freq.lower()}"


@dataclass(frozen=True, slots=True)
class RealtimeRuntimeConfig:
    redis_url: str
    stock_rt_daily: RealtimeStockRtDailyConfig
    stock_rt_min: RealtimeStockRtMinConfig


def get_realtime_runtime_config(settings: Settings | None = None) -> RealtimeRuntimeConfig:
    source = settings or get_settings()
    stock_rt_daily = _build_stock_rt_daily_config(source)
    stock_rt_min = _build_stock_rt_min_config(source)
    return RealtimeRuntimeConfig(
        redis_url=source.redis_url,
        stock_rt_daily=stock_rt_daily,
        stock_rt_min=stock_rt_min,
    )


def get_realtime_stock_rt_daily_config(settings: Settings | None = None) -> RealtimeStockRtDailyConfig:
    return get_realtime_runtime_config(settings).stock_rt_daily


def get_realtime_stock_rt_min_config(settings: Settings | None = None) -> RealtimeStockRtMinConfig:
    return get_realtime_runtime_config(settings).stock_rt_min


def get_realtime_tushare_max_calls_per_minute(api_name: str) -> int | None:
    if api_name == STOCK_RT_DAILY_SOURCE_API_NAME:
        return get_realtime_stock_rt_daily_config().max_calls_per_minute
    if api_name == STOCK_RT_MIN_SOURCE_API_NAME:
        return get_realtime_stock_rt_min_config().max_calls_per_minute
    return None


def normalize_stock_rt_min_freq(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in STOCK_RT_MIN_ALLOWED_FREQS:
        raise ValueError(f"invalid stock realtime minute freq: {value}")
    return normalized


def _build_stock_rt_daily_config(settings: Settings) -> RealtimeStockRtDailyConfig:
    poll_interval_seconds = _positive_int("REALTIME_STOCK_RT_DAILY_POLL_INTERVAL_SECONDS", settings.realtime_stock_rt_daily_poll_interval_seconds)
    max_calls_per_minute = _positive_int("REALTIME_STOCK_RT_DAILY_MAX_CALLS_PER_MINUTE", settings.realtime_stock_rt_daily_max_calls_per_minute)
    _validate_collection_sessions("REALTIME_STOCK_RT_DAILY_COLLECTION_SESSIONS", settings.realtime_stock_rt_daily_collection_sessions)
    _validate_request_budget(
        label="REALTIME_STOCK_RT_DAILY",
        feed_count=1,
        poll_interval_seconds=poll_interval_seconds,
        max_calls_per_minute=max_calls_per_minute,
    )
    _validate_stale_window(
        label="REALTIME_STOCK_RT_DAILY",
        poll_interval_seconds=poll_interval_seconds,
        stale_after_seconds=settings.realtime_stock_rt_daily_stale_after_seconds,
    )
    return RealtimeStockRtDailyConfig(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        display_name=STOCK_RT_DAILY_DISPLAY_NAME,
        source_api_name=STOCK_RT_DAILY_SOURCE_API_NAME,
        exchange=_non_empty_text("DEFAULT_EXCHANGE", settings.default_exchange),
        enabled=bool(settings.realtime_stock_rt_daily_enabled),
        poll_interval_seconds=poll_interval_seconds,
        collection_sessions=settings.realtime_stock_rt_daily_collection_sessions,
        max_calls_per_minute=max_calls_per_minute,
        lease_ttl_seconds=_positive_int("REALTIME_STOCK_RT_DAILY_LEASE_TTL_SECONDS", settings.realtime_stock_rt_daily_lease_ttl_seconds),
        stale_after_seconds=_positive_int("REALTIME_STOCK_RT_DAILY_STALE_AFTER_SECONDS", settings.realtime_stock_rt_daily_stale_after_seconds),
        storage=RealtimeFeedStorageConfig(
            snapshot_ttl_seconds=_positive_int(
                "REALTIME_STOCK_RT_DAILY_SNAPSHOT_TTL_SECONDS",
                settings.realtime_stock_rt_daily_snapshot_ttl_seconds,
            ),
            keep_recent_batches=_positive_int(
                "REALTIME_STOCK_RT_DAILY_KEEP_RECENT_BATCHES",
                settings.realtime_stock_rt_daily_keep_recent_batches,
            ),
            batch_stream_maxlen=_positive_int(
                "REALTIME_STOCK_RT_DAILY_BATCH_STREAM_MAXLEN",
                settings.realtime_stock_rt_daily_batch_stream_maxlen,
            ),
            delta_stream_maxlen=_positive_int(
                "REALTIME_STOCK_RT_DAILY_DELTA_STREAM_MAXLEN",
                settings.realtime_stock_rt_daily_delta_stream_maxlen,
            ),
        ),
        ts_code_pattern=_non_empty_text("REALTIME_STOCK_RT_DAILY_TS_CODE_PATTERN", settings.realtime_stock_rt_daily_ts_code_pattern),
    )


def _build_stock_rt_min_config(settings: Settings) -> RealtimeStockRtMinConfig:
    enabled_freqs = _parse_stock_rt_min_freqs(settings.realtime_stock_rt_min_enabled_freqs)
    poll_interval_seconds = _positive_int("REALTIME_STOCK_RT_MIN_POLL_INTERVAL_SECONDS", settings.realtime_stock_rt_min_poll_interval_seconds)
    max_calls_per_minute = _positive_int("REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE", settings.realtime_stock_rt_min_max_calls_per_minute)
    _validate_collection_sessions("REALTIME_STOCK_RT_MIN_COLLECTION_SESSIONS", settings.realtime_stock_rt_min_collection_sessions)
    _validate_request_budget(
        label="REALTIME_STOCK_RT_MIN",
        feed_count=len(enabled_freqs),
        poll_interval_seconds=poll_interval_seconds,
        max_calls_per_minute=max_calls_per_minute,
    )
    _validate_stale_window(
        label="REALTIME_STOCK_RT_MIN",
        poll_interval_seconds=poll_interval_seconds,
        stale_after_seconds=settings.realtime_stock_rt_min_stale_after_seconds,
    )
    return RealtimeStockRtMinConfig(
        display_name=STOCK_RT_MIN_DISPLAY_NAME,
        source_api_name=STOCK_RT_MIN_SOURCE_API_NAME,
        exchange=_non_empty_text("DEFAULT_EXCHANGE", settings.default_exchange),
        enabled=bool(settings.realtime_stock_rt_min_enabled),
        enabled_freqs=enabled_freqs,
        poll_interval_seconds=poll_interval_seconds,
        collection_sessions=settings.realtime_stock_rt_min_collection_sessions,
        max_calls_per_minute=max_calls_per_minute,
        lease_ttl_seconds=_positive_int("REALTIME_STOCK_RT_MIN_LEASE_TTL_SECONDS", settings.realtime_stock_rt_min_lease_ttl_seconds),
        stale_after_seconds=_positive_int("REALTIME_STOCK_RT_MIN_STALE_AFTER_SECONDS", settings.realtime_stock_rt_min_stale_after_seconds),
        storage=RealtimeFeedStorageConfig(
            snapshot_ttl_seconds=_positive_int(
                "REALTIME_STOCK_RT_MIN_SNAPSHOT_TTL_SECONDS",
                settings.realtime_stock_rt_min_snapshot_ttl_seconds,
            ),
            keep_recent_batches=_positive_int(
                "REALTIME_STOCK_RT_MIN_KEEP_RECENT_BATCHES",
                settings.realtime_stock_rt_min_keep_recent_batches,
            ),
            batch_stream_maxlen=_positive_int(
                "REALTIME_STOCK_RT_MIN_BATCH_STREAM_MAXLEN",
                settings.realtime_stock_rt_min_batch_stream_maxlen,
            ),
            delta_stream_maxlen=_positive_int(
                "REALTIME_STOCK_RT_MIN_DELTA_STREAM_MAXLEN",
                settings.realtime_stock_rt_min_delta_stream_maxlen,
            ),
        ),
        ts_code_pattern=_non_empty_text("REALTIME_STOCK_RT_MIN_TS_CODE_PATTERN", settings.realtime_stock_rt_min_ts_code_pattern),
        source_timeout_seconds=_positive_int("REALTIME_STOCK_RT_MIN_SOURCE_TIMEOUT_SECONDS", settings.realtime_stock_rt_min_source_timeout_seconds),
    )


def _parse_stock_rt_min_freqs(raw_value: str) -> tuple[str, ...]:
    seen: set[str] = set()
    results: list[str] = []
    for raw_part in str(raw_value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        freq = normalize_stock_rt_min_freq(part)
        if freq in seen:
            continue
        seen.add(freq)
        results.append(freq)
    if not results:
        raise ValueError("REALTIME_STOCK_RT_MIN_ENABLED_FREQS cannot be empty")
    return tuple(results)


def _positive_int(name: str, value: int) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return parsed


def _non_empty_text(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} cannot be empty")
    return text


def _validate_collection_sessions(name: str, value: str) -> None:
    has_session = False
    for raw_part in str(value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        has_session = True
        start_text, separator, end_text = part.partition("-")
        if not separator:
            raise ValueError(f"{name} contains invalid session: {part}")
        start = time.fromisoformat(start_text.strip())
        end = time.fromisoformat(end_text.strip())
        if start >= end:
            raise ValueError(f"{name} session start must be before end: {part}")
    if not has_session:
        raise ValueError(f"{name} cannot be empty")


def _validate_request_budget(
    *,
    label: str,
    feed_count: int,
    poll_interval_seconds: int,
    max_calls_per_minute: int,
) -> None:
    required_calls_per_minute = feed_count * 60 / poll_interval_seconds
    if required_calls_per_minute > max_calls_per_minute:
        raise ValueError(
            f"{label} max_calls_per_minute={max_calls_per_minute} cannot cover "
            f"{feed_count} feed(s) at poll_interval_seconds={poll_interval_seconds}"
        )


def _validate_stale_window(*, label: str, poll_interval_seconds: int, stale_after_seconds: int) -> None:
    if _positive_int(f"{label}_STALE_AFTER_SECONDS", stale_after_seconds) < poll_interval_seconds:
        raise ValueError(f"{label} stale_after_seconds must be greater than or equal to poll_interval_seconds")
