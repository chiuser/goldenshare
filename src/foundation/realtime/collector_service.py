from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.realtime.feed_config import RealtimeRuntimeConfig, get_realtime_runtime_config
from src.foundation.realtime.state_store import RealtimeStateStore
from src.foundation.realtime.stock_rt_daily import StockRtDailyCollector, StockRtDailyCycleResult
from src.foundation.realtime.stock_rt_min import StockRtMinCollector, StockRtMinCycleResult


@dataclass(frozen=True, slots=True)
class RealtimeCollectorFeedRun:
    feed_key: str
    status: str
    collection_status: str
    batch_id: str | None
    fetched_rows: int
    snapshot_count: int
    delta_count: int
    invalid_count: int
    freq: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class RealtimeCollectorCycleResult:
    feed_runs: tuple[RealtimeCollectorFeedRun, ...]
    next_sleep_seconds: float


class RealtimeCollectorService:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        config: RealtimeRuntimeConfig | None = None,
        daily_collector: StockRtDailyCollector | None = None,
        stock_rt_min_collector: StockRtMinCollector | None = None,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        self._config = config or get_realtime_runtime_config()
        self._daily_collector = daily_collector or StockRtDailyCollector(store=store, config=self._config.stock_rt_daily)
        self._stock_rt_min_collector = stock_rt_min_collector or StockRtMinCollector(store=store, config=self._config.stock_rt_min)
        self._monotonic_provider = monotonic_provider or time.monotonic
        self._next_due_at: dict[str, float] = {}

    def run_due_cycle(self, session: Session) -> RealtimeCollectorCycleResult:
        now = self._monotonic_provider()
        feed_runs: list[RealtimeCollectorFeedRun] = []
        daily_feed_key = self._config.stock_rt_daily.feed_key
        if self._is_due(daily_feed_key, now=now):
            try:
                feed_runs.append(_from_daily_result(daily_feed_key, self._daily_collector.run_cycle(session)))
            except Exception as exc:
                feed_runs.append(_failed_feed_run(feed_key=daily_feed_key, message=str(exc)))
            self._mark_scheduled(daily_feed_key, interval_seconds=self._config.stock_rt_daily.poll_interval_seconds, now=now)

        if self._config.stock_rt_min.enabled:
            for freq in self._config.stock_rt_min.enabled_freqs:
                feed_key = self._config.stock_rt_min.feed_key_for_freq(freq)
                if not self._is_due(feed_key, now=now):
                    continue
                try:
                    feed_runs.append(_from_min_result(self._stock_rt_min_collector.run_freq_cycle(session, freq=freq)))
                except Exception as exc:
                    feed_runs.append(_failed_feed_run(feed_key=feed_key, freq=freq, message=str(exc)))
                self._mark_scheduled(feed_key, interval_seconds=self._config.stock_rt_min.poll_interval_seconds, now=now)

        return RealtimeCollectorCycleResult(
            feed_runs=tuple(feed_runs),
            next_sleep_seconds=self.seconds_until_next_due(),
        )

    def seconds_until_next_due(self) -> float:
        if not self._next_due_at:
            return 0.1
        now = self._monotonic_provider()
        return max(min(self._next_due_at.values()) - now, 0.1)

    def _is_due(self, feed_key: str, *, now: float) -> bool:
        due_at = self._next_due_at.get(feed_key)
        return due_at is None or now >= due_at

    def _mark_scheduled(self, feed_key: str, *, interval_seconds: int, now: float) -> None:
        self._next_due_at[feed_key] = now + interval_seconds


def _from_daily_result(feed_key: str, result: StockRtDailyCycleResult) -> RealtimeCollectorFeedRun:
    return RealtimeCollectorFeedRun(
        feed_key=feed_key,
        status=result.status,
        collection_status=result.collection_status,
        batch_id=result.batch_id,
        fetched_rows=result.fetched_rows,
        snapshot_count=result.snapshot_count,
        delta_count=result.delta_count,
        invalid_count=0,
        message=result.message,
    )


def _from_min_result(result: StockRtMinCycleResult) -> RealtimeCollectorFeedRun:
    return RealtimeCollectorFeedRun(
        feed_key=result.feed_key,
        freq=result.freq,
        status=result.status,
        collection_status=result.collection_status,
        batch_id=result.batch_id,
        fetched_rows=result.fetched_rows,
        snapshot_count=result.snapshot_count,
        delta_count=result.delta_count,
        invalid_count=result.invalid_count,
        message=result.message,
    )


def _failed_feed_run(*, feed_key: str, message: str, freq: str | None = None) -> RealtimeCollectorFeedRun:
    return RealtimeCollectorFeedRun(
        feed_key=feed_key,
        freq=freq,
        status="degraded",
        collection_status="unknown",
        batch_id=None,
        fetched_rows=0,
        snapshot_count=0,
        delta_count=0,
        invalid_count=0,
        message=message,
    )
