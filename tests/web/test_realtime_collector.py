from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.foundation.realtime import InMemoryRealtimeStateStore, STOCK_RT_DAILY_FEED_KEY, StockRtDailyCollector, StockRtDailyFetchResult
from tests.realtime_runtime_config_helpers import load_test_realtime_runtime_config


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class FakeStockRtDailyProvider:
    def __init__(self, row_batches: list[list[dict]]) -> None:
        self.row_batches = row_batches
        self.calls = 0

    def fetch_all_market(self) -> StockRtDailyFetchResult:
        rows = self.row_batches[min(self.calls, len(self.row_batches) - 1)]
        self.calls += 1
        return StockRtDailyFetchResult(
            rows=rows,
            source_elapsed_ms=12.5,
            request_params={"ts_code": "3*.SZ,6*.SH,0*.SZ,9*.BJ"},
        )


class RecordingLeaseStore(InMemoryRealtimeStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.lease_ttls: list[int] = []

    def acquire_lease(self, feed_key: str, *, owner: str, ttl_seconds: int) -> bool:
        self.lease_ttls.append(ttl_seconds)
        return super().acquire_lease(feed_key, owner=owner, ttl_seconds=ttl_seconds)


def test_stock_rt_daily_collector_publishes_current_batch_and_delta(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session).stock_rt_daily
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 15), is_open=True)
    store = InMemoryRealtimeStateStore()
    provider = FakeStockRtDailyProvider(
        [
            [
                {"ts_code": "600000.SH", "name": "浦发银行", "close": 10.01, "trade_time": "2026-05-15 09:35:00"},
                {"ts_code": "000001.SZ", "name": "平安银行", "close": 11.01, "trade_time": "2026-05-15 09:35:00"},
            ],
            [
                {"ts_code": "600000.SH", "name": "浦发银行", "close": 10.02, "trade_time": "2026-05-15 09:35:06"},
                {"ts_code": "000001.SZ", "name": "平安银行", "close": 11.01, "trade_time": "2026-05-15 09:35:06"},
            ],
        ]
    )
    now_values = iter(
        [
            datetime(2026, 5, 15, 9, 35, 0, tzinfo=CN_TIMEZONE) + timedelta(milliseconds=idx)
            for idx in range(20)
        ]
    )
    collector = StockRtDailyCollector(
        store=store,
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: next(now_values),
        collector_id="test-collector",
    )

    first = collector.run_cycle(db_session)
    second = collector.run_cycle(db_session)

    assert first.status == "ok"
    assert first.snapshot_count == 2
    assert first.delta_count == 0
    assert second.status == "ok"
    assert second.snapshot_count == 2
    assert second.delta_count == 2
    current_batch_id = store.get_current_batch_id(STOCK_RT_DAILY_FEED_KEY)
    assert current_batch_id == second.batch_id
    snapshots = store.get_snapshots(STOCK_RT_DAILY_FEED_KEY, current_batch_id or "", ["600000.SH"])
    assert snapshots["600000.SH"]["close"] == "10.02"
    assert store.get_health(STOCK_RT_DAILY_FEED_KEY)["status"] == "ok"  # type: ignore[index]


def test_stock_rt_daily_collector_uses_configured_lease_ttl(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session, daily={"lease_ttl_seconds": 44}).stock_rt_daily
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 15), is_open=True)
    store = RecordingLeaseStore()
    provider = FakeStockRtDailyProvider(
        [[{"ts_code": "600000.SH", "name": "浦发银行", "close": 10.01, "trade_time": "2026-05-15 09:35:00"}]]
    )
    collector = StockRtDailyCollector(
        store=store,
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 5, 15, 9, 35, 0, tzinfo=CN_TIMEZONE),
        collector_id="test-collector",
    )

    result = collector.run_cycle(db_session)

    assert result.status == "ok"
    assert store.lease_ttls == [44]


def test_stock_rt_daily_collector_skips_source_request_outside_collection_window(
    db_session,
    trade_calendar_factory,
) -> None:
    config = load_test_realtime_runtime_config(db_session).stock_rt_daily
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 15), is_open=True)
    provider = FakeStockRtDailyProvider([[{"ts_code": "600000.SH"}]])
    collector = StockRtDailyCollector(
        store=InMemoryRealtimeStateStore(),
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: datetime(2026, 5, 15, 12, 0, 0, tzinfo=CN_TIMEZONE),
        collector_id="test-collector",
    )

    result = collector.run_cycle(db_session)

    assert result.status == "idle"
    assert result.collection_status == "idle"
    assert provider.calls == 0
