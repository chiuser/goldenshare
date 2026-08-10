from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.biz.services.quote_trend_channel_query_service import (
    QuoteTrendChannelQueryService,
    TrendChannelComputeError,
    TrendChannelInstrumentMissingError,
    TrendChannelSourceChangingError,
    TrendChannelSourceInvalidError,
    TrendChannelSourceUnavailableError,
    get_quote_trend_channel_cache,
)
from src.foundation.config.settings import get_settings
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


BASE_UPDATED_AT = datetime(2026, 8, 7, 17, 30, tzinfo=timezone.utc)
TREND_CHANNEL_URL = "/api/v1/quote/detail/trend-channel"


@pytest.fixture(autouse=True)
def clear_trend_channel_cache():
    cache = get_quote_trend_channel_cache()
    cache.clear()
    yield
    cache.clear()


def _seed_instrument(db_session, *, name: str | None = "上证指数") -> None:
    db_session.add(
        IndexBasic(
            ts_code="000001.SH",
            name=name,
            market="SSE",
            category="综合",
            created_at=BASE_UPDATED_AT,
            updated_at=BASE_UPDATED_AT,
        )
    )
    db_session.commit()


def _seed_daily_rows(db_session) -> None:
    rows = [
        (date(2026, 8, 5), "10.0000", "11.0000", "9.0000", "10.0000"),
        (date(2026, 8, 6), "10.0000", "13.0000", "10.0000", "13.0000"),
        (date(2026, 8, 7), "12.0000", "12.0000", "10.0000", "11.0000"),
    ]
    db_session.add_all(
        [
            IndexDailyServing(
                ts_code="000001.SH",
                trade_date=trade_date,
                open=Decimal(open_value),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                source="api",
                created_at=BASE_UPDATED_AT,
                updated_at=BASE_UPDATED_AT + timedelta(seconds=index),
            )
            for index, (trade_date, open_value, high, low, close) in enumerate(rows)
        ]
    )
    db_session.commit()


def _seed_ready_source(db_session) -> None:
    _seed_instrument(db_session)
    _seed_daily_rows(db_session)


def test_trend_channel_returns_independent_daily_contract(app_client, db_session) -> None:
    _seed_ready_source(db_session)

    response = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": " 000001.sh ", "period": " DAY ", "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["instrument"] == {
        "ts_code": "000001.SH",
        "name": "上证指数",
        "security_type": "index",
    }
    assert payload["period"] == "day"
    assert payload["adjustment"] == "none"
    assert payload["formula"] == {
        "key": "high-low-ema-hysteresis",
        "version": "sse-daily-trend-channel-v1",
        "short_period": 25,
        "long_period": 90,
        "seed": "first_observation",
        "state_rule": "strict_close_breakout_inside_retention",
    }
    assert payload["data_status"]["status"] == "READY"
    assert payload["data_status"]["observed_trade_date"] == "2026-08-07"
    assert payload["data_status"]["is_provisional"] is False
    assert payload["data_status"]["note"] is None
    assert payload["meta"] == {
        "bar_count": 2,
        "limit": 2,
        "start_date": "2026-08-06",
        "end_date": "2026-08-07",
        "has_more_history": True,
        "next_end_date": "2026-08-05",
    }

    for bar in payload["bars"]:
        assert bar["is_provisional"] is False
        assert set(bar["short_channel"]) == {"upper", "lower", "position", "state"}
        assert set(bar["long_channel"]) == {"upper", "lower", "position", "state"}
        for field in ("open", "high", "low", "close"):
            whole, fraction = bar[field].split(".")
            assert whole
            assert len(fraction) == 4
        for channel_name in ("short_channel", "long_channel"):
            for field in ("upper", "lower"):
                whole, fraction = bar[channel_name][field].split(".")
                assert whole
                assert len(fraction) == 4


def test_trend_channel_limit_and_end_date_slice_without_recalculation_drift(
    app_client,
    db_session,
) -> None:
    _seed_ready_source(db_session)

    latest_one = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": "000001.SH", "limit": 1},
    ).json()
    latest_two = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": "000001.SH", "limit": 2},
    ).json()
    historical = app_client.get(
        TREND_CHANNEL_URL,
        params={
            "ts_code": "000001.SH",
            "end_date": "2026-08-06",
            "limit": 2,
        },
    )

    assert latest_one["bars"][0] == latest_two["bars"][-1]
    assert latest_one["meta"]["next_end_date"] == "2026-08-06"
    assert historical.status_code == 200
    historical_payload = historical.json()
    assert [bar["trade_date"] for bar in historical_payload["bars"]] == [
        "2026-08-05",
        "2026-08-06",
    ]
    assert historical_payload["data_status"]["observed_trade_date"] == "2026-08-07"
    assert historical_payload["meta"]["end_date"] == "2026-08-06"
    assert historical_payload["meta"]["has_more_history"] is False
    assert historical_payload["meta"]["next_end_date"] is None


