from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.foundation.config.settings import get_settings
from src.foundation.realtime import (
    InMemoryRealtimeStateStore,
    STOCK_RT_MIN_FIELDS,
    StockRtMinFeedPublisher,
    StockRtMinFetchResult,
    TushareStockRtMinProvider,
    get_realtime_stock_rt_min_config,
    normalize_stock_rt_min_rows,
)
from src.foundation.realtime.constants import STOCK_RT_MIN_SOURCE_API_NAME


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class RecordingTushareClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call(self, api_name: str, *, params: dict, fields: tuple[str, ...]) -> list[dict]:
        self.calls.append({"api_name": api_name, "params": params, "fields": fields})
        return [{"ts_code": "600000.SH", "freq": params["freq"], "time": "2026-06-01 10:35:00"}]


class FakeStockRtMinProvider:
    def __init__(self, row_batches_by_freq: dict[str, list[list[dict]]]) -> None:
        self.row_batches_by_freq = row_batches_by_freq
        self.calls_by_freq: dict[str, int] = {}

    def fetch_all_market(self, *, freq: str) -> StockRtMinFetchResult:
        calls = self.calls_by_freq.get(freq, 0)
        self.calls_by_freq[freq] = calls + 1
        batches = self.row_batches_by_freq[freq]
        rows = batches[min(calls, len(batches) - 1)]
        config = get_realtime_stock_rt_min_config()
        return StockRtMinFetchResult(
            freq=freq,
            feed_key=config.feed_key_for_freq(freq),
            rows=rows,
            source_elapsed_ms=12.5,
            request_params={"ts_code": config.ts_code_pattern, "freq": freq},
        )


def test_stock_rt_min_provider_requests_rt_min_with_freq_pattern_and_explicit_fields(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_TS_CODE_PATTERN", "3*.SZ,6*.SH,0*.SZ,9*.BJ")
    get_settings.cache_clear()
    client = RecordingTushareClient()
    provider = TushareStockRtMinProvider(client=client)  # type: ignore[arg-type]

    result = provider.fetch_all_market(freq="1min")

    assert result.freq == "1MIN"
    assert result.feed_key == "tushare_stock_rt_min_1min"
    assert result.request_params == {"ts_code": "3*.SZ,6*.SH,0*.SZ,9*.BJ", "freq": "1MIN"}
    assert client.calls == [
        {
            "api_name": STOCK_RT_MIN_SOURCE_API_NAME,
            "params": {"ts_code": "3*.SZ,6*.SH,0*.SZ,9*.BJ", "freq": "1MIN"},
            "fields": STOCK_RT_MIN_FIELDS,
        }
    ]


def test_normalize_stock_rt_min_rows_keeps_source_time_and_adds_identity_fields() -> None:
    received_at = datetime(2026, 6, 1, 10, 35, tzinfo=CN_TIMEZONE)

    result = normalize_stock_rt_min_rows(
        [
            {
                "ts_code": "600000.SH",
                "freq": "1MIN",
                "time": "2026-05-15 15:00:00",
                "open": 10.1,
                "close": 10.2,
                "high": 10.3,
                "low": 10.0,
                "vol": 12345,
                "amount": 67890,
            }
        ],
        freq="1MIN",
        received_at=received_at,
    )

    assert result.invalid_count == 0
    assert len(result.snapshots) == 1
    snapshot = result.snapshots[0]
    assert snapshot["ts_code"] == "600000.SH"
    assert snapshot["freq"] == "1MIN"
    assert snapshot["time"] == "2026-05-15 15:00:00"
    assert snapshot["close"] == "10.2"
    assert snapshot["source"] == "tushare"
    assert snapshot["source_api_name"] == "rt_min"
    assert snapshot["received_at"] == "2026-06-01T10:35:00+08:00"
    assert snapshot["raw_payload_hash"]


def test_normalize_stock_rt_min_rows_counts_invalid_identity_rows() -> None:
    result = normalize_stock_rt_min_rows(
        [
            {"ts_code": "", "freq": "1MIN", "time": "2026-06-01 10:35:00"},
            {"ts_code": "600000.SH", "freq": "", "time": "2026-06-01 10:35:00"},
            {"ts_code": "000001.SZ", "freq": "5MIN", "time": "2026-06-01 10:35:00"},
            {"ts_code": "000002.SZ", "freq": "1MIN", "time": ""},
        ],
        freq="1MIN",
        received_at=datetime(2026, 6, 1, 10, 35, tzinfo=CN_TIMEZONE),
    )

    assert result.snapshots == []
    assert result.invalid_count == 4
    assert result.invalid_reason_counts == {
        "missing_ts_code": 1,
        "missing_freq": 1,
        "freq_mismatch": 1,
        "missing_time": 1,
    }


def test_stock_rt_min_publish_freq_isolates_redis_feeds_and_keeps_delta_stream_ready(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_KEEP_RECENT_BATCHES", "3")
    get_settings.cache_clear()
    config = get_realtime_stock_rt_min_config()
    store = InMemoryRealtimeStateStore()
    provider = FakeStockRtMinProvider(
        {
            "1MIN": [
                [{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": 10.1}],
                [{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:36:00", "close": 10.2}],
            ],
            "5MIN": [
                [{"ts_code": "600000.SH", "freq": "5MIN", "time": "2026-06-01 10:35:00", "close": 10.5}]
            ],
        }
    )
    now_values = iter(
        [
            datetime(2026, 6, 1, 10, 35, 0, tzinfo=CN_TIMEZONE) + timedelta(seconds=index)
            for index in range(10)
        ]
    )
    publisher = StockRtMinFeedPublisher(
        store=store,
        provider=provider,  # type: ignore[arg-type]
        config=config,
        now_provider=lambda: next(now_values),
    )

    first_1min = publisher.publish_freq(freq="1MIN")
    first_5min = publisher.publish_freq(freq="5MIN")
    second_1min = publisher.publish_freq(freq="1MIN")

    feed_1min = config.feed_key_for_freq("1MIN")
    feed_5min = config.feed_key_for_freq("5MIN")
    assert first_1min.snapshot_count == 1
    assert first_1min.delta_count == 0
    assert first_5min.feed_key == feed_5min
    assert second_1min.delta_count == 1
    assert store.get_current_batch_id(feed_1min) == second_1min.batch_id
    assert store.get_current_batch_id(feed_5min) == first_5min.batch_id
    assert store.get_batch_meta(feed_1min, second_1min.batch_id or "")["freq"] == "1MIN"
    assert store.get_batch_meta(feed_5min, first_5min.batch_id or "")["freq"] == "5MIN"
    assert store.delta_stream_ids[feed_1min]
