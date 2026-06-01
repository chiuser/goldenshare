from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
import os
import socket
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.clients import TushareHttpClient
from src.foundation.realtime.constants import (
    STOCK_RT_MIN_SOURCE,
    STOCK_RT_MIN_SOURCE_API_NAME,
)
from src.foundation.realtime.feed_config import RealtimeStockRtMinConfig, get_realtime_stock_rt_min_config, normalize_stock_rt_min_freq
from src.foundation.realtime.market_clock import RealtimeMarketClock
from src.foundation.realtime.state_store import RealtimePublishResult, RealtimeStateStore
from src.foundation.realtime.state_store import RealtimeStateStoreUnavailable
from src.foundation.realtime.stock_rt_daily import build_batch_id


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
STOCK_RT_MIN_FIELDS = (
    "ts_code",
    "freq",
    "time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
)


@dataclass(frozen=True, slots=True)
class StockRtMinFetchResult:
    freq: str
    feed_key: str
    rows: list[dict[str, Any]]
    source_elapsed_ms: float
    request_params: dict[str, str]


@dataclass(frozen=True, slots=True)
class StockRtMinNormalizeResult:
    snapshots: list[dict[str, Any]]
    invalid_count: int
    invalid_reason_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class StockRtMinCycleResult:
    status: str
    freq: str
    feed_key: str
    collection_status: str = "unknown"
    fetched_rows: int = 0
    snapshot_count: int = 0
    invalid_count: int = 0
    invalid_reason_counts: dict[str, int] | None = None
    delta_count: int = 0
    batch_id: str | None = None
    received_at: str | None = None
    published_at: str | None = None
    source_elapsed_ms: float | None = None
    write_elapsed_ms: float | None = None
    last_batch_event_id: str | None = None
    last_delta_event_id: str | None = None
    message: str | None = None


class TushareStockRtMinProvider:
    def __init__(
        self,
        *,
        client: TushareHttpClient | None = None,
        config: RealtimeStockRtMinConfig | None = None,
        ts_code_pattern: str | None = None,
    ) -> None:
        self._config = config or get_realtime_stock_rt_min_config()
        self._client = client or TushareHttpClient(timeout=self._config.source_timeout_seconds)
        self._ts_code_pattern = ts_code_pattern or self._config.ts_code_pattern

    def fetch_all_market(self, *, freq: str) -> StockRtMinFetchResult:
        normalized_freq = normalize_stock_rt_min_freq(freq)
        feed_key = self._config.feed_key_for_freq(normalized_freq)
        params = {"ts_code": self._ts_code_pattern, "freq": normalized_freq}
        started = time.perf_counter()
        rows = self._client.call(STOCK_RT_MIN_SOURCE_API_NAME, params=params, fields=STOCK_RT_MIN_FIELDS)
        return StockRtMinFetchResult(
            freq=normalized_freq,
            feed_key=feed_key,
            rows=rows,
            source_elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            request_params=params,
        )


