from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from src.foundation.realtime.redis_keys import RealtimeRedisKeys


class RealtimeStateStoreUnavailable(RuntimeError):
    pass


class RealtimeFeedUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RealtimePublishResult:
    batch_event_id: str | None
    delta_event_ids: tuple[str, ...]


class RealtimeStateStore(Protocol):
    def ping(self) -> bool:
        ...

    def publish_batch(
        self,
        *,
        feed_key: str,
        batch_id: str,
        snapshots: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        ttl_seconds: int,
        keep_recent_batches: int,
        batch_stream_maxlen: int,
        delta_stream_maxlen: int,
        delta_snapshots: Sequence[Mapping[str, Any]] | None = None,
    ) -> RealtimePublishResult:
        ...

    def get_current_batch_id(self, feed_key: str) -> str | None:
        ...

    def get_batch_meta(self, feed_key: str, batch_id: str) -> dict[str, Any] | None:
        ...

    def get_batch_snapshot_count(self, feed_key: str, batch_id: str) -> int:
        ...

    def get_snapshots(self, feed_key: str, batch_id: str, ts_codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        ...

    def get_health(self, feed_key: str) -> dict[str, Any] | None:
        ...

    def set_health(self, feed_key: str, health: Mapping[str, Any]) -> None:
        ...


class RedisRealtimeStateStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_url(cls, redis_url: str) -> "RedisRealtimeStateStore":
        try:
            from redis import Redis
        except Exception as exc:  # pragma: no cover - depends on optional runtime package presence
            raise RealtimeStateStoreUnavailable("redis Python package is not installed") from exc
        return cls(Redis.from_url(redis_url, decode_responses=True))

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def publish_batch(
        self,
        *,
        feed_key: str,
        batch_id: str,
        snapshots: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        ttl_seconds: int,
        keep_recent_batches: int,
        batch_stream_maxlen: int,
        delta_stream_maxlen: int,
        delta_snapshots: Sequence[Mapping[str, Any]] | None = None,
    ) -> RealtimePublishResult:
        keys = RealtimeRedisKeys(feed_key)
        normalized_snapshots = _normalize_snapshots(feed_key=feed_key, batch_id=batch_id, snapshots=snapshots)
        normalized_delta_snapshots = _normalize_snapshots(feed_key=feed_key, batch_id=batch_id, snapshots=delta_snapshots or ())
        payload_meta = {
            "feed_key": feed_key,
            "batch_id": batch_id,
            "snapshot_count": len(normalized_snapshots),
            **dict(meta),
        }
        score = _published_score(payload_meta)
        batch_event = _stringify_event(
            {
                "event_type": "batch_published",
                "feed_key": feed_key,
                "batch_id": batch_id,
                "snapshot_count": len(normalized_snapshots),
                "source_row_count": payload_meta.get("source_row_count", len(normalized_snapshots)),
                "delta_count": len(normalized_delta_snapshots),
                "published_at": payload_meta.get("published_at"),
            }
        )
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.delete(keys.batch_index(batch_id))
            for ts_code, snapshot in normalized_snapshots.items():
                pipe.setex(keys.batch_snapshot(batch_id, ts_code), ttl_seconds, _json_dump(snapshot))
                pipe.sadd(keys.batch_index(batch_id), ts_code)
            pipe.expire(keys.batch_index(batch_id), ttl_seconds)
            pipe.setex(keys.batch_meta(batch_id), ttl_seconds, _json_dump(payload_meta))
            pipe.zadd(keys.batches(), {batch_id: score})
            pipe.set(keys.current_batch(), batch_id)
            pipe.xadd(keys.batch_stream(), batch_event, maxlen=batch_stream_maxlen, approximate=True)
            for ts_code, snapshot in normalized_delta_snapshots.items():
                pipe.xadd(
                    keys.delta_stream(),
                    _stringify_event({"event_type": "quote_changed", "ts_code": ts_code, **snapshot}),
                    maxlen=delta_stream_maxlen,
                    approximate=True,
                )
            results = pipe.execute()
            stream_result_offset = 5 + (len(normalized_snapshots) * 2)
            batch_event_id = _coerce_text(results[stream_result_offset]) if len(results) > stream_result_offset else None
            delta_event_ids = tuple(_coerce_text(item) for item in results[stream_result_offset + 1 :])
            self._cleanup_old_batches(keys, keep_recent_batches=keep_recent_batches)
            return RealtimePublishResult(batch_event_id=batch_event_id, delta_event_ids=delta_event_ids)
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def get_current_batch_id(self, feed_key: str) -> str | None:
        try:
            return _coerce_optional_text(self._client.get(RealtimeRedisKeys(feed_key).current_batch()))
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def get_batch_meta(self, feed_key: str, batch_id: str) -> dict[str, Any] | None:
        try:
            return _json_load(self._client.get(RealtimeRedisKeys(feed_key).batch_meta(batch_id)))
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def get_batch_snapshot_count(self, feed_key: str, batch_id: str) -> int:
        try:
            return int(self._client.scard(RealtimeRedisKeys(feed_key).batch_index(batch_id)))
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def get_snapshots(self, feed_key: str, batch_id: str, ts_codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        keys = RealtimeRedisKeys(feed_key)
        normalized_codes = [_normalize_ts_code(item) for item in ts_codes]
        try:
            payloads = self._client.mget([keys.batch_snapshot(batch_id, code) for code in normalized_codes])
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc
        results: dict[str, dict[str, Any]] = {}
        for ts_code, payload in zip(normalized_codes, payloads, strict=True):
            item = _json_load(payload)
            if item is not None:
                results[ts_code] = item
        return results

    def get_health(self, feed_key: str) -> dict[str, Any] | None:
        try:
            return _json_load(self._client.get(RealtimeRedisKeys(feed_key).health()))
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def set_health(self, feed_key: str, health: Mapping[str, Any]) -> None:
        try:
            self._client.set(RealtimeRedisKeys(feed_key).health(), _json_dump(dict(health)))
        except Exception as exc:
            raise RealtimeStateStoreUnavailable(str(exc)) from exc

    def _cleanup_old_batches(self, keys: RealtimeRedisKeys, *, keep_recent_batches: int) -> None:
        if keep_recent_batches <= 0:
            return
        old_batch_ids = [_coerce_text(item) for item in self._client.zrange(keys.batches(), 0, -keep_recent_batches - 1)]
        if not old_batch_ids:
            return
        pipe = self._client.pipeline(transaction=True)
        for old_batch_id in old_batch_ids:
            snapshot_codes = [_coerce_text(item) for item in self._client.smembers(keys.batch_index(old_batch_id))]
            for ts_code in snapshot_codes:
                pipe.delete(keys.batch_snapshot(old_batch_id, ts_code))
            pipe.delete(keys.batch_index(old_batch_id))
            pipe.delete(keys.batch_meta(old_batch_id))
        pipe.zrem(keys.batches(), *old_batch_ids)
        pipe.execute()


class InMemoryRealtimeStateStore:
    def __init__(self) -> None:
        self.current_batches: dict[str, str] = {}
        self.batch_meta: dict[tuple[str, str], dict[str, Any]] = {}
        self.snapshots: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self.health: dict[str, dict[str, Any]] = {}
        self.batch_order: dict[str, list[str]] = {}
        self.batch_stream_ids: dict[str, str] = {}
        self.delta_stream_ids: dict[str, str] = {}
        self._event_index = 0

    def ping(self) -> bool:
        return True

    def publish_batch(
        self,
        *,
        feed_key: str,
        batch_id: str,
        snapshots: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        ttl_seconds: int,
        keep_recent_batches: int,
        batch_stream_maxlen: int,
        delta_stream_maxlen: int,
        delta_snapshots: Sequence[Mapping[str, Any]] | None = None,
    ) -> RealtimePublishResult:
        del ttl_seconds, batch_stream_maxlen, delta_stream_maxlen
        normalized_snapshots = _normalize_snapshots(feed_key=feed_key, batch_id=batch_id, snapshots=snapshots)
        self.snapshots[(feed_key, batch_id)] = normalized_snapshots
        self.batch_meta[(feed_key, batch_id)] = {
            "feed_key": feed_key,
            "batch_id": batch_id,
            "snapshot_count": len(normalized_snapshots),
            **dict(meta),
        }
        order = self.batch_order.setdefault(feed_key, [])
        if batch_id not in order:
            order.append(batch_id)
        self.current_batches[feed_key] = batch_id
        batch_event_id = self._next_event_id()
        delta_event_ids = tuple(self._next_event_id() for _ in _normalize_snapshots(feed_key=feed_key, batch_id=batch_id, snapshots=delta_snapshots or ()))
        self.batch_stream_ids[feed_key] = batch_event_id
        if delta_event_ids:
            self.delta_stream_ids[feed_key] = delta_event_ids[-1]
        self._cleanup_old_batches(feed_key, keep_recent_batches=keep_recent_batches)
        return RealtimePublishResult(batch_event_id=batch_event_id, delta_event_ids=delta_event_ids)

    def get_current_batch_id(self, feed_key: str) -> str | None:
        return self.current_batches.get(feed_key)

    def get_batch_meta(self, feed_key: str, batch_id: str) -> dict[str, Any] | None:
        item = self.batch_meta.get((feed_key, batch_id))
        return dict(item) if item is not None else None

    def get_batch_snapshot_count(self, feed_key: str, batch_id: str) -> int:
        return len(self.snapshots.get((feed_key, batch_id), {}))

    def get_snapshots(self, feed_key: str, batch_id: str, ts_codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        batch_snapshots = self.snapshots.get((feed_key, batch_id), {})
        return {
            code: dict(batch_snapshots[code])
            for code in (_normalize_ts_code(item) for item in ts_codes)
            if code in batch_snapshots
        }

    def get_health(self, feed_key: str) -> dict[str, Any] | None:
        item = self.health.get(feed_key)
        return dict(item) if item is not None else None

    def set_health(self, feed_key: str, health: Mapping[str, Any]) -> None:
        self.health[feed_key] = dict(health)

    def _next_event_id(self) -> str:
        self._event_index += 1
        return f"{int(time.time() * 1000)}-{self._event_index}"

    def _cleanup_old_batches(self, feed_key: str, *, keep_recent_batches: int) -> None:
        if keep_recent_batches <= 0:
            return
        order = self.batch_order.setdefault(feed_key, [])
        old_batch_ids = order[:-keep_recent_batches]
        self.batch_order[feed_key] = order[-keep_recent_batches:]
        for batch_id in old_batch_ids:
            self.snapshots.pop((feed_key, batch_id), None)
            self.batch_meta.pop((feed_key, batch_id), None)


class UnavailableRealtimeStateStore:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def ping(self) -> bool:
        raise RealtimeStateStoreUnavailable(self.reason)

    def publish_batch(self, **_kwargs: Any) -> RealtimePublishResult:
        raise RealtimeStateStoreUnavailable(self.reason)

    def get_current_batch_id(self, _feed_key: str) -> str | None:
        raise RealtimeStateStoreUnavailable(self.reason)

    def get_batch_meta(self, _feed_key: str, _batch_id: str) -> dict[str, Any] | None:
        raise RealtimeStateStoreUnavailable(self.reason)

    def get_batch_snapshot_count(self, _feed_key: str, _batch_id: str) -> int:
        raise RealtimeStateStoreUnavailable(self.reason)

    def get_snapshots(self, _feed_key: str, _batch_id: str, _ts_codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        raise RealtimeStateStoreUnavailable(self.reason)

    def get_health(self, _feed_key: str) -> dict[str, Any] | None:
        raise RealtimeStateStoreUnavailable(self.reason)

    def set_health(self, _feed_key: str, _health: Mapping[str, Any]) -> None:
        raise RealtimeStateStoreUnavailable(self.reason)


def build_realtime_state_store(redis_url: str) -> RealtimeStateStore:
    try:
        return RedisRealtimeStateStore.from_url(redis_url)
    except RealtimeStateStoreUnavailable as exc:
        return UnavailableRealtimeStateStore(str(exc))


def _normalize_snapshots(
    *,
    feed_key: str,
    batch_id: str,
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        ts_code = _normalize_ts_code(snapshot.get("ts_code"))
        if not ts_code:
            continue
        normalized[ts_code] = {
            "feed_key": feed_key,
            "batch_id": batch_id,
            **dict(snapshot),
            "ts_code": ts_code,
        }
    return normalized


def _normalize_ts_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _json_dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _json_load(value: Any) -> dict[str, Any] | None:
    text = _coerce_optional_text(value)
    if not text:
        return None
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else None


def _stringify_event(value: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _coerce_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _coerce_text(value)


def _published_score(meta: Mapping[str, Any]) -> float:
    for key in ("published_at", "received_at"):
        value = meta.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if value:
            try:
                from datetime import datetime

                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return time.time()
