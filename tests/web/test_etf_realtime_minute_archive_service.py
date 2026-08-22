from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from src.foundation.realtime import InMemoryRealtimeStateStore
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.services.etf_realtime_minute_archive_service import EtfRealtimeMinuteArchiveService


FEED_KEY = "tushare_etf_rt_k"
TARGET_DATE = date(2026, 8, 21)
TS_CODE = "510300.SH"


def _publish_batch(store: InMemoryRealtimeStateStore, batch_id: str, trade_time: str, amount: str) -> None:
    store.publish_batch(
        feed_key=FEED_KEY,
        batch_id=batch_id,
        snapshots=[{"ts_code": TS_CODE, "trade_time": trade_time, "amount": amount, "vol": amount}],
        meta={"published_at": trade_time},
        ttl_seconds=259200,
        keep_recent_batches=260,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )


def test_archive_uses_real_buckets_latest_valid_snapshot_and_is_idempotent(db_session) -> None:
    db_session.add(
        EtfRealtimeMonitorPool(
            ts_code=TS_CODE,
            group_key="broad_base",
            group_name="宽基ETF",
            enabled=True,
            display_order=1,
        )
    )
    db_session.commit()
    store = InMemoryRealtimeStateStore()
    _publish_batch(store, "b1", "2026-08-21T11:28:00+08:00", "100")
    _publish_batch(store, "b2", "2026-08-21T11:29:00+08:00", "200")
    _publish_batch(store, "b3", "2026-08-21T11:30:00+08:00", "250")
    _publish_batch(store, "b4", "2026-08-21T13:00:00+08:00", "300")

    service = EtfRealtimeMinuteArchiveService()
    first = service.run(db_session, store=store, feed_key=FEED_KEY, trade_date=TARGET_DATE)

    assert first.metric_count == 240
    morning = db_session.get(EtfRealtimeMinuteStat, (TARGET_DATE, time(11, 30), TS_CODE))
    afternoon = db_session.get(EtfRealtimeMinuteStat, (TARGET_DATE, time(13, 1), TS_CODE))
    missing = db_session.get(EtfRealtimeMinuteStat, (TARGET_DATE, time(9, 31), TS_CODE))
    lunch_bucket = db_session.get(EtfRealtimeMinuteStat, (TARGET_DATE, time(12, 0), TS_CODE))
    assert morning is not None
    assert morning.amount_delta_yuan == Decimal("50")
    assert afternoon is not None
    assert afternoon.amount_delta_yuan == Decimal("50")
    assert missing is not None
    assert missing.data_quality == "missing"
    assert missing.amount_delta_yuan is None
    assert missing.source_trade_time is None
    assert lunch_bucket is None

    second = service.run(db_session, store=store, feed_key=FEED_KEY, trade_date=TARGET_DATE)
    assert second.metric_count == 240
    assert db_session.query(EtfRealtimeMinuteStat).count() == 240
