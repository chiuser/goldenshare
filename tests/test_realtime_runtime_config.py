from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.config.settings import get_settings
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import (
    RealtimeRuntimeConfigError,
    load_realtime_runtime_config,
    normalize_stock_rt_min_freq,
)
from tests.realtime_runtime_config_helpers import DEFAULT_DAILY_RUNTIME_CONFIG, seed_realtime_runtime_config


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


def test_realtime_runtime_config_loads_from_database_rows() -> None:
    session = _session()
    seed_realtime_runtime_config(
        session,
        daily={"lease_ttl_seconds": 44},
        minute={"enabled": True, "enabled_freqs": ["1MIN", "30MIN"], "poll_interval_seconds": 30},
    )

    config = load_realtime_runtime_config(session)

    assert config.redis_url == "redis://127.0.0.1:6379/0"
    assert config.stock_rt_daily.lease_ttl_seconds == 44
    assert config.stock_rt_min.enabled is True
    assert config.stock_rt_min.enabled_freqs == ("1MIN", "30MIN")
    assert config.stock_rt_min.poll_interval_seconds == 30
    assert config.stock_rt_min.feed_key_for_freq("1min") == "tushare_stock_rt_min_1min"


def test_realtime_runtime_config_missing_rows_fail_fast_without_env_fallback() -> None:
    session = _session()
    session.add(
        RealtimeRuntimeConfigRecord(
            object_key="stock_rt_daily",
            object_kind="collector_feed",
            runtime_config_json=dict(DEFAULT_DAILY_RUNTIME_CONFIG),
            version=1,
            requires_collector_restart=True,
        )
    )
    session.commit()

    with pytest.raises(RealtimeRuntimeConfigError, match="missing: stock_rt_min"):
        load_realtime_runtime_config(session)


def test_realtime_runtime_config_rejects_invalid_minute_frequency() -> None:
    session = _session()
    seed_realtime_runtime_config(session, minute={"enabled_freqs": ["1MIN", "BAD"]})

    with pytest.raises(RealtimeRuntimeConfigError, match="invalid stock realtime minute freq"):
        load_realtime_runtime_config(session)


def test_realtime_runtime_config_rejects_empty_minute_frequency_list() -> None:
    session = _session()
    seed_realtime_runtime_config(session, minute={"enabled_freqs": []})

    with pytest.raises(RealtimeRuntimeConfigError, match="cannot be empty"):
        load_realtime_runtime_config(session)


def test_realtime_runtime_config_rejects_underprovisioned_request_budget() -> None:
    session = _session()
    seed_realtime_runtime_config(session, minute={"poll_interval_seconds": 60, "max_calls_per_minute": 4})

    with pytest.raises(RealtimeRuntimeConfigError, match="cannot cover"):
        load_realtime_runtime_config(session)


def test_realtime_runtime_config_rejects_stale_less_than_poll_interval() -> None:
    session = _session()
    seed_realtime_runtime_config(session, minute={"poll_interval_seconds": 60, "stale_after_seconds": 30})

    with pytest.raises(RealtimeRuntimeConfigError, match="stale_after_seconds"):
        load_realtime_runtime_config(session)


def test_realtime_runtime_config_locked_fields_ignore_db_json_and_env(monkeypatch) -> None:
    session = _session()
    monkeypatch.setenv("DEFAULT_EXCHANGE", "SZSE")
    get_settings.cache_clear()
    seed_realtime_runtime_config(
        session,
        daily={
            "exchange": "SZSE",
            "collection_sessions": "00:00-23:59",
            "ts_code_pattern": "600000.SH",
            "feed_key": "bad_daily_key",
            "source_api_name": "bad_rt_k",
        },
        minute={
            "exchange": "SZSE",
            "collection_sessions": "00:00-23:59",
            "ts_code_pattern": "600000.SH",
            "feed_key_pattern": "bad_min",
            "source_api_name": "bad_rt_min",
        },
    )

    config = load_realtime_runtime_config(session)

    assert config.stock_rt_daily.exchange == "SSE"
    assert config.stock_rt_daily.collection_sessions == "09:30-11:30,13:00-15:00"
    assert config.stock_rt_daily.ts_code_pattern == "3*.SZ,6*.SH,0*.SZ,9*.BJ"
    assert config.stock_rt_daily.feed_key == "tushare_stock_rt_k"
    assert config.stock_rt_daily.source_api_name == "rt_k"
    assert config.stock_rt_min.exchange == "SSE"
    assert config.stock_rt_min.collection_sessions == "09:30-11:30,13:00-15:00"
    assert config.stock_rt_min.ts_code_pattern == "3*.SZ,6*.SH,0*.SZ,9*.BJ"
    assert config.stock_rt_min.feed_key_for_freq("1MIN") == "tushare_stock_rt_min_1min"
    assert config.stock_rt_min.source_api_name == "rt_min"
    get_settings.cache_clear()


def test_normalize_stock_rt_min_freq_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        normalize_stock_rt_min_freq("2MIN")
