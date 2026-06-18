from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import socket
import time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.clients import TushareHttpClient
from src.foundation.realtime.constants import ETF_RT_DAILY_SOURCE, ETF_RT_DAILY_SOURCE_API_NAME
from src.foundation.realtime.market_clock import RealtimeMarketClock
from src.foundation.realtime.runtime_config import RealtimeEtfRtDailyConfig, get_realtime_etf_rt_daily_config
from src.foundation.realtime.state_store import RealtimePublishResult, RealtimeStateStore, RealtimeStateStoreUnavailable
from src.foundation.realtime.stock_rt_daily import build_batch_id


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
ETF_RT_DAILY_FIELDS = (
    "ts_code",
    "name",
    "trade_time",
    "pre_close",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "num",
    "ask_price1",
    "bid_price1",
    "ask_volume1",
    "bid_volume1",
)


@dataclass(frozen=True, slots=True)
class EtfRtDailyFetchResult:
    rows: list[dict[str, Any]]
    source_elapsed_ms: float
    request_segments: tuple[dict[str, str], ...]
    segment_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class EtfRtDailyNormalizeResult:
    snapshots: list[dict[str, Any]]
    invalid_count: int
    invalid_reason_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class EtfRtDailyCycleResult:
    status: str
    collection_status: str
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
    segment_counts: dict[str, int] | None = None
    message: str | None = None


class TushareEtfRtDailyProvider:
    def __init__(
        self,
        *,
        client: TushareHttpClient | None = None,
        config: RealtimeEtfRtDailyConfig | None = None,
    ) -> None:
        self._config = config or get_realtime_etf_rt_daily_config()
        self._client = client or TushareHttpClient(timeout=self._config.source_timeout_seconds)

    def fetch_all_market(self) -> EtfRtDailyFetchResult:
        started = time.perf_counter()
        rows: list[dict[str, Any]] = []
        request_segments: list[dict[str, str]] = []
        segment_counts: dict[str, int] = {}
        for segment in self._config.request_segments:
            params = {"ts_code": segment.ts_code, "topic": segment.topic}
            segment_rows = self._client.call(ETF_RT_DAILY_SOURCE_API_NAME, params=params, fields=ETF_RT_DAILY_FIELDS)
            segment_key = segment.market
            segment_counts[segment_key] = len(segment_rows)
            request_segments.append({"market": segment.market, "topic": segment.topic, "ts_code": segment.ts_code})
            rows.extend({**row, "request_segment": segment_key} for row in segment_rows)
        return EtfRtDailyFetchResult(
            rows=rows,
            source_elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            request_segments=tuple(request_segments),
            segment_counts=segment_counts,
        )


