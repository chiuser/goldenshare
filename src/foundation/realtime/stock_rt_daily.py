from __future__ import annotations

from collections.abc import Callable, Sequence
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
from src.foundation.config.settings import get_settings
from src.foundation.realtime.constants import (
    STOCK_RT_DAILY_FEED_KEY,
    STOCK_RT_DAILY_SOURCE,
    STOCK_RT_DAILY_SOURCE_API_NAME,
)
from src.foundation.realtime.market_clock import RealtimeMarketClock
from src.foundation.realtime.state_store import RealtimePublishResult, RealtimeStateStore, RealtimeStateStoreUnavailable


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
STOCK_RT_DAILY_FIELDS = (
    "ts_code",
    "name",
    "pre_close",
    "high",
    "open",
    "low",
    "close",
    "vol",
    "amount",
    "num",
    "ask_price1",
    "ask_volume1",
    "bid_price1",
    "bid_volume1",
    "trade_time",
)
LEASE_TTL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class StockRtDailyFetchResult:
    rows: list[dict[str, Any]]
    source_elapsed_ms: float
    request_params: dict[str, str]


@dataclass(frozen=True, slots=True)
class StockRtDailyCycleResult:
    status: str
    collection_status: str
    fetched_rows: int = 0
    snapshot_count: int = 0
    delta_count: int = 0
    batch_id: str | None = None
    message: str | None = None


