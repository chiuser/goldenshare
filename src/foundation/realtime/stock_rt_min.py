from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import time
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.clients import TushareHttpClient
from src.foundation.realtime.constants import (
    STOCK_RT_MIN_SOURCE,
    STOCK_RT_MIN_SOURCE_API_NAME,
)
from src.foundation.realtime.feed_config import RealtimeStockRtMinConfig, get_realtime_stock_rt_min_config, normalize_stock_rt_min_freq
from src.foundation.realtime.state_store import RealtimePublishResult, RealtimeStateStore
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
    fetched_rows: int = 0
    snapshot_count: int = 0
    invalid_count: int = 0
    invalid_reason_counts: dict[str, int] | None = None
    delta_count: int = 0
    batch_id: str | None = None
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
        now_provider: Any | None = None,
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
        publish_result = self._store.publish_batch(
            feed_key=feed_key,
            batch_id=batch_id,
            snapshots=normalize_result.snapshots,
            meta={
                "received_at": received_at.isoformat(),
                "published_at": self._now_provider().astimezone(CN_TIMEZONE).isoformat(),
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
        return _build_cycle_result(
            freq=normalized_freq,
            feed_key=feed_key,
            batch_id=batch_id,
            fetched_rows=len(fetch_result.rows),
            snapshot_count=len(normalize_result.snapshots),
            invalid_count=normalize_result.invalid_count,
            invalid_reason_counts=normalize_result.invalid_reason_counts,
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
    fetched_rows: int,
    snapshot_count: int,
    invalid_count: int,
    invalid_reason_counts: dict[str, int],
    publish_result: RealtimePublishResult,
    delta_count: int,
) -> StockRtMinCycleResult:
    del publish_result
    return StockRtMinCycleResult(
        status="ok",
        freq=freq,
        feed_key=feed_key,
        fetched_rows=fetched_rows,
        snapshot_count=snapshot_count,
        invalid_count=invalid_count,
        invalid_reason_counts=invalid_reason_counts,
        delta_count=delta_count,
        batch_id=batch_id,
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
