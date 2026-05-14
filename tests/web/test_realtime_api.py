from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.app.dependencies.realtime import get_realtime_state_store
from src.app.web.app import app
from src.foundation.config.settings import get_settings
from src.foundation.realtime import InMemoryRealtimeStateStore, STOCK_RT_DAILY_FEED_KEY


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


def test_stock_rt_daily_snapshot_api_reads_current_batch(app_client, db_session, trade_calendar_factory) -> None:
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        batch_id="batch-api",
        snapshots=[{"ts_code": "600000.SH", "name": "浦发银行", "close": "10.20", "received_at": "2026-05-15T09:30:00+08:00"}],
        meta={"received_at": "2026-05-15T09:30:00+08:00", "published_at": "2026-05-15T09:30:01+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get("/api/v1/realtime/stock-rt-daily?ts_codes=600000.SH,NOPE.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["feed_key"] == STOCK_RT_DAILY_FEED_KEY
    assert payload["batch_id"] == "batch-api"
    assert payload["items"][0]["ts_code"] == "600000.SH"
    assert payload["missing_ts_codes"] == ["NOPE.SH"]


def test_stock_rt_daily_snapshot_api_requires_ts_codes(app_client) -> None:
    response = app_client.get("/api/v1/realtime/stock-rt-daily")

    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_TS_CODES"


def test_stock_rt_daily_snapshot_api_returns_unavailable_without_current_batch(app_client) -> None:
    store = InMemoryRealtimeStateStore()
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get("/api/v1/realtime/stock-rt-daily?ts_codes=600000.SH")

    assert response.status_code == 503
    assert response.json()["code"] == "REALTIME_FEED_UNAVAILABLE"


def test_ops_realtime_health_api_uses_health_contract(app_client, auth_token, monkeypatch, trade_calendar_factory) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_DAILY_ENABLED", "true")
    get_settings.cache_clear()
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=STOCK_RT_DAILY_FEED_KEY,
        batch_id="batch-health",
        snapshots=[{"ts_code": "600000.SH", "name": "浦发银行", "close": "10.20"}],
        meta={
            "received_at": "2026-05-15T09:30:00+08:00",
            "published_at": "2026-05-15T09:30:01+08:00",
            "source_row_count": 1,
            "source_elapsed_ms": 120,
            "write_elapsed_ms": 8,
        },
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.set_health(
        STOCK_RT_DAILY_FEED_KEY,
        {
            "collector_running": True,
            "collector_id": "test:1",
            "request_count_last_minute": 1,
            "last_batch_event_id": "1-0",
            "delta_count_last_batch": 0,
        },
    )
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get(
        "/api/v1/ops/realtime/stock-rt-daily/health",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["feed_key"] == STOCK_RT_DAILY_FEED_KEY
    assert payload["current_batch_id"] == "batch-health"
    assert payload["snapshot_count"] == 1
    assert payload["collector_running"] is True
    assert payload["recommended_poll_interval_seconds"] == 60
