from __future__ import annotations

from dataclasses import dataclass

from src.foundation.realtime import (
    REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY,
    InMemoryRealtimeStateStore,
    RealtimeCollectorService,
)
from src.foundation.realtime.etf_rt_daily import EtfRtDailyCycleResult
from src.foundation.realtime.stock_rt_daily import StockRtDailyCycleResult
from src.foundation.realtime.stock_rt_min import StockRtMinCycleResult
from tests.realtime_runtime_config_helpers import make_realtime_runtime_config


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


class FakeEtfCollector:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def run_cycle(self, _session) -> EtfRtDailyCycleResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("ETF failed")
        return EtfRtDailyCycleResult(
            status="ok",
            collection_status="open",
            fetched_rows=30,
            snapshot_count=30,
            delta_count=3,
            invalid_count=0,
            batch_id=f"etf-{self.calls}",
        )


def test_realtime_collector_service_does_not_schedule_minutes_when_disabled() -> None:
    daily = FakeDailyCollector()
    minute = FakeMinuteCollector()
    etf = FakeEtfCollector()
    store = InMemoryRealtimeStateStore()
    service = RealtimeCollectorService(
        store=store,
        config=make_realtime_runtime_config(minute={"enabled": False}, daily_version=2, minute_version=5, etf_version=7),
        daily_collector=daily,  # type: ignore[arg-type]
        stock_rt_min_collector=minute,  # type: ignore[arg-type]
        etf_rt_daily_collector=etf,  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
        collector_id="collector-test",
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    assert daily.calls == 1
    assert minute.calls == []
    assert etf.calls == 0
    assert [item.feed_key for item in result.feed_runs] == ["tushare_stock_rt_k"]
    apply_state = store.get_health(REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY)
    assert apply_state is not None
    assert apply_state["collector_id"] == "collector-test"
    assert apply_state["objects"]["stock_rt_daily"]["version"] == 2
    assert apply_state["objects"]["stock_rt_min"]["version"] == 5
    assert apply_state["objects"]["etf_rt_daily"]["version"] == 7


def test_realtime_collector_service_schedules_daily_and_minute_feeds_by_independent_due_time(
) -> None:
    clock = MutableClock(100.0)
    daily = FakeDailyCollector()
    minute = FakeMinuteCollector()
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        config=make_realtime_runtime_config(minute={"enabled": True, "enabled_freqs": ["1MIN", "5MIN"]}),
        daily_collector=daily,  # type: ignore[arg-type]
        stock_rt_min_collector=minute,  # type: ignore[arg-type]
        etf_rt_daily_collector=FakeEtfCollector(),  # type: ignore[arg-type]
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


def test_realtime_collector_service_isolates_single_minute_frequency_failure() -> None:
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        config=make_realtime_runtime_config(minute={"enabled": True, "enabled_freqs": ["1MIN", "5MIN"]}),
        daily_collector=FakeDailyCollector(),  # type: ignore[arg-type]
        stock_rt_min_collector=FakeMinuteCollector(fail_freq="1MIN"),  # type: ignore[arg-type]
        etf_rt_daily_collector=FakeEtfCollector(),  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    by_feed = {item.feed_key: item for item in result.feed_runs}
    assert by_feed["tushare_stock_rt_min_1min"].status == "degraded"
    assert "1MIN failed" in (by_feed["tushare_stock_rt_min_1min"].message or "")
    assert by_feed["tushare_stock_rt_min_5min"].status == "ok"
    assert by_feed["tushare_stock_rt_k"].status == "ok"


def test_realtime_collector_service_schedules_etf_feed_independently() -> None:
    daily = FakeDailyCollector()
    minute = FakeMinuteCollector()
    etf = FakeEtfCollector()
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        config=make_realtime_runtime_config(
            minute={"enabled": False},
            etf={"enabled": True, "poll_interval_seconds": 60},
        ),
        daily_collector=daily,  # type: ignore[arg-type]
        stock_rt_min_collector=minute,  # type: ignore[arg-type]
        etf_rt_daily_collector=etf,  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    assert [item.feed_key for item in result.feed_runs] == ["tushare_stock_rt_k", "tushare_etf_rt_k"]
    assert etf.calls == 1


def test_realtime_collector_service_isolates_etf_failure_from_stock_feeds() -> None:
    service = RealtimeCollectorService(
        store=InMemoryRealtimeStateStore(),
        config=make_realtime_runtime_config(
            minute={"enabled": True, "enabled_freqs": ["1MIN"]},
            etf={"enabled": True},
        ),
        daily_collector=FakeDailyCollector(),  # type: ignore[arg-type]
        stock_rt_min_collector=FakeMinuteCollector(),  # type: ignore[arg-type]
        etf_rt_daily_collector=FakeEtfCollector(fail=True),  # type: ignore[arg-type]
        monotonic_provider=MutableClock(100.0),
    )

    result = service.run_due_cycle(None)  # type: ignore[arg-type]

    by_feed = {item.feed_key: item for item in result.feed_runs}
    assert by_feed["tushare_etf_rt_k"].status == "degraded"
    assert by_feed["tushare_stock_rt_k"].status == "ok"
    assert by_feed["tushare_stock_rt_min_1min"].status == "ok"