class StockRtMinFeedPublisher:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        provider: TushareStockRtMinProvider | None = None,
        config: RealtimeStockRtMinConfig | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config or get_realtime_stock_rt_min_config()
        self._store = store
        self._provider = provider or TushareStockRtMinProvider(config=self._config)
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))

    def publish_freq(self, *, freq: str) -> StockRtMinCycleResult:
        normalized_freq = normalize_stock_rt_min_freq(freq)
        feed_key = self._config.feed_key_for_freq(normalized_freq)
        fetch_result = self._provider.fetch_all_market(freq=normalized_freq)
        received_at = self._now_provider().astimezone(CN_TIMEZONE)
        batch_id = build_batch_id(received_at)
        normalize_result = normalize_stock_rt_min_rows(
            fetch_result.rows,
            freq=normalized_freq,
            received_at=received_at,
        )
        previous_batch_id = self._store.get_current_batch_id(feed_key)
        delta_snapshots = self._build_delta_snapshots(
            feed_key=feed_key,
            previous_batch_id=previous_batch_id,
            snapshots=normalize_result.snapshots,
        )
        write_started = time.perf_counter()
        published_at = self._now_provider().astimezone(CN_TIMEZONE)
        publish_result = self._store.publish_batch(
            feed_key=feed_key,
            batch_id=batch_id,
            snapshots=normalize_result.snapshots,
            meta={
                "received_at": received_at.isoformat(),
                "published_at": published_at.isoformat(),
                "source_elapsed_ms": fetch_result.source_elapsed_ms,
                "source_row_count": len(fetch_result.rows),
                "request_params": fetch_result.request_params,
                "freq": normalized_freq,
                "invalid_count": normalize_result.invalid_count,
                "invalid_reason_counts": normalize_result.invalid_reason_counts,
            },
            ttl_seconds=self._config.storage.snapshot_ttl_seconds,
            keep_recent_batches=self._config.storage.keep_recent_batches,
            batch_stream_maxlen=self._config.storage.batch_stream_maxlen,
            delta_stream_maxlen=self._config.storage.delta_stream_maxlen,
            delta_snapshots=delta_snapshots,
        )
        write_elapsed_ms = round((time.perf_counter() - write_started) * 1000, 2)
        return _build_cycle_result(
            freq=normalized_freq,
            feed_key=feed_key,
            batch_id=batch_id,
            received_at=received_at.isoformat(),
            published_at=published_at.isoformat(),
            fetched_rows=len(fetch_result.rows),
            snapshot_count=len(normalize_result.snapshots),
            invalid_count=normalize_result.invalid_count,
            invalid_reason_counts=normalize_result.invalid_reason_counts,
            source_elapsed_ms=fetch_result.source_elapsed_ms,
            write_elapsed_ms=write_elapsed_ms,
            publish_result=publish_result,
            delta_count=len(delta_snapshots),
        )

    def _build_delta_snapshots(
        self,
        *,
        feed_key: str,
        previous_batch_id: str | None,
        snapshots: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not previous_batch_id:
            return []
        previous = self._store.get_snapshots(
            feed_key,
            previous_batch_id,
            [snapshot["ts_code"] for snapshot in snapshots],
        )
        return [
            snapshot
            for snapshot in snapshots
            if previous.get(snapshot["ts_code"], {}).get("raw_payload_hash") != snapshot.get("raw_payload_hash")
        ]


class StockRtMinCollector:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        provider: TushareStockRtMinProvider | None = None,
        config: RealtimeStockRtMinConfig | None = None,
        clock: RealtimeMarketClock | None = None,
        now_provider: Callable[[], datetime] | None = None,
        collector_id: str | None = None,
    ) -> None:
        self._config = config or get_realtime_stock_rt_min_config()
        self._store = store
        self._provider = provider or TushareStockRtMinProvider(config=self._config)
        self._clock = clock or RealtimeMarketClock()
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))
        self._collector_id = collector_id or f"{socket.gethostname()}:{os.getpid()}"
        self._publisher = StockRtMinFeedPublisher(
            store=store,
            provider=self._provider,
            config=self._config,
            now_provider=self._now_provider,
        )
        self._request_timestamps_by_freq: dict[str, list[float]] = {}

    def run_freq_cycle(self, session: Session, *, freq: str) -> StockRtMinCycleResult:
        normalized_freq = normalize_stock_rt_min_freq(freq)
        feed_key = self._config.feed_key_for_freq(normalized_freq)
        try:
            return self._run_freq_cycle(session, freq=normalized_freq, feed_key=feed_key)
        except RealtimeStateStoreUnavailable as exc:
            return StockRtMinCycleResult(
                status="unavailable",
                freq=normalized_freq,
                feed_key=feed_key,
                collection_status="unknown",
                message=str(exc),
            )

    def _run_freq_cycle(self, session: Session, *, freq: str, feed_key: str) -> StockRtMinCycleResult:
        config = self._config
        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock_context = self._clock.resolve(
            session,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            now=now,
        )
        if not config.enabled:
            self._merge_health(
                feed_key,
                {
                    "status": "idle",
                    "enabled": False,
                    "collector_running": True,
                    "collector_id": self._collector_id,
                    "feed_key": feed_key,
                    "freq": freq,
                    "collection_status": "disabled",
                    "is_trading_day": clock_context.is_trading_day,
                    "last_request_at": None,
                },
            )
            return StockRtMinCycleResult(
                status="idle",
                freq=freq,
                feed_key=feed_key,
                collection_status="disabled",
                message="feed disabled",
            )

        if clock_context.collection_status != "open":
            self._merge_health(
                feed_key,
                {
                    "status": "idle",
                    "enabled": True,
                    "collector_running": True,
                    "collector_id": self._collector_id,
                    "feed_key": feed_key,
                    "freq": freq,
                    "collection_status": clock_context.collection_status,
                    "is_trading_day": clock_context.is_trading_day,
                },
            )
            return StockRtMinCycleResult(
                status="idle",
                freq=freq,
                feed_key=feed_key,
                collection_status=clock_context.collection_status,
            )

        if not self._store.acquire_lease(feed_key, owner=self._collector_id, ttl_seconds=config.lease_ttl_seconds):
            return StockRtMinCycleResult(
                status="skipped",
                freq=freq,
                feed_key=feed_key,
                collection_status="open",
                message="collector lease not acquired",
            )

        try:
            result = self._run_open_freq_cycle(freq=freq, feed_key=feed_key, now=now, is_trading_day=clock_context.is_trading_day)
        except Exception as exc:
            self._record_error(feed_key, freq=freq, exc=exc, now=now)
            result = StockRtMinCycleResult(
                status="degraded",
                freq=freq,
                feed_key=feed_key,
                collection_status="open",
                message=str(exc),
            )
        finally:
            try:
                self._store.release_lease(feed_key, owner=self._collector_id)
            except RealtimeStateStoreUnavailable:
                pass
        return result

    def _run_open_freq_cycle(
        self,
        *,
        freq: str,
        feed_key: str,
        now: datetime,
        is_trading_day: bool,
    ) -> StockRtMinCycleResult:
        requested_at = now.isoformat()
        self._record_request_timestamp(freq)
        result = self._publisher.publish_freq(freq=freq)
        self._record_success_health(
            feed_key=feed_key,
            freq=freq,
            result=result,
            requested_at=requested_at,
            is_trading_day=is_trading_day,
        )
        return replace(result, collection_status="open")

    def _record_request_timestamp(self, freq: str) -> None:
        now_monotonic = time.monotonic()
        current = self._request_timestamps_by_freq.setdefault(freq, [])
        self._request_timestamps_by_freq[freq] = [item for item in current if now_monotonic - item <= 60]
        self._request_timestamps_by_freq[freq].append(now_monotonic)

    def _request_count_last_minute(self, freq: str) -> int:
        now_monotonic = time.monotonic()
        current = self._request_timestamps_by_freq.setdefault(freq, [])
        self._request_timestamps_by_freq[freq] = [item for item in current if now_monotonic - item <= 60]
        return len(self._request_timestamps_by_freq[freq])

    def _record_success_health(
        self,
        *,
        feed_key: str,
        freq: str,
        result: StockRtMinCycleResult,
        requested_at: str,
        is_trading_day: bool,
    ) -> None:
        self._merge_health(
            feed_key,
            {
                "status": "ok",
                "enabled": True,
                "collector_running": True,
                "collector_id": self._collector_id,
                "feed_key": feed_key,
                "freq": freq,
                "last_request_at": requested_at,
                "last_success_at": result.published_at,
                "last_error_at": None,
                "last_error_message": None,
                "current_batch_id": result.batch_id,
                "current_batch_received_at": result.received_at,
                "current_batch_published_at": result.published_at,
                "source_elapsed_ms": result.source_elapsed_ms,
                "write_elapsed_ms": result.write_elapsed_ms,
                "source_row_count": result.fetched_rows,
                "snapshot_count": result.snapshot_count,
                "invalid_count": result.invalid_count,
                "invalid_reason_counts": result.invalid_reason_counts or {},
                "request_count_last_minute": self._request_count_last_minute(freq),
                "is_trading_day": is_trading_day,
                "collection_status": "open",
                "last_batch_event_id": result.last_batch_event_id,
                "last_delta_event_id": result.last_delta_event_id,
                "delta_count_last_batch": result.delta_count,
            },
        )

    def _record_error(self, feed_key: str, *, freq: str, exc: Exception, now: datetime) -> None:
        self._merge_health(
            feed_key,
            {
                "status": "degraded",
                "enabled": True,
                "collector_running": True,
                "collector_id": self._collector_id,
                "feed_key": feed_key,
                "freq": freq,
                "last_request_at": now.isoformat(),
                "last_error_at": now.isoformat(),
                "last_error_message": str(exc),
                "collection_status": "open",
                "request_count_last_minute": self._request_count_last_minute(freq),
            },
        )

    def _merge_health(self, feed_key: str, payload: dict[str, Any]) -> None:
        existing = self._store.get_health(feed_key) or {}
        existing.update(payload)
        self._store.set_health(feed_key, existing)


