from __future__ import annotations

from src.foundation.realtime import InMemoryRealtimeStateStore
from src.foundation.realtime.etf_volume_metrics import (
    DATA_QUALITY_INVALID,
    DATA_QUALITY_MISSING,
    DATA_QUALITY_OK,
    aggregate_etf_window_metrics,
    build_etf_minute_metrics_for_trade_date,
)


FEED_KEY = "tushare_etf_rt_k"


def test_etf_volume_metrics_use_cumulative_amount_delta_and_do_not_fill_missing_as_zero() -> None:
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=FEED_KEY,
        batch_id="b1",
        snapshots=[{"ts_code": "510300.SH", "trade_time": "2026-08-21T09:31:00+08:00", "amount": "1000", "vol": "10"}],
        meta={"published_at": "2026-08-21T09:31:00+08:00"},
        ttl_seconds=259200,
        keep_recent_batches=260,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.publish_batch(
        feed_key=FEED_KEY,
        batch_id="b2",
        snapshots=[{"ts_code": "510300.SH", "trade_time": "2026-08-21T09:32:00+08:00", "amount": "1600", "vol": "16"}],
        meta={"published_at": "2026-08-21T09:32:00+08:00"},
        ttl_seconds=259200,
        keep_recent_batches=260,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )

    metrics = build_etf_minute_metrics_for_trade_date(
        store,
        feed_key=FEED_KEY,
        ts_codes=["510300.SH", "159919.SZ"],
        trade_date=__import__("datetime").date(2026, 8, 21),
    )

    ok_metric = next(item for item in metrics if item.ts_code == "510300.SH" and item.data_quality == DATA_QUALITY_OK)
    missing_metric = next(item for item in metrics if item.ts_code == "159919.SZ")
    assert ok_metric.data_quality == DATA_QUALITY_OK
    assert str(ok_metric.amount_delta_yuan) == "600"
    assert missing_metric.data_quality == DATA_QUALITY_MISSING
    assert missing_metric.amount_delta_yuan is None


def test_etf_volume_metrics_mark_decreased_cumulative_amount_invalid() -> None:
    store = InMemoryRealtimeStateStore()
    for batch_id, amount in (("b1", "1000"), ("b2", "900")):
        store.publish_batch(
            feed_key=FEED_KEY,
            batch_id=batch_id,
            snapshots=[{"ts_code": "510300.SH", "trade_time": "2026-08-21T09:32:00+08:00", "amount": amount, "vol": "10"}],
            meta={"published_at": "2026-08-21T09:32:00+08:00"},
            ttl_seconds=259200,
            keep_recent_batches=260,
            batch_stream_maxlen=5000,
            delta_stream_maxlen=200000,
        )

    metrics = build_etf_minute_metrics_for_trade_date(
        store,
        feed_key=FEED_KEY,
        ts_codes=["510300.SH"],
        trade_date=__import__("datetime").date(2026, 8, 21),
    )

    invalid_metric = next(item for item in metrics if item.data_quality == DATA_QUALITY_INVALID)
    assert invalid_metric.missing_reason == "amount_decreased"


def test_etf_window_metrics_require_complete_window() -> None:
    store = InMemoryRealtimeStateStore()
    for index, amount in enumerate(("100", "200", "300", "400", "500", "600"), start=0):
        store.publish_batch(
            feed_key=FEED_KEY,
            batch_id=f"b{index}",
            snapshots=[{"ts_code": "510300.SH", "trade_time": f"2026-08-21T09:{34 + index}:00+08:00", "amount": amount, "vol": amount}],
            meta={"published_at": f"2026-08-21T09:{34 + index}:00+08:00"},
            ttl_seconds=259200,
            keep_recent_batches=260,
            batch_stream_maxlen=5000,
            delta_stream_maxlen=200000,
        )
    minute_metrics = build_etf_minute_metrics_for_trade_date(
        store,
        feed_key=FEED_KEY,
        ts_codes=["510300.SH"],
        trade_date=__import__("datetime").date(2026, 8, 21),
    )

    window_metrics = aggregate_etf_window_metrics(minute_metrics, window_minutes=5)

    complete_window = next(item for item in window_metrics if item.data_quality == DATA_QUALITY_OK)
    assert str(complete_window.amount_yuan) == "500"
