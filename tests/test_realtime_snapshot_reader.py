from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import (
    InMemoryRealtimeStateStore,
    RealtimeFeedUnavailable,
    RealtimeSnapshotReader,
    RealtimeStateStoreUnavailable,
    STOCK_RT_DAILY_FEED_KEY,
    get_realtime_stock_rt_min_config,
)
from src.foundation.realtime.state_store import UnavailableRealtimeStateStore
from tests.realtime_runtime_config_helpers import seed_realtime_runtime_config


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        RealtimeRuntimeConfigRecord.__table__.create(connection)
        TradeCalendar.__table__.create(connection)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _open_trade_day(session: Session, trade_date: date = date(2026, 6, 1)) -> None:
    session.add(TradeCalendar(exchange="SSE", trade_date=trade_date, is_open=True, pretrade_date=None))
    session.commit()


def test_realtime_snapshot_reader_reads_daily_current_batch_and_stale_state() -> None:
    session = _session()
    seed_realtime_runtime_config(session)
    _open_trade_day(session)
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        batch_id="daily-1",
        snapshots=[{"ts_code": "600000.SH", "name": "浦发银行", "close": "10.20"}],
        meta={
            "received_at": "2026-06-01T10:30:00+08:00",
            "published_at": "2026-06-01T10:30:00+08:00",
            "source_row_count": 1,
        },
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )

    result = RealtimeSnapshotReader(
        store=store,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 0, tzinfo=CN_TIMEZONE),
    ).read_stock_rt_daily_snapshot(session, ts_codes=["600000.SH", "NOPE.SH"])

    assert result.feed_key == STOCK_RT_DAILY_FEED_KEY
    assert result.batch_id == "daily-1"
    assert result.collection_status == "open"
    assert result.stale is True
    assert result.stale_after_seconds == 20
    assert result.items[0]["ts_code"] == "600000.SH"
    assert result.missing_ts_codes == ("NOPE.SH",)


def test_realtime_snapshot_reader_keeps_minute_frequency_feeds_isolated() -> None:
    session = _session()
    seed_realtime_runtime_config(session)
    _open_trade_day(session)
    config = get_realtime_stock_rt_min_config(session)
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=config.feed_key_for_freq("1MIN"),
        batch_id="min-1",
        snapshots=[{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": "10.20"}],
        meta={"received_at": "2026-06-01T10:35:01+08:00", "published_at": "2026-06-01T10:35:02+08:00"},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.publish_batch(
        feed_key=config.feed_key_for_freq("5MIN"),
        batch_id="min-5",
        snapshots=[{"ts_code": "600000.SH", "freq": "5MIN", "time": "2026-06-01 10:35:00", "close": "10.50"}],
        meta={"received_at": "2026-06-01T10:35:03+08:00", "published_at": "2026-06-01T10:35:04+08:00"},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )

    result = RealtimeSnapshotReader(
        store=store,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 5, tzinfo=CN_TIMEZONE),
    ).read_stock_rt_min_snapshot(session, freq="5MIN", ts_codes=["600000.SH"])

    assert result.feed_key == config.feed_key_for_freq("5MIN")
    assert result.freq == "5MIN"
    assert result.batch_id == "min-5"
    assert result.items[0]["freq"] == "5MIN"
    assert result.items[0]["close"] == "10.50"


def test_realtime_snapshot_reader_rejects_missing_current_batch() -> None:
    session = _session()
    seed_realtime_runtime_config(session)
    store = InMemoryRealtimeStateStore()

    with pytest.raises(RealtimeFeedUnavailable, match="尚未发布可读批次"):
        RealtimeSnapshotReader(store=store).read_stock_rt_daily_snapshot(session, ts_codes=["600000.SH"])


def test_realtime_snapshot_reader_rejects_missing_batch_meta() -> None:
    session = _session()
    seed_realtime_runtime_config(session)
    store = InMemoryRealtimeStateStore()
    store.current_batches[STOCK_RT_DAILY_FEED_KEY] = "missing-meta"

    with pytest.raises(RealtimeFeedUnavailable, match="当前批次缺少元信息"):
        RealtimeSnapshotReader(store=store).read_stock_rt_daily_snapshot(session, ts_codes=["600000.SH"])


def test_realtime_snapshot_reader_propagates_state_store_unavailable() -> None:
    session = _session()
    seed_realtime_runtime_config(session)

    with pytest.raises(RealtimeStateStoreUnavailable, match="redis down"):
        RealtimeSnapshotReader(store=UnavailableRealtimeStateStore("redis down")).read_stock_rt_daily_snapshot(
            session,
            ts_codes=["600000.SH"],
        )