def normalize_stock_rt_min_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    freq: str,
    received_at: datetime,
) -> StockRtMinNormalizeResult:
    expected_freq = normalize_stock_rt_min_freq(freq)
    snapshots: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        row_freq = str(row.get("freq") or "").strip().upper()
        source_time = _normalize_value(row.get("time"))
        invalid_reason = _invalid_reason(ts_code=ts_code, row_freq=row_freq, expected_freq=expected_freq, source_time=source_time)
        if invalid_reason:
            invalid_reason_counts[invalid_reason] = invalid_reason_counts.get(invalid_reason, 0) + 1
            continue
        payload = {field: _normalize_value(row.get(field)) for field in STOCK_RT_MIN_FIELDS}
        payload["ts_code"] = ts_code
        payload["freq"] = row_freq
        payload["time"] = source_time
        payload["source"] = STOCK_RT_MIN_SOURCE
        payload["source_api_name"] = STOCK_RT_MIN_SOURCE_API_NAME
        payload["received_at"] = received_at.isoformat()
        payload["raw_payload_hash"] = _payload_hash(payload)
        snapshots.append(payload)
    return StockRtMinNormalizeResult(
        snapshots=snapshots,
        invalid_count=sum(invalid_reason_counts.values()),
        invalid_reason_counts=invalid_reason_counts,
    )