class TushareStockRtDailyProvider:
    def __init__(
        self,
        *,
        client: TushareHttpClient | None = None,
        ts_code_pattern: str | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client or TushareHttpClient()
        self._ts_code_pattern = ts_code_pattern or settings.realtime_stock_rt_daily_ts_code_pattern

    def fetch_all_market(self) -> StockRtDailyFetchResult:
        params = {"ts_code": self._ts_code_pattern}
        started = time.perf_counter()
        rows = self._client.call(STOCK_RT_DAILY_SOURCE_API_NAME, params=params, fields=STOCK_RT_DAILY_FIELDS)
        return StockRtDailyFetchResult(
            rows=rows,
            source_elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            request_params=params,
        )


class StockRtDailyCollector:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        provider: TushareStockRtDailyProvider | None = None,
        clock: RealtimeMarketClock | None = None,
        now_provider: Callable[[], datetime] | None = None,
        collector_id: str | None = None,
    ) -> None:
        self._store = store
        self._provider = provider or TushareStockRtDailyProvider()
        self._clock = clock or RealtimeMarketClock()
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))
        self._collector_id = collector_id or f"{socket.gethostname()}:{os.getpid()}"
        self._request_timestamps: list[float] = []

    def run_cycle(self, session: Session) -> StockRtDailyCycleResult:
        try:
            return self._run_cycle(session)
        except RealtimeStateStoreUnavailable as exc:
            return StockRtDailyCycleResult(status="unavailable", collection_status="unknown", message=str(exc))

    def _run_cycle(self, session: Session) -> StockRtDailyCycleResult:
        settings = get_settings()
        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock_context = self._clock.resolve(
            session,
            exchange=settings.default_exchange,
            collection_sessions=settings.realtime_stock_rt_daily_collection_sessions,
            now=now,
        )
        if not settings.realtime_stock_rt_daily_enabled:
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
            return StockRtDailyCycleResult(status="idle", collection_status="disabled", message="feed disabled")

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
            return StockRtDailyCycleResult(status="idle", collection_status=clock_context.collection_status)

        if not self._store.acquire_lease(STOCK_RT_DAILY_FEED_KEY, owner=self._collector_id, ttl_seconds=LEASE_TTL_SECONDS):
            return StockRtDailyCycleResult(status="skipped", collection_status="open", message="collector lease not acquired")

        try:
            return self._run_open_cycle(now=now, is_trading_day=clock_context.is_trading_day)
        except Exception as exc:
            self._record_error(exc, now=now)
            return StockRtDailyCycleResult(status="degraded", collection_status="open", message=str(exc))
        finally:
            try:
                self._store.release_lease(STOCK_RT_DAILY_FEED_KEY, owner=self._collector_id)
            except RealtimeStateStoreUnavailable:
                pass

    def _run_open_cycle(self, *, now: datetime, is_trading_day: bool) -> StockRtDailyCycleResult:
        settings = get_settings()
        requested_at = now.isoformat()
        self._record_request_timestamp()
        fetch_result = self._provider.fetch_all_market()
        received_at = self._now_provider().astimezone(CN_TIMEZONE)
        batch_id = build_batch_id(received_at)
        snapshots = normalize_stock_rt_daily_rows(fetch_result.rows, received_at=received_at)
        previous_batch_id = self._store.get_current_batch_id(STOCK_RT_DAILY_FEED_KEY)
        delta_snapshots = self._build_delta_snapshots(previous_batch_id=previous_batch_id, snapshots=snapshots)
        write_started = time.perf_counter()
        publish_result = self._store.publish_batch(
            feed_key=STOCK_RT_DAILY_FEED_KEY,
            batch_id=batch_id,
            snapshots=snapshots,
            meta={
                "received_at": received_at.isoformat(),
                "published_at": self._now_provider().astimezone(CN_TIMEZONE).isoformat(),
                "source_elapsed_ms": fetch_result.source_elapsed_ms,
                "source_row_count": len(fetch_result.rows),
                "request_params": fetch_result.request_params,
            },
            ttl_seconds=settings.realtime_stock_rt_daily_snapshot_ttl_seconds,
            keep_recent_batches=settings.realtime_stock_rt_daily_keep_recent_batches,
            batch_stream_maxlen=settings.realtime_stock_rt_daily_batch_stream_maxlen,
            delta_stream_maxlen=settings.realtime_stock_rt_daily_delta_stream_maxlen,
            delta_snapshots=delta_snapshots,
        )
        write_elapsed_ms = round((time.perf_counter() - write_started) * 1000, 2)
        self._record_success_health(
            publish_result=publish_result,
            batch_id=batch_id,
            requested_at=requested_at,
            received_at=received_at,
            source_elapsed_ms=fetch_result.source_elapsed_ms,
            write_elapsed_ms=write_elapsed_ms,
            source_row_count=len(fetch_result.rows),
            snapshot_count=len(snapshots),
            delta_count=len(delta_snapshots),
            is_trading_day=is_trading_day,
        )
        return StockRtDailyCycleResult(
            status="ok",
            collection_status="open",
            fetched_rows=len(fetch_result.rows),
            snapshot_count=len(snapshots),
            delta_count=len(delta_snapshots),
            batch_id=batch_id,
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
            STOCK_RT_DAILY_FEED_KEY,
            previous_batch_id,
            [snapshot["ts_code"] for snapshot in snapshots],
        )
        return [
            snapshot
            for snapshot in snapshots
            if previous.get(snapshot["ts_code"], {}).get("raw_payload_hash") != snapshot.get("raw_payload_hash")
        ]

    def _record_request_timestamp(self) -> None:
        now_monotonic = time.monotonic()
        self._request_timestamps = [item for item in self._request_timestamps if now_monotonic - item <= 60]
        self._request_timestamps.append(now_monotonic)

    def _record_success_health(
        self,
        *,
        publish_result: RealtimePublishResult,
        batch_id: str,
        requested_at: str,
        received_at: datetime,
        source_elapsed_ms: float,
        write_elapsed_ms: float,
        source_row_count: int,
        snapshot_count: int,
        delta_count: int,
        is_trading_day: bool,
    ) -> None:
        published_at = self._now_provider().astimezone(CN_TIMEZONE).isoformat()
        self._merge_health(
            {
                "status": "ok",
                "enabled": True,
                "collector_running": True,
                "collector_id": self._collector_id,
                "last_request_at": requested_at,
                "last_success_at": published_at,
                "last_error_at": None,
                "last_error_message": None,
                "current_batch_id": batch_id,
                "current_batch_received_at": received_at.isoformat(),
                "current_batch_published_at": published_at,
                "source_elapsed_ms": source_elapsed_ms,
                "write_elapsed_ms": write_elapsed_ms,
                "source_row_count": source_row_count,
                "snapshot_count": snapshot_count,
                "request_count_last_minute": len(self._request_timestamps),
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
                "last_error_at": now.isoformat(),
                "last_error_message": str(exc),
                "collection_status": "open",
                "request_count_last_minute": len(self._request_timestamps),
            }
        )

    def _merge_health(self, payload: dict[str, Any]) -> None:
        try:
            existing = self._store.get_health(STOCK_RT_DAILY_FEED_KEY) or {}
            existing.update(payload)
            self._store.set_health(STOCK_RT_DAILY_FEED_KEY, existing)
        except RealtimeStateStoreUnavailable:
            raise


def normalize_stock_rt_daily_rows(rows: Sequence[dict[str, Any]], *, received_at: datetime) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if not ts_code:
            continue
        payload = {field: _normalize_value(row.get(field)) for field in STOCK_RT_DAILY_FIELDS}
        payload["ts_code"] = ts_code
        payload["source"] = STOCK_RT_DAILY_SOURCE
        payload["source_api_name"] = STOCK_RT_DAILY_SOURCE_API_NAME
        payload["received_at"] = received_at.isoformat()
        payload["raw_payload_hash"] = _payload_hash(payload)
        snapshots.append(payload)
    return snapshots


def build_batch_id(value: datetime) -> str:
    return value.astimezone(CN_TIMEZONE).strftime("%Y%m%dT%H%M%S.%f%z")


def _normalize_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _payload_hash(payload: dict[str, Any]) -> str:
    hash_payload = {field: payload.get(field) for field in STOCK_RT_DAILY_FIELDS}
    encoded = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