def test_trend_channel_returns_empty_when_source_has_no_daily_rows(app_client, db_session) -> None:
    _seed_instrument(db_session, name=None)

    response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000001.SH"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["instrument"]["name"] == "上证指数"
    assert payload["data_status"]["status"] == "EMPTY"
    assert payload["data_status"]["observed_trade_date"] is None
    assert payload["data_status"]["note"] == "source_has_no_daily_rows"
    assert payload["bars"] == []
    assert payload["meta"]["bar_count"] == 0


def test_trend_channel_returns_empty_before_first_trade_date(app_client, db_session) -> None:
    _seed_ready_source(db_session)

    response = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": "000001.SH", "end_date": "2026-08-01"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["status"] == "EMPTY"
    assert payload["data_status"]["observed_trade_date"] == "2026-08-07"
    assert payload["data_status"]["note"] == "no_rows_on_or_before_end_date"
    assert payload["bars"] == []


def test_trend_channel_rejects_unsupported_symbol(app_client) -> None:
    response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000300.SH"})

    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_TREND_CHANNEL_SYMBOL"


@pytest.mark.parametrize("period", ["week", "month", "minute120"])
def test_trend_channel_rejects_non_daily_period(app_client, period: str) -> None:
    response = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": "000001.SH", "period": period},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_TREND_CHANNEL_PERIOD"


@pytest.mark.parametrize("limit", [0, 2001])
def test_trend_channel_enforces_limit_range(app_client, limit: int) -> None:
    response = app_client.get(
        TREND_CHANNEL_URL,
        params={"ts_code": "000001.SH", "limit": limit},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_trend_channel_bad_source_row_fails_closed(app_client, db_session) -> None:
    _seed_instrument(db_session)
    db_session.add(
        IndexDailyServing(
            ts_code="000001.SH",
            trade_date=date(2026, 8, 7),
            open=Decimal("10.0000"),
            high=Decimal("9.0000"),
            low=Decimal("11.0000"),
            close=Decimal("10.0000"),
            source="api",
            created_at=BASE_UPDATED_AT,
            updated_at=BASE_UPDATED_AT,
        )
    )
    db_session.commit()

    response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000001.SH"})

    assert response.status_code == 503
    assert response.json()["code"] == "TREND_CHANNEL_SOURCE_INVALID"


def test_trend_channel_missing_index_basic_returns_service_error(app_client) -> None:
    response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000001.SH"})

    assert response.status_code == 503
    assert response.json()["code"] == "TREND_CHANNEL_INSTRUMENT_MISSING"


@pytest.mark.parametrize(
    ("service_error", "expected_status", "expected_code"),
    [
        (
            TrendChannelInstrumentMissingError("missing"),
            503,
            "TREND_CHANNEL_INSTRUMENT_MISSING",
        ),
        (
            TrendChannelSourceUnavailableError("unavailable"),
            503,
            "TREND_CHANNEL_SOURCE_UNAVAILABLE",
        ),
        (
            TrendChannelSourceInvalidError(reason_code="bad_row"),
            503,
            "TREND_CHANNEL_SOURCE_INVALID",
        ),
        (
            TrendChannelSourceChangingError("changing"),
            503,
            "TREND_CHANNEL_SOURCE_CHANGING",
        ),
        (
            TrendChannelComputeError(reason_code="invariant"),
            500,
            "TREND_CHANNEL_COMPUTE_FAILED",
        ),
    ],
)
def test_trend_channel_maps_each_service_error(
    app_client,
    monkeypatch,
    service_error: RuntimeError,
    expected_status: int,
    expected_code: str,
) -> None:
    def fail_build_response(self, session, *, end_date, limit):
        del self, session, end_date, limit
        raise service_error

    monkeypatch.setattr(
        QuoteTrendChannelQueryService,
        "build_response",
        fail_build_response,
    )

    response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000001.SH"})

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


def test_trend_channel_reuses_existing_quote_authentication(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = app_client.get(TREND_CHANNEL_URL, params={"ts_code": "000001.SH"})
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()


def test_shared_kline_response_does_not_gain_trend_channel_fields(app_client, db_session) -> None:
    IndexDailyBasic.__table__.create(db_session.get_bind(), checkfirst=True)
    _seed_ready_source(db_session)

    response = app_client.get(
        "/api/v1/quote/detail/kline",
        params={
            "ts_code": "000001.SH",
            "security_type": "index",
            "period": "day",
            "adjustment": "none",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    bar = response.json()["bars"][0]
    assert "short_channel" not in bar
    assert "long_channel" not in bar
    assert "combined_state" not in bar