class EtfRtDailyCollector:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        provider: TushareEtfRtDailyProvider | None = None,
        config: RealtimeEtfRtDailyConfig | None = None,
        clock: RealtimeMarketClock | None = None,
        now_provider: Callable[[], datetime] | None = None,
        collector_id: str | None = None,
    ) -> None:
        self._config = config or get_realtime_etf_rt_daily_config()
        self._store = store
        self._provider = provider or TushareEtfRtDailyProvider(config=self._config)
        self._clock = clock or RealtimeMarketClock()
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))
        self._collector_id = collector_id or f"{socket.gethostname()}:{os.getpid()}"
        self._request_timestamps: list[float] = []

    def run_cycle(self, session: Session) -> EtfRtDailyCycleResult:
        try:
            return self._run_cycle(session)
        except RealtimeStateStoreUnavailable as exc:
            return EtfRtDailyCycleResult(status="unavailable", collection_status="unknown", message=str(exc))

    def _run_cycle(self, session: Session) -> EtfRtDailyCycleResult:
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
                {
                    "status": "idle",
                    "enabled": False,
                    "collector_running": True,
                    "collector_id": self._collector_id,
                    "collection_status": "disabled",
                    "is_trading_day": clock_context.is_trading_day,
                    "last_request_at": None,
                }
            )
            return EtfRtDailyCycleResult(status="idle", collection_status="disabled", message="feed disabled")

        if clock_context.collection_status != "open":
            self._merge_health(
                {
                    "status": "idle",
                    "enabled": True,
                    "collector_running": True,
                    "collector_id": self._collector_id,
                    "collection_status": clock_context.collection_status,
                    "is_trading_day": clock_context.is_trading_day,
                }
            )
            return EtfRtDailyCycleResult(status="idle", collection_status=clock_context.collection_status)

        if not self._store.acquire_lease(config.feed_key, owner=self._collector_id, ttl_seconds=config.lease_ttl_seconds):
            return EtfRtDailyCycleResult(status="skipped", collection_status="open", message="collector lease not acquired")

        try:
            return self._run_open_cycle(now=now, is_trading_day=clock_context.is_trading_day)
        except Exception as exc:
            self._record_error(exc, now=now)
            return EtfRtDailyCycleResult(status="degraded", collection_status="open", message=str(exc))
        finally:
            try:
                self._store.release_lease(config.feed_key, owner=self._collector_id)
            except RealtimeStateStoreUnavailable:
                pass

    def _run_open_cycle(self, *, now: datetime, is_trading_day: bool) -> EtfRtDailyCycleResult:
        config = self._config
        requested_at = now.isoformat()
        self._record_request_timestamps(count=len(config.request_segments))
        fetch_result = self._provider.fetch_all_market()
        received_at = self._now_provider().astimezone(CN_TIMEZONE)
        batch_id = build_batch_id(received_at)
        normalize_result = normalize_etf_rt_daily_rows(fetch_result.rows, received_at=received_at)
        previous_batch_id = self._store.get_current_batch_id(config.feed_key)
        delta_snapshots = self._build_delta_snapshots(previous_batch_id=previous_batch_id, snapshots=normalize_result.snapshots)
        write_started = time.perf_counter()
        published_at = self._now_provider().astimezone(CN_TIMEZONE)
        publish_result = self._store.publish_batch(
            feed_key=config.feed_key,
            batch_id=batch_id,
            snapshots=normalize_result.snapshots,
            meta={
                "received_at": received_at.isoformat(),
                "published_at": published_at.isoformat(),
                "source_elapsed_ms": fetch_result.source_elapsed_ms,
                "source_row_count": len(fetch_result.rows),
                "request_segments": list(fetch_result.request_segments),
                "segment_counts": fetch_result.segment_counts,
                "invalid_count": normalize_result.invalid_count,
                "invalid_reason_counts": normalize_result.invalid_reason_counts,
            },
            ttl_seconds=config.storage.snapshot_ttl_seconds,
            keep_recent_batches=config.storage.keep_recent_batches,
            batch_stream_maxlen=config.storage.batch_stream_maxlen,
            delta_stream_maxlen=config.storage.delta_stream_maxlen,
            delta_snapshots=delta_snapshots,
        )
        write_elapsed_ms = round((time.perf_counter() - write_started) * 1000, 2)
        self._record_success_health(
            publish_result=publish_result,
            batch_id=batch_id,
            requested_at=requested_at,
            received_at=received_at,
            published_at=published_at,
            source_elapsed_ms=fetch_result.source_elapsed_ms,
            write_elapsed_ms=write_elapsed_ms,
            source_row_count=len(fetch_result.rows),
            snapshot_count=len(normalize_result.snapshots),
            delta_count=len(delta_snapshots),
            invalid_count=normalize_result.invalid_count,
            invalid_reason_counts=normalize_result.invalid_reason_counts,
            segment_counts=fetch_result.segment_counts,
            is_trading_day=is_trading_day,
        )
        return EtfRtDailyCycleResult(
            status="ok",
            collection_status="open",
            fetched_rows=len(fetch_result.rows),
            snapshot_count=len(normalize_result.snapshots),
            invalid_count=normalize_result.invalid_count,
            invalid_reason_counts=normalize_result.invalid_reason_counts,
            delta_count=len(delta_snapshots),
            batch_id=batch_id,
            received_at=received_at.isoformat(),
            published_at=published_at.isoformat(),
            source_elapsed_ms=fetch_result.source_elapsed_ms,
            write_elapsed_ms=write_elapsed_ms,
            last_batch_event_id=publish_result.batch_event_id,
            last_delta_event_id=publish_result.delta_event_ids[-1] if publish_result.delta_event_ids else None,
            segment_counts=fetch_result.segment_counts,
        )

    def _build_delta_snapshots(
        self,
        *,
        previous_batch_id: str | None,
        snapshots: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not previous_batch_id:
            return []
        previous = self._store.get_snapshots(
            self._config.feed_key,
            previous_batch_id,
            [snapshot["ts_code"] for snapshot in snapshots],
        )
        return [
            snapshot
            for snapshot in snapshots
            if previous.get(snapshot["ts_code"], {}).get("raw_payload_hash") != snapshot.get("raw_payload_hash")
        ]

    def _record_request_timestamps(self, *, count: int) -> None:
        now_monotonic = time.monotonic()
        self._request_timestamps = [item for item in self._request_timestamps if now_monotonic - item <= 60]
        self._request_timestamps.extend(now_monotonic for _ in range(count))

    def _request_count_last_minute(self) -> int:
        now_monotonic = time.monotonic()
        self._request_timestamps = [item for item in self._request_timestamps if now_monotonic - item <= 60]
        return len(self._request_timestamps)

    def _record_success_health(
        self,
        *,
        publish_result: RealtimePublishResult,
        batch_id: str,
        requested_at: str,
        received_at: datetime,
        published_at: datetime,
        source_elapsed_ms: float,
        write_elapsed_ms: float,
        source_row_count: int,
        snapshot_count: int,
        delta_count: int,
        invalid_count: int,
        invalid_reason_counts: dict[str, int],
        segment_counts: dict[str, int],
        is_trading_day: bool,
    ) -> None:
        self._merge_health(
            {
                "status": "ok",
                "enabled": True,
                "collector_running": True,
                "collector_id": self._collector_id,
                "last_request_at": requested_at,
                "last_success_at": published_at.isoformat(),
                "last_error_at": None,
                "last_error_message": None,
                "current_batch_id": batch_id,
                "current_batch_received_at": received_at.isoformat(),
                "current_batch_published_at": published_at.isoformat(),
                "source_elapsed_ms": source_elapsed_ms,
                "write_elapsed_ms": write_elapsed_ms,
                "source_row_count": source_row_count,
                "snapshot_count": snapshot_count,
                "invalid_count": invalid_count,
                "invalid_reason_counts": invalid_reason_counts,
                "segment_counts": segment_counts,
                "request_count_last_minute": self._request_count_last_minute(),
                "is_trading_day": is_trading_day,
                "collection_status": "open",
                "last_batch_event_id": publish_result.batch_event_id,
                "last_delta_event_id": publish_result.delta_event_ids[-1] if publish_result.delta_event_ids else None,
                "delta_count_last_batch": delta_count,
            }
        )

    def _record_error(self, exc: Exception, *, now: datetime) -> None:
        self._merge_health(
            {
                "status": "degraded",
                "enabled": True,
                "collector_running": True,
                "collector_id": self._collector_id,
                "last_request_at": now.isoformat(),
                "last_error_at": now.isoformat(),
                "last_error_message": str(exc),
                "collection_status": "open",
                "request_count_last_minute": self._request_count_last_minute(),
            }
        )

    def _merge_health(self, payload: dict[str, Any]) -> None:
        existing = self._store.get_health(self._config.feed_key) or {}
        existing.update(payload)
        self._store.set_health(self._config.feed_key, existing)


def normalize_etf_rt_daily_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    received_at: datetime,
) -> EtfRtDailyNormalizeResult:
    snapshots: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            invalid_reason_counts["missing_ts_code"] = invalid_reason_counts.get("missing_ts_code", 0) + 1
            continue
        payload = {field: _normalize_value(row.get(field)) for field in ETF_RT_DAILY_FIELDS}
        payload["ts_code"] = ts_code
        payload["request_segment"] = _normalize_value(row.get("request_segment"))
        payload["source"] = ETF_RT_DAILY_SOURCE
        payload["source_api_name"] = ETF_RT_DAILY_SOURCE_API_NAME
        payload["received_at"] = received_at.isoformat()
        payload["raw_payload_hash"] = _payload_hash(payload)
        snapshots.append(payload)
    return EtfRtDailyNormalizeResult(
        snapshots=snapshots,
        invalid_count=sum(invalid_reason_counts.values()),
        invalid_reason_counts=invalid_reason_counts,
    )


def _normalize_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _payload_hash(payload: Mapping[str, Any]) -> str:
    hash_payload = {field: payload.get(field) for field in ETF_RT_DAILY_FIELDS}
    hash_payload["request_segment"] = payload.get("request_segment")
    encoded = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
