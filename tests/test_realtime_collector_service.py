from __future__ import annotations

from dataclasses import dataclass

from src.foundation.config.settings import get_settings
from src.foundation.realtime import InMemoryRealtimeStateStore, RealtimeCollectorService
from src.foundation.realtime.stock_rt_daily import StockRtDailyCycleResult
from src.foundation.realtime.stock_rt_min import StockRtMinCycleResult


@dataclass
class MutableClock:
    value: float

    def __call__(self) -> float:
        return self.value


class FakeDailyCollector:
    def __init__(self) -> None:
        self.calls = 0

    def run_cycle(self, _session) -> StockRtDailyCycleResult:
        self.calls += 1
        return StockRtDailyCycleResult(
            status="ok",
            collection_status="open",
            fetched_rows=10,
            snapshot_count=10,
            delta_count=1,
            batch_id=f"daily-{self.calls}",
        )


class FakeMinuteCollector:
    def __init__(self, *, fail_freq: str | None = None) -> None:
        self.fail_freq = fail_freq
        self.calls: list[str] = []

    def run_freq_cycle(self, _session, *, freq: str) -> StockRtMinCycleResult:
        self.calls.append(freq)
        if freq == self.fail_freq:
            raise RuntimeError(f"{freq} failed")
        return StockRtMinCycleResult(
            status="ok",
            freq=freq,
            feed_key=f"tushare_stock_rt_min_{freq.lower()}",
            collection_status="open",
            fetched_rows=20,
            snapshot_count=20,
            delta_count=2,
            invalid_count=0,
            batch_id=f"minute-{freq}",
        )


def test_realtime_collector_service_does_not_schedule_minutes_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "false")
    get_settings.cache_clear()
    daily = FakeDailyCollector()
    minute = FakeMinuteCollector()
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        daily_collector=daily,  # type: ignore[arg-type]
        stock_rt_min_collector=minute,  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    assert daily.calls == 1
    assert minute.calls == []
    assert [item.feed_key for item in result.feed_runs] == ["tushare_stock_rt_k"]


def test_realtime_collector_service_schedules_daily_and_minute_feeds_by_independent_due_time(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,5MIN")
    get_settings.cache_clear()
    clock = MutableClock(100.0)
    daily = FakeDailyCollector()
    minute = FakeMinuteCollector()
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        daily_collector=daily,  # type: ignore[arg-type]
        stock_rt_min_collector=minute,  # type: ignore[arg-type]
        monotonic_provider=clock,
    )

    first = service.run_due_cycle(None)  # type: ignore[arg-type]
    clock.value = 106.0
    second = service.run_due_cycle(None)  # type: ignore[arg-type]
    clock.value = 160.0
    third = service.run_due_cycle(None)  # type: ignore[arg-type]

    assert [item.feed_key for item in first.feed_runs] == [
        "tushare_stock_rt_k",
        "tushare_stock_rt_min_1min",
        "tushare_stock_rt_min_5min",
    ]
    assert [item.feed_key for item in second.feed_runs] == ["tushare_stock_rt_k"]
    assert [item.feed_key for item in third.feed_runs] == [
        "tushare_stock_rt_k",
        "tushare_stock_rt_min_1min",
        "tushare_stock_rt_min_5min",
    ]
    assert minute.calls == ["1MIN", "5MIN", "1MIN", "5MIN"]


def test_realtime_collector_service_isolates_single_minute_frequency_failure(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,5MIN")
    get_settings.cache_clear()
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        daily_collector=FakeDailyCollector(),  # type: ignore[arg-type]
        stock_rt_min_collector=FakeMinuteCollector(fail_freq="1MIN"),  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    by_feed = {item.feed_key: item for item in result.feed_runs}
    assert by_feed["tushare_stock_rt_min_1min"].status == "degraded"
    assert "1MIN failed" in (by_feed["tushare_stock_rt_min_1min"].message or "")
    assert by_feed["tushare_stock_rt_min_5min"].status == "ok"
    assert by_feed["tushare_stock_rt_k"].status == "ok"
