from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.app.dependencies.realtime import get_realtime_state_store
from src.app.web.app import app
from src.foundation.config.settings import get_settings
from src.foundation.realtime import (
    InMemoryRealtimeStateStore,
    STOCK_RT_DAILY_FEED_KEY,
    STOCK_RT_MIN_ALLOWED_FREQS,
    get_realtime_stock_rt_min_config,
)
from src.foundation.realtime.state_store import UnavailableRealtimeStateStore
from src.ops.queries.realtime_feed_health_query_service import RealtimeFeedHealthQueryService


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


def test_stock_rt_min_snapshot_api_reads_current_batch_by_freq(app_client, db_session, trade_calendar_factory) -> None:
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    config = get_realtime_stock_rt_min_config()
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=config.feed_key_for_freq("1MIN"),
        batch_id="batch-min-1",
        snapshots=[
            {
                "ts_code": "600000.SH",
                "freq": "1MIN",
                "time": "2026-06-01 10:35:00",
                "close": "10.20",
                "source": "tushare",
                "source_api_name": "rt_min",
                "received_at": "2026-06-01T10:35:01+08:00",
            }
        ],
        meta={"received_at": "2026-06-01T10:35:01+08:00", "published_at": "2026-06-01T10:35:02+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get("/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes=600000.SH,NOPE.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["feed_key"] == config.feed_key_for_freq("1MIN")
    assert payload["freq"] == "1MIN"
    assert payload["batch_id"] == "batch-min-1"
    assert payload["items"][0]["ts_code"] == "600000.SH"
    assert payload["items"][0]["freq"] == "1MIN"
    assert payload["missing_ts_codes"] == ["NOPE.SH"]


def test_stock_rt_min_snapshot_api_keeps_freq_feeds_isolated(app_client, db_session, trade_calendar_factory) -> None:
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    config = get_realtime_stock_rt_min_config()
    store = InMemoryRealtimeStateStore()
    store.publish_batch(
        feed_key=config.feed_key_for_freq("1MIN"),
        batch_id="batch-min-1",
        snapshots=[{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": "10.20"}],
        meta={"received_at": "2026-06-01T10:35:01+08:00", "published_at": "2026-06-01T10:35:02+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.publish_batch(
        feed_key=config.feed_key_for_freq("5MIN"),
        batch_id="batch-min-5",
        snapshots=[{"ts_code": "600000.SH", "freq": "5MIN", "time": "2026-06-01 10:35:00", "close": "10.50"}],
        meta={"received_at": "2026-06-01T10:35:03+08:00", "published_at": "2026-06-01T10:35:04+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get("/api/v1/realtime/stock-rt-min?freq=5MIN&ts_codes=600000.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["feed_key"] == config.feed_key_for_freq("5MIN")
    assert payload["batch_id"] == "batch-min-5"
    assert payload["items"][0]["freq"] == "5MIN"
    assert payload["items"][0]["close"] == "10.50"


def test_stock_rt_min_snapshot_api_rejects_invalid_query(app_client) -> None:
    cases = [
        ("/api/v1/realtime/stock-rt-min?ts_codes=600000.SH", "MISSING_FREQ"),
        ("/api/v1/realtime/stock-rt-min?freq=BAD&ts_codes=600000.SH", "INVALID_FREQ"),
        ("/api/v1/realtime/stock-rt-min?freq=1MIN", "MISSING_TS_CODES"),
        ("/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes=6*.SH", "UNSUPPORTED_TS_CODE_PATTERN"),
        ("/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes=600000.SH&limit=10", "UNSUPPORTED_QUERY_PARAM"),
        ("/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes=600000.SH&offset=10", "UNSUPPORTED_QUERY_PARAM"),
    ]

    for url, expected_code in cases:
        response = app_client.get(url)
        assert response.status_code == 400
        assert response.json()["code"] == expected_code


def test_stock_rt_min_snapshot_api_rejects_too_many_codes(app_client) -> None:
    ts_codes = ",".join(f"{index:06d}.SH" for index in range(201))

    response = app_client.get(f"/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes={ts_codes}")

    assert response.status_code == 400
    assert response.json()["code"] == "TOO_MANY_TS_CODES"


def test_stock_rt_min_snapshot_api_returns_unavailable_without_current_batch(app_client) -> None:
    store = InMemoryRealtimeStateStore()
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get("/api/v1/realtime/stock-rt-min?freq=1MIN&ts_codes=600000.SH")

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


def test_ops_stock_rt_min_health_api_returns_all_supported_freqs(
    app_client,
    auth_token,
    monkeypatch,
    trade_calendar_factory,
) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,5MIN")
    get_settings.cache_clear()
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    config = get_realtime_stock_rt_min_config()
    store = InMemoryRealtimeStateStore()
    feed_key = config.feed_key_for_freq("1MIN")
    store.publish_batch(
        feed_key=feed_key,
        batch_id="batch-min-health",
        snapshots=[{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:35:00", "close": "10.20"}],
        meta={
            "received_at": "2026-06-01T10:35:01+08:00",
            "published_at": "2026-06-01T10:35:02+08:00",
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
        feed_key,
        {
            "collector_running": True,
            "collector_id": "minute:1",
            "request_count_last_minute": 1,
            "invalid_count": 2,
            "invalid_reason_counts": {"missing_freq": 2},
            "last_batch_event_id": "1-0",
            "delta_count_last_batch": 0,
        },
    )
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get(
        "/api/v1/ops/realtime/stock-rt-min/health",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "股票实时分钟"
    assert payload["configured_freqs"] == ["1MIN", "5MIN"]
    assert payload["supported_freqs"] == list(STOCK_RT_MIN_ALLOWED_FREQS)
    assert [item["freq"] for item in payload["items"]] == list(STOCK_RT_MIN_ALLOWED_FREQS)
    by_freq = {item["freq"]: item for item in payload["items"]}
    assert by_freq["1MIN"]["feed_key"] == feed_key
    assert by_freq["1MIN"]["current_batch_id"] == "batch-min-health"
    assert by_freq["1MIN"]["invalid_count"] == 2
    assert by_freq["1MIN"]["invalid_reason_counts"] == {"missing_freq": 2}
    assert by_freq["15MIN"]["enabled"] is False
    assert by_freq["15MIN"]["status"] == "idle"


def test_ops_stock_rt_min_health_api_can_filter_single_freq(
    app_client,
    auth_token,
    monkeypatch,
    trade_calendar_factory,
) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,5MIN")
    get_settings.cache_clear()
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    store = InMemoryRealtimeStateStore()
    app.dependency_overrides[get_realtime_state_store] = lambda: store

    response = app_client.get(
        "/api/v1/ops/realtime/stock-rt-min/health?freq=1MIN",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["freq"] for item in payload["items"]] == ["1MIN"]


def test_ops_stock_rt_min_health_api_rejects_invalid_freq(app_client, auth_token) -> None:
    response = app_client.get(
        "/api/v1/ops/realtime/stock-rt-min/health?freq=BAD",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_FREQ"


def test_ops_stock_rt_min_health_query_marks_stale_and_degraded(db_session, trade_calendar_factory, monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,5MIN")
    get_settings.cache_clear()
    trade_calendar_factory(exchange="SSE", trade_date=datetime(2026, 6, 1).date(), is_open=True)
    config = get_realtime_stock_rt_min_config()
    store = InMemoryRealtimeStateStore()
    stale_feed_key = config.feed_key_for_freq("1MIN")
    degraded_feed_key = config.feed_key_for_freq("5MIN")
    store.publish_batch(
        feed_key=stale_feed_key,
        batch_id="batch-stale",
        snapshots=[{"ts_code": "600000.SH", "freq": "1MIN", "time": "2026-06-01 10:30:00"}],
        meta={"received_at": "2026-06-01T10:30:00+08:00", "published_at": "2026-06-01T10:30:00+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.publish_batch(
        feed_key=degraded_feed_key,
        batch_id="batch-degraded",
        snapshots=[{"ts_code": "600000.SH", "freq": "5MIN", "time": "2026-06-01 10:35:00"}],
        meta={"received_at": "2026-06-01T10:35:00+08:00", "published_at": "2026-06-01T10:35:00+08:00", "source_row_count": 1},
        ttl_seconds=259200,
        keep_recent_batches=3,
        batch_stream_maxlen=5000,
        delta_stream_maxlen=200000,
    )
    store.set_health(degraded_feed_key, {"status": "degraded", "last_error_message": "boom"})

    result = RealtimeFeedHealthQueryService(
        store=store,
        now_provider=lambda: datetime(2026, 6, 1, 10, 35, 0, tzinfo=CN_TIMEZONE),
    ).build_stock_rt_min_health(db_session)

    by_freq = {item.freq: item for item in result.items}
    assert by_freq["1MIN"].status == "stale"
    assert by_freq["5MIN"].status == "degraded"
    assert result.status == "degraded"
    assert result.page_polling_enabled is True


def test_ops_stock_rt_min_health_api_returns_unavailable_for_enabled_freq_on_redis_failure(
    app_client,
    auth_token,
    monkeypatch,
    trade_calendar_factory,
) -> None:
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED", "true")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN")
    get_settings.cache_clear()
    today = datetime.now(CN_TIMEZONE).date()
    trade_calendar_factory(exchange="SSE", trade_date=today, is_open=True)
    app.dependency_overrides[get_realtime_state_store] = lambda: UnavailableRealtimeStateStore("redis down")

    response = app_client.get(
        "/api/v1/ops/realtime/stock-rt-min/health",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    by_freq = {item["freq"]: item for item in payload["items"]}
    assert by_freq["1MIN"]["status"] == "unavailable"
    assert by_freq["1MIN"]["redis_connected"] is False
    assert by_freq["5MIN"]["enabled"] is False
