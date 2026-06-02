from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.realtime.market_clock import RealtimeMarketClock
from src.foundation.realtime.runtime_config import get_realtime_stock_rt_daily_config, get_realtime_stock_rt_min_config, normalize_stock_rt_min_freq
from src.foundation.realtime.state_store import RealtimeFeedUnavailable, RealtimeStateStore


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class RealtimeSnapshotReadResult:
    feed_key: str
    batch_id: str
    received_at: str | None
    published_at: str | None
    stale: bool
    stale_after_seconds: int
    collection_status: str
    items: tuple[dict[str, Any], ...]
    missing_ts_codes: tuple[str, ...]
    freq: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "feed_key": self.feed_key,
            "batch_id": self.batch_id,
            "received_at": self.received_at,
            "published_at": self.published_at,
            "stale": self.stale,
            "stale_after_seconds": self.stale_after_seconds,
            "collection_status": self.collection_status,
            "items": [dict(item) for item in self.items],
            "missing_ts_codes": list(self.missing_ts_codes),
        }
        if self.freq is not None:
            payload["freq"] = self.freq
        return payload


class RealtimeSnapshotReader:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))

    def read_stock_rt_daily_snapshot(self, session: Session, *, ts_codes: Sequence[str]) -> RealtimeSnapshotReadResult:
        config = get_realtime_stock_rt_daily_config(session)
        return self._read_snapshot(
            session,
            feed_key=config.feed_key,
            ts_codes=ts_codes,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            stale_after_seconds=config.stale_after_seconds,
            unavailable_subject="实时行情流",
        )

    def read_stock_rt_min_snapshot(self, session: Session, *, freq: str, ts_codes: Sequence[str]) -> RealtimeSnapshotReadResult:
        config = get_realtime_stock_rt_min_config(session)
        normalized_freq = normalize_stock_rt_min_freq(freq)
        feed_key = config.feed_key_for_freq(normalized_freq)
        return self._read_snapshot(
            session,
            feed_key=feed_key,
            ts_codes=ts_codes,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            stale_after_seconds=config.stale_after_seconds,
            unavailable_subject="实时分钟行情流",
            freq=normalized_freq,
        )

    def _read_snapshot(
        self,
        session: Session,
        *,
        feed_key: str,
        ts_codes: Sequence[str],
        exchange: str,
        collection_sessions: str,
        stale_after_seconds: int,
        unavailable_subject: str,
        freq: str | None = None,
    ) -> RealtimeSnapshotReadResult:
        batch_id = self._store.get_current_batch_id(feed_key)
        if not batch_id:
            raise RealtimeFeedUnavailable(f"{unavailable_subject}尚未发布可读批次")
        meta = self._store.get_batch_meta(feed_key, batch_id)
        if meta is None:
            raise RealtimeFeedUnavailable(f"{unavailable_subject}当前批次缺少元信息")
        snapshots_by_code = self._store.get_snapshots(feed_key, batch_id, ts_codes)

        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock = RealtimeMarketClock().resolve(
            session,
            exchange=exchange,
            collection_sessions=collection_sessions,
            now=now,
        )
        age_seconds = _age_seconds(meta.get("published_at"), now)
        stale = clock.collection_status == "open" and age_seconds is not None and age_seconds > stale_after_seconds
        items = tuple(dict(snapshots_by_code[code]) for code in ts_codes if code in snapshots_by_code)
        return RealtimeSnapshotReadResult(
            feed_key=feed_key,
            freq=freq,
            batch_id=batch_id,
            received_at=_string_or_none(meta.get("received_at")),
            published_at=_string_or_none(meta.get("published_at")),
            stale=stale,
            stale_after_seconds=stale_after_seconds,
            collection_status=clock.collection_status,
            items=items,
            missing_ts_codes=tuple(code for code in ts_codes if code not in snapshots_by_code),
        )


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
