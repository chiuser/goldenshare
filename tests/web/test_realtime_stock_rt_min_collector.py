from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.foundation.realtime import InMemoryRealtimeStateStore, StockRtMinCollector, StockRtMinFetchResult
from src.foundation.realtime.runtime_config import RealtimeStockRtMinConfig
from tests.realtime_runtime_config_helpers import load_test_realtime_runtime_config


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class FakeStockRtMinProvider:
    def __init__(self, row_batches_by_freq: dict[str, list[list[dict]]], *, config: RealtimeStockRtMinConfig) -> None:
        self.row_batches_by_freq = row_batches_by_freq
        self.config = config
        self.calls_by_freq: dict[str, int] = {}

    def fetch_all_market(self, *, freq: str) -> StockRtMinFetchResult:
        calls = self.calls_by_freq.get(freq, 0)
        self.calls_by_freq[freq] = calls + 1
        batches = self.row_batches_by_freq[freq]
        rows = batches[min(calls, len(batches) - 1)]
        return StockRtMinFetchResult(
            freq=freq,
            feed_key=self.config.feed_key_for_freq(freq),
            rows=rows,
            source_elapsed_ms=12.5,
            request_params={"ts_code": self.config.ts_code_pattern, "freq": freq},
        )


class FailingStockRtMinProvider:
    def fetch_all_market(self, *, freq: str) -> StockRtMinFetchResult:
        raise RuntimeError(f"{freq} boom")


class RecordingLeaseStore(InMemoryRealtimeStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.lease_ttls: list[int] = []

    def acquire_lease(self, feed_key: str, *, owner: str, ttl_seconds: int) -> bool:
        self.lease_ttls.append(ttl_seconds)
        return super().acquire_lease(feed_key, owner=owner, ttl_seconds=ttl_seconds)


def test_stock_rt_min_collector_writes_health_with_freq_and_invalid_counts(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session, minute={"enabled": True, "lease_ttl_seconds": 77}).stock_rt_min
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 1), is_open=True)
    store = RecordingLeaseStore()
    provider = FakeStockRtMinProvider(
        {
            "1MIN": [
                [
                    {"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": 10.1},
                    {"ts_code": "", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": 10.2},
                ]
            ]
        },
        config=config,
    )
    collector = StockRtMinCollector(
        store=store,
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 0, tzinfo=CN_TIMEZONE),
        collector_id="minute-test",
    )

    result = collector.run_freq_cycle(db_session, freq="1MIN")

    feed_key = config.feed_key_for_freq("1MIN")
    health = store.get_health(feed_key) or {}
    assert result.status == "ok"
    assert result.invalid_count == 1
    assert store.lease_ttls == [77]
    assert health["status"] == "ok"
    assert health["feed_key"] == feed_key
    assert health["freq"] == "1MIN"
    assert health["invalid_count"] == 1
    assert health["invalid_reason_counts"] == {"missing_ts_code": 1}
    assert health["request_count_last_minute"] == 1


def test_stock_rt_min_collector_skips_source_request_outside_collection_window(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session, minute={"enabled": True}).stock_rt_min
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 1), is_open=True)
    provider = FakeStockRtMinProvider({"1MIN": [[{"ts_code": "600000.SH"}]]}, config=config)
    collector = StockRtMinCollector(
        store=InMemoryRealtimeStateStore(),
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=CN_TIMEZONE),
        collector_id="minute-test",
    )

    result = collector.run_freq_cycle(db_session, freq="1MIN")

    assert result.status == "idle"
    assert result.collection_status == "idle"
    assert provider.calls_by_freq == {}


def test_stock_rt_min_collector_records_degraded_health_without_breaking_other_freq(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session, minute={"enabled": True}).stock_rt_min
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 1), is_open=True)
    store = InMemoryRealtimeStateStore()
    failing = StockRtMinCollector(
        store=store,
        provider=FailingStockRtMinProvider(),  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 0, tzinfo=CN_TIMEZONE),
        collector_id="minute-test",
    )
    healthy = StockRtMinCollector(
        store=store,
        provider=FakeStockRtMinProvider(
            {"5MIN": [[{"ts_code": "600000.SH", "freq": "5MIN", "time": "2026-06-01 10:35:00"}]]},
            config=config,
        ),  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 1, tzinfo=CN_TIMEZONE),
        collector_id="minute-test",
    )

    failed_result = failing.run_freq_cycle(db_session, freq="1MIN")
    ok_result = healthy.run_freq_cycle(db_session, freq="5MIN")

    failed_health = store.get_health(config.feed_key_for_freq("1MIN")) or {}
    ok_health = store.get_health(config.feed_key_for_freq("5MIN")) or {}
    assert failed_result.status == "degraded"
    assert "1MIN boom" in (failed_result.message or "")
    assert failed_health["status"] == "degraded"
    assert failed_health["last_request_at"] == "2026-06-01T10:35:00+08:00"
    assert ok_result.status == "ok"
    assert ok_health["status"] == "ok"
