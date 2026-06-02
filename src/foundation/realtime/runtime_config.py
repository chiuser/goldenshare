from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.config.settings import Settings, get_settings
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime.config_catalog import (
    STOCK_RT_DAILY_CATALOG,
    STOCK_RT_DAILY_OBJECT_KEY,
    STOCK_RT_MIN_CATALOG,
    STOCK_RT_MIN_FEED_KEY_PREFIX,
    STOCK_RT_MIN_OBJECT_KEY,
)
from src.foundation.realtime.constants import (
    STOCK_RT_DAILY_SOURCE_API_NAME,
    STOCK_RT_MIN_SOURCE_API_NAME,
)


STOCK_RT_MIN_ALLOWED_FREQS = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")


class RealtimeRuntimeConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RealtimeFeedStorageConfig:
    snapshot_ttl_seconds: int
    keep_recent_batches: int
    batch_stream_maxlen: int
    delta_stream_maxlen: int


@dataclass(frozen=True, slots=True)
class RealtimeStockRtDailyConfig:
    version: int
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
    version: int
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
        return f"{STOCK_RT_MIN_FEED_KEY_PREFIX}_{normalized_freq.lower()}"


@dataclass(frozen=True, slots=True)
class RealtimeRuntimeConfig:
    redis_url: str
    stock_rt_daily: RealtimeStockRtDailyConfig
    stock_rt_min: RealtimeStockRtMinConfig


def get_realtime_runtime_config(
    session: Session | None = None,
    settings: Settings | None = None,
) -> RealtimeRuntimeConfig:
    if session is not None:
        return load_realtime_runtime_config(session, settings=settings)
    if settings is not None:
        return _load_runtime_config_with_short_session(settings=settings)
    return _get_cached_realtime_runtime_config()


def load_realtime_runtime_config(
    session: Session,
    *,
    settings: Settings | None = None,
) -> RealtimeRuntimeConfig:
    daily_record = _get_required_record(session, STOCK_RT_DAILY_OBJECT_KEY, expected_kind=STOCK_RT_DAILY_CATALOG.object_kind)
    minute_record = _get_required_record(session, STOCK_RT_MIN_OBJECT_KEY, expected_kind=STOCK_RT_MIN_CATALOG.object_kind)
    return build_realtime_runtime_config_from_json(
        daily_config=daily_record.runtime_config_json,
        minute_config=minute_record.runtime_config_json,
        daily_version=daily_record.version,
        minute_version=minute_record.version,
        settings=settings,
    )


@lru_cache(maxsize=1)
def _get_cached_realtime_runtime_config() -> RealtimeRuntimeConfig:
    return _load_runtime_config_with_short_session(settings=get_settings())


def clear_realtime_runtime_config_cache() -> None:
    _get_cached_realtime_runtime_config.cache_clear()


def get_realtime_stock_rt_daily_config(session: Session | None = None) -> RealtimeStockRtDailyConfig:
    return get_realtime_runtime_config(session).stock_rt_daily


def get_realtime_stock_rt_min_config(session: Session | None = None) -> RealtimeStockRtMinConfig:
    return get_realtime_runtime_config(session).stock_rt_min


def get_realtime_tushare_max_calls_per_minute(api_name: str, session: Session | None = None) -> int | None:
    if api_name == STOCK_RT_DAILY_SOURCE_API_NAME:
        return get_realtime_stock_rt_daily_config(session).max_calls_per_minute
    if api_name == STOCK_RT_MIN_SOURCE_API_NAME:
        return get_realtime_stock_rt_min_config(session).max_calls_per_minute
    return None


def build_realtime_runtime_config_from_json(
    *,
    daily_config: Mapping[str, Any],
    minute_config: Mapping[str, Any],
    daily_version: int = 0,
    minute_version: int = 0,
    settings: Settings | None = None,
) -> RealtimeRuntimeConfig:
    source_settings = settings or get_settings()
    stock_rt_daily = _build_stock_rt_daily_config(daily_config, version=daily_version)
    stock_rt_min = _build_stock_rt_min_config(minute_config, version=minute_version)
    return RealtimeRuntimeConfig(
        redis_url=_non_empty_text("REDIS_URL", source_settings.redis_url),
        stock_rt_daily=stock_rt_daily,
        stock_rt_min=stock_rt_min,
    )