def _invalid_reason(*, ts_code: str, row_freq: str, expected_freq: str, source_time: str | None) -> str | None:
    if not ts_code:
        return "missing_ts_code"
    if not row_freq:
        return "missing_freq"
    if row_freq != expected_freq:
        return "freq_mismatch"
    if not source_time:
        return "missing_time"
    return None


def _build_cycle_result(
    *,
    freq: str,
    feed_key: str,
    batch_id: str,
    received_at: str,
    published_at: str,
    fetched_rows: int,
    snapshot_count: int,
    invalid_count: int,
    invalid_reason_counts: dict[str, int],
    source_elapsed_ms: float,
    write_elapsed_ms: float,
    publish_result: RealtimePublishResult,
    delta_count: int,
) -> StockRtMinCycleResult:
    return StockRtMinCycleResult(
        status="ok",
        freq=freq,
        feed_key=feed_key,
        collection_status="open",
        fetched_rows=fetched_rows,
        snapshot_count=snapshot_count,
        invalid_count=invalid_count,
        invalid_reason_counts=invalid_reason_counts,
        delta_count=delta_count,
        batch_id=batch_id,
        received_at=received_at,
        published_at=published_at,
        source_elapsed_ms=source_elapsed_ms,
        write_elapsed_ms=write_elapsed_ms,
        last_batch_event_id=publish_result.batch_event_id,
        last_delta_event_id=publish_result.delta_event_ids[-1] if publish_result.delta_event_ids else None,
    )


def _normalize_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _payload_hash(payload: Mapping[str, Any]) -> str:
    hash_payload = {field: payload.get(field) for field in STOCK_RT_MIN_FIELDS}
    encoded = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
