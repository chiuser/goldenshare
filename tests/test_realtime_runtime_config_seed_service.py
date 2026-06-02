from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.config.settings import get_settings
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime.feed_config import (
    RealtimeFeedStorageConfig,
    RealtimeRuntimeConfig,
    RealtimeStockRtDailyConfig,
    RealtimeStockRtMinConfig,
)
from src.foundation.realtime.runtime_config_seed_service import RealtimeRuntimeConfigSeedService


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        RealtimeRuntimeConfigRecord.__table__.create(connection)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _runtime_config() -> RealtimeRuntimeConfig:
    storage = RealtimeFeedStorageConfig(
        snapshot_ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    return RealtimeRuntimeConfig(
        redis_url="redis://example/0",
        stock_rt_daily=RealtimeStockRtDailyConfig(
            feed_key="tushare_stock_rt_k",
            display_name="股票实时日线",
            source_api_name="rt_k",
            exchange="SSE",
            enabled=True,
            poll_interval_seconds=6,
            collection_sessions="09:30-11:30,13:00-15:00",
            max_calls_per_minute=10,
            lease_ttl_seconds=30,
            stale_after_seconds=20,
            storage=storage,
            ts_code_pattern="3*.SZ,6*.SH,0*.SZ,9*.BJ",
        ),
        stock_rt_min=RealtimeStockRtMinConfig(
            display_name="股票实时分钟",
            source_api_name="rt_min",
            exchange="SSE",
            enabled=True,
            enabled_freqs=("1MIN", "5MIN"),
            poll_interval_seconds=60,
            collection_sessions="09:30-11:30,13:00-15:00",
            max_calls_per_minute=20,
            lease_ttl_seconds=90,
            stale_after_seconds=90,
            storage=storage,
            ts_code_pattern="3*.SZ,6*.SH,0*.SZ,9*.BJ",
            source_timeout_seconds=20,
        ),
    )


def _row_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(RealtimeRuntimeConfigRecord)) or 0


def test_realtime_runtime_config_seed_dry_run_does_not_write() -> None:
    session = _session()

    report = RealtimeRuntimeConfigSeedService().run(session, dry_run=True, runtime_config=_runtime_config())

    assert report.dry_run is True
    assert report.created_count == 2
    assert report.skipped_count == 0
    assert [item.object_key for item in report.items] == ["stock_rt_daily", "stock_rt_min"]
    assert _row_count(session) == 0


def test_realtime_runtime_config_seed_apply_creates_required_rows() -> None:
    session = _session()

    report = RealtimeRuntimeConfigSeedService().run(session, dry_run=False, runtime_config=_runtime_config())

    assert report.created_count == 2
    assert report.skipped_count == 0
    daily = session.get(RealtimeRuntimeConfigRecord, "stock_rt_daily")
    minute = session.get(RealtimeRuntimeConfigRecord, "stock_rt_min")
    assert daily is not None
    assert minute is not None
    assert daily.object_kind == "collector_feed"
    assert minute.object_kind == "feed_group"
    assert daily.version == 1
    assert minute.requires_collector_restart is True
    assert _row_count(session) == 2


def test_realtime_runtime_config_seed_does_not_persist_locked_fields() -> None:
    session = _session()

    RealtimeRuntimeConfigSeedService().run(session, dry_run=False, runtime_config=_runtime_config())

    locked_fields = {
        "collection_sessions",
        "ts_code_pattern",
        "source_api_name",
        "feed_key",
        "feed_key_pattern",
        "exchange",
    }
    daily = session.get(RealtimeRuntimeConfigRecord, "stock_rt_daily")
    minute = session.get(RealtimeRuntimeConfigRecord, "stock_rt_min")
    assert daily is not None
    assert minute is not None
    assert locked_fields.isdisjoint(daily.runtime_config_json)
    assert locked_fields.isdisjoint(minute.runtime_config_json)
    assert daily.runtime_config_json == {
        "enabled": True,
        "poll_interval_seconds": 6,
        "max_calls_per_minute": 10,
        "lease_ttl_seconds": 30,
        "stale_after_seconds": 20,
        "snapshot_ttl_seconds": 259200,
        "keep_recent_batches": 3,
        "batch_stream_maxlen": 5000,
        "delta_stream_maxlen": 200000,
    }
    assert minute.runtime_config_json["enabled_freqs"] == ["1MIN", "5MIN"]
    assert minute.runtime_config_json["source_timeout_seconds"] == 20


def test_realtime_runtime_config_seed_skips_existing_rows_without_overwrite() -> None:
    session = _session()
    session.add(
        RealtimeRuntimeConfigRecord(
            object_key="stock_rt_daily",
            object_kind="collector_feed",
            runtime_config_json={"enabled": False, "custom": "kept"},
            version=9,
            requires_collector_restart=False,
        )
    )
    session.commit()

    report = RealtimeRuntimeConfigSeedService().run(session, dry_run=False, runtime_config=_runtime_config())

    assert report.created_count == 1
    assert report.skipped_count == 1
    daily = session.get(RealtimeRuntimeConfigRecord, "stock_rt_daily")
    minute = session.get(RealtimeRuntimeConfigRecord, "stock_rt_min")
    assert daily is not None
    assert minute is not None
    assert daily.runtime_config_json == {"enabled": False, "custom": "kept"}
    assert daily.version == 9
    assert minute.object_kind == "feed_group"


def test_realtime_runtime_config_seed_rejects_invalid_env_without_partial_write(monkeypatch) -> None:
    session = _session()
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "BAD")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="invalid stock realtime minute freq"):
        RealtimeRuntimeConfigSeedService().run(session, dry_run=False)

    assert _row_count(session) == 0
    get_settings.cache_clear()
