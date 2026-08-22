from __future__ import annotations

from src.foundation.realtime import InMemoryRealtimeStateStore, RealtimeRedisKeys, STOCK_RT_DAILY_FEED_KEY


def test_realtime_redis_keys_are_feed_scoped() -> None:
    keys = RealtimeRedisKeys("tushare_stock_rt_k")

    assert keys.current_batch() == "rt:feed:tushare_stock_rt_k:current_batch"
    assert keys.batch_snapshot("b1", "600000.SH") == "rt:feed:tushare_stock_rt_k:batch:b1:snapshot:600000.SH"
    assert keys.batch_index("b1") == "rt:feed:tushare_stock_rt_k:batch:b1:index"
    assert keys.health() == "rt:feed:tushare_stock_rt_k:health"


def test_in_memory_state_store_reads_only_current_batch_and_retains_recent_batches() -> None:
    store = InMemoryRealtimeStateStore()

    store.publish_batch(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        batch_id="batch-1",
        snapshots=[
            {"ts_code": "600000.SH", "name": "浦发银行", "close": "10.01"},
            {"ts_code": "000001.SZ", "name": "平安银行", "close": "11.01"},
        ],
        meta={"published_at": "2026-05-15T09:30:00+08:00", "source_row_count": 2},
        ttl_seconds=259200,
        keep_recent_batches=1,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    assert store.get_current_batch_id(STOCK_RT_DAILY_FEED_KEY) == "batch-1"
    assert store.get_batch_snapshot_count(STOCK_RT_DAILY_FEED_KEY, "batch-1") == 2

    store.publish_batch(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        batch_id="batch-2",
        snapshots=[{"ts_code": "600000.SH", "name": "浦发银行", "close": "10.02"}],
        meta={"published_at": "2026-05-15T09:30:06+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=1,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )

    assert store.get_current_batch_id(STOCK_RT_DAILY_FEED_KEY) == "batch-2"
    assert store.get_batch_meta(STOCK_RT_DAILY_FEED_KEY, "batch-1") is None
    assert store.get_snapshots(STOCK_RT_DAILY_FEED_KEY, "batch-2", ["600000.SH", "000001.SZ"]) == {
        "600000.SH": {
            "feed_key": STOCK_RT_DAILY_FEED_KEY,
            "batch_id": "batch-2",
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "close": "10.02",
        }
    }


def test_in_memory_state_store_lists_batches_and_reads_full_batch_snapshots() -> None:
    store = InMemoryRealtimeStateStore()

    for batch_id, close in (("batch-1", "10.01"), ("batch-2", "10.02")):
        store.publish_batch(
            feed_key=STOCK_RT_DAILY_FEED_KEY,
            batch_id=batch_id,
            snapshots=[
                {"ts_code": "600000.SH", "close": close},
                {"ts_code": "000001.SZ", "close": close},
            ],
            meta={"published_at": f"2026-05-15T09:30:0{batch_id[-1]}+08:00"},
            ttl_seconds=259200,
            keep_recent_batches=3,
            batch_stream_maxlen=5000,
            delta_stream_maxlen=200000,
        )

    assert store.list_batch_ids(STOCK_RT_DAILY_FEED_KEY) == ["batch-2", "batch-1"]
    assert store.list_batch_ids(STOCK_RT_DAILY_FEED_KEY, limit=1) == ["batch-2"]
    assert store.get_batch_snapshot_codes(STOCK_RT_DAILY_FEED_KEY, "batch-2") == {"600000.SH", "000001.SZ"}
    assert set(store.get_batch_snapshots(STOCK_RT_DAILY_FEED_KEY, "batch-2")) == {"600000.SH", "000001.SZ"}