def normalize_stock_rt_min_freq(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in STOCK_RT_MIN_ALLOWED_FREQS:
        raise RealtimeRuntimeConfigError(f"invalid stock realtime minute freq: {value}")
    return normalized


def _load_runtime_config_with_short_session(*, settings: Settings) -> RealtimeRuntimeConfig:
    from src.db import SessionLocal

    with SessionLocal() as session:
        return load_realtime_runtime_config(session, settings=settings)


def _get_required_record(session: Session, object_key: str, *, expected_kind: str) -> RealtimeRuntimeConfigRecord:
    record = session.get(RealtimeRuntimeConfigRecord, object_key)
    if record is None:
        raise RealtimeRuntimeConfigError(f"realtime runtime config missing: {object_key}")
    if record.object_kind != expected_kind:
        raise RealtimeRuntimeConfigError(
            f"realtime runtime config {object_key} object_kind must be {expected_kind}, got {record.object_kind}"
        )
    if not isinstance(record.runtime_config_json, dict):
        raise RealtimeRuntimeConfigError(f"realtime runtime config {object_key} runtime_config_json must be an object")
    return record


def _build_stock_rt_daily_config(raw_config: Mapping[str, Any], *, version: int) -> RealtimeStockRtDailyConfig:
    poll_interval_seconds = _positive_int(
        "stock_rt_daily.poll_interval_seconds",
        _required_value(raw_config, "poll_interval_seconds", object_key=STOCK_RT_DAILY_OBJECT_KEY),
    )
    max_calls_per_minute = _positive_int(
        "stock_rt_daily.max_calls_per_minute",
        _required_value(raw_config, "max_calls_per_minute", object_key=STOCK_RT_DAILY_OBJECT_KEY),
    )
    _validate_collection_sessions("stock_rt_daily.collection_sessions", STOCK_RT_DAILY_CATALOG.collection_sessions)
    _validate_request_budget(
        label="stock_rt_daily",
        feed_count=1,
        poll_interval_seconds=poll_interval_seconds,
        max_calls_per_minute=max_calls_per_minute,
    )
    stale_after_seconds = _positive_int(
        "stock_rt_daily.stale_after_seconds",
        _required_value(raw_config, "stale_after_seconds", object_key=STOCK_RT_DAILY_OBJECT_KEY),
    )
    _validate_stale_window(
        label="stock_rt_daily",
        poll_interval_seconds=poll_interval_seconds,
        stale_after_seconds=stale_after_seconds,
    )
    return RealtimeStockRtDailyConfig(
        version=int(version),
        feed_key=_non_empty_text("stock_rt_daily.feed_key", STOCK_RT_DAILY_CATALOG.feed_key),
        display_name=STOCK_RT_DAILY_CATALOG.display_name,
        source_api_name=STOCK_RT_DAILY_CATALOG.source_api_name,
        exchange=STOCK_RT_DAILY_CATALOG.exchange,
        enabled=_bool_value("stock_rt_daily.enabled", _required_value(raw_config, "enabled", object_key=STOCK_RT_DAILY_OBJECT_KEY)),
        poll_interval_seconds=poll_interval_seconds,
        collection_sessions=STOCK_RT_DAILY_CATALOG.collection_sessions,
        max_calls_per_minute=max_calls_per_minute,
        lease_ttl_seconds=_positive_int(
            "stock_rt_daily.lease_ttl_seconds",
            _required_value(raw_config, "lease_ttl_seconds", object_key=STOCK_RT_DAILY_OBJECT_KEY),
        ),
        stale_after_seconds=stale_after_seconds,
        storage=_build_storage_config(STOCK_RT_DAILY_OBJECT_KEY, raw_config),
        ts_code_pattern=STOCK_RT_DAILY_CATALOG.ts_code_pattern,
    )


def _build_stock_rt_min_config(raw_config: Mapping[str, Any], *, version: int) -> RealtimeStockRtMinConfig:
    enabled_freqs = _parse_stock_rt_min_freqs(_required_value(raw_config, "enabled_freqs", object_key=STOCK_RT_MIN_OBJECT_KEY))
    poll_interval_seconds = _positive_int(
        "stock_rt_min.poll_interval_seconds",
        _required_value(raw_config, "poll_interval_seconds", object_key=STOCK_RT_MIN_OBJECT_KEY),
    )
    max_calls_per_minute = _positive_int(
        "stock_rt_min.max_calls_per_minute",
        _required_value(raw_config, "max_calls_per_minute", object_key=STOCK_RT_MIN_OBJECT_KEY),
    )
    _validate_collection_sessions("stock_rt_min.collection_sessions", STOCK_RT_MIN_CATALOG.collection_sessions)
    _validate_request_budget(
        label="stock_rt_min",
        feed_count=len(enabled_freqs),
        poll_interval_seconds=poll_interval_seconds,
        max_calls_per_minute=max_calls_per_minute,
    )
    stale_after_seconds = _positive_int(
        "stock_rt_min.stale_after_seconds",
        _required_value(raw_config, "stale_after_seconds", object_key=STOCK_RT_MIN_OBJECT_KEY),
    )
    _validate_stale_window(
        label="stock_rt_min",
        poll_interval_seconds=poll_interval_seconds,
        stale_after_seconds=stale_after_seconds,
    )
    return RealtimeStockRtMinConfig(
        version=int(version),
        display_name=STOCK_RT_MIN_CATALOG.display_name,
        source_api_name=STOCK_RT_MIN_CATALOG.source_api_name,
        exchange=STOCK_RT_MIN_CATALOG.exchange,
        enabled=_bool_value("stock_rt_min.enabled", _required_value(raw_config, "enabled", object_key=STOCK_RT_MIN_OBJECT_KEY)),
        enabled_freqs=enabled_freqs,
        poll_interval_seconds=poll_interval_seconds,
        collection_sessions=STOCK_RT_MIN_CATALOG.collection_sessions,
        max_calls_per_minute=max_calls_per_minute,
        lease_ttl_seconds=_positive_int(
            "stock_rt_min.lease_ttl_seconds",
            _required_value(raw_config, "lease_ttl_seconds", object_key=STOCK_RT_MIN_OBJECT_KEY),
        ),
        stale_after_seconds=stale_after_seconds,
        storage=_build_storage_config(STOCK_RT_MIN_OBJECT_KEY, raw_config),
        ts_code_pattern=STOCK_RT_MIN_CATALOG.ts_code_pattern,
        source_timeout_seconds=_positive_int(
            "stock_rt_min.source_timeout_seconds",
            _required_value(raw_config, "source_timeout_seconds", object_key=STOCK_RT_MIN_OBJECT_KEY),
        ),
    )


def _build_storage_config(object_key: str, raw_config: Mapping[str, Any]) -> RealtimeFeedStorageConfig:
    return RealtimeFeedStorageConfig(
        snapshot_ttl_seconds=_positive_int(
            f"{object_key}.snapshot_ttl_seconds",
            _required_value(raw_config, "snapshot_ttl_seconds", object_key=object_key),
        ),
        keep_recent_batches=_positive_int(
            f"{object_key}.keep_recent_batches",
            _required_value(raw_config, "keep_recent_batches", object_key=object_key),
        ),
        batch_stream_maxlen=_positive_int(
            f"{object_key}.batch_stream_maxlen",
            _required_value(raw_config, "batch_stream_maxlen", object_key=object_key),
        ),
        delta_stream_maxlen=_positive_int(
            f"{object_key}.delta_stream_maxlen",
            _required_value(raw_config, "delta_stream_maxlen", object_key=object_key),
        ),
    )


def _parse_stock_rt_min_freqs(raw_value: Any) -> tuple[str, ...]:
    raw_items = raw_value if isinstance(raw_value, list | tuple) else str(raw_value or "").split(",")
    seen: set[str] = set()
    results: list[str] = []
    for raw_part in raw_items:
        part = str(raw_part or "").strip()
        if not part:
            continue
        freq = normalize_stock_rt_min_freq(part)
        if freq in seen:
            continue
        seen.add(freq)
        results.append(freq)
    if not results:
        raise RealtimeRuntimeConfigError("stock_rt_min.enabled_freqs cannot be empty")
    return tuple(results)


def _required_value(raw_config: Mapping[str, Any], key: str, *, object_key: str) -> Any:
    if key not in raw_config:
        raise RealtimeRuntimeConfigError(f"realtime runtime config {object_key}.{key} is required")
    return raw_config[key]


def _positive_int(name: str, value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RealtimeRuntimeConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise RealtimeRuntimeConfigError(f"{name} must be greater than 0")
    return parsed


def _bool_value(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise RealtimeRuntimeConfigError(f"{name} must be a boolean")


def _non_empty_text(name: str, value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        raise RealtimeRuntimeConfigError(f"{name} cannot be empty")
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
            raise RealtimeRuntimeConfigError(f"{name} contains invalid session: {part}")
        start = time.fromisoformat(start_text.strip())
        end = time.fromisoformat(end_text.strip())
        if start >= end:
            raise RealtimeRuntimeConfigError(f"{name} session start must be before end: {part}")
    if not has_session:
        raise RealtimeRuntimeConfigError(f"{name} cannot be empty")


def _validate_request_budget(
    *,
    label: str,
    feed_count: int,
    poll_interval_seconds: int,
    max_calls_per_minute: int,
) -> None:
    required_calls_per_minute = feed_count * 60 / poll_interval_seconds
    if required_calls_per_minute > max_calls_per_minute:
        raise RealtimeRuntimeConfigError(
            f"{label} max_calls_per_minute={max_calls_per_minute} cannot cover "
            f"{feed_count} feed(s) at poll_interval_seconds={poll_interval_seconds}"
        )


def _validate_stale_window(*, label: str, poll_interval_seconds: int, stale_after_seconds: int) -> None:
    if _positive_int(f"{label}.stale_after_seconds", stale_after_seconds) < poll_interval_seconds:
        raise RealtimeRuntimeConfigError(f"{label} stale_after_seconds must be greater than or equal to poll_interval_seconds")
