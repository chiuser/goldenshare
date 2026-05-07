from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from src.foundation.clients.tushare_client import _API_RATE_LIMITS, _RateLimiter, TushareHttpClient, TushareRateLimitError


def test_tushare_http_client_builds_session_with_post_retries() -> None:
    client = TushareHttpClient(token="token")

    https_adapter = client.session.adapters["https://"]
    retry = https_adapter.max_retries

    assert retry.total == 5
    assert retry.connect == 5
    assert retry.read == 5
    assert retry.other == 3
    assert retry.allowed_methods is None


def test_tushare_http_client_uses_session_post_with_timeout_tuple(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 0,
        "msg": "ok",
        "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=()))
    post = mocker.patch.object(client.session, "post", return_value=response)

    rows = client.call("daily", params={"ts_code": "000001.SZ"}, fields=["ts_code"])

    assert rows == [{"ts_code": "000001.SZ"}]
    post.assert_called_once_with(
        client.base_url,
        json={
            "api_name": "daily",
            "token": "token",
            "params": {"ts_code": "000001.SZ"},
            "fields": "ts_code",
        },
        timeout=(5, 30),
    )


def test_tushare_http_client_logs_and_reraises_request_exception(mocker) -> None:
    client = TushareHttpClient(token="token")
    mocker.patch.object(
        client.session,
        "post",
        side_effect=requests.exceptions.SSLError("boom"),
    )
    logger = mocker.patch.object(client, "logger")

    with pytest.raises(requests.exceptions.SSLError):
        client.call("daily", params={"ts_code": "000001.SZ", "trade_date": "20260324"})

    logger.warning.assert_called_once()


def test_tushare_http_client_logs_retry_success(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 0,
        "msg": "ok",
        "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=(object(), object())))
    mocker.patch.object(client.session, "post", return_value=response)
    logger = mocker.patch.object(client, "logger")

    client.call("daily", params={"ts_code": "000001.SZ"})

    logger.info.assert_called_once()


def test_tushare_index_daily_rate_limit_keeps_safety_margin() -> None:
    assert _API_RATE_LIMITS["index_daily"] == 420
    assert _API_RATE_LIMITS["index_daily"] < 500


def test_tushare_rate_limiter_spaces_calls_evenly(mocker) -> None:
    limiter = _RateLimiter(max_calls_per_minute=120)
    current_time = [100.0]
    sleeps: list[float] = []

    mocker.patch("src.foundation.clients.tushare_client.time.monotonic", side_effect=lambda: current_time[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time[0] += seconds

    mocker.patch("src.foundation.clients.tushare_client.time.sleep", side_effect=fake_sleep)

    limiter.acquire()
    limiter.acquire()

    assert sleeps == [pytest.approx(0.5)]


def test_tushare_http_client_raises_rate_limit_error_for_business_quota_response(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": -2002,
        "msg": "抱歉，您访问接口(index_daily)频率超限(500次/分钟)",
        "data": None,
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=()))
    mocker.patch.object(client.session, "post", return_value=response)

    with pytest.raises(TushareRateLimitError) as exc_info:
        client.call("index_daily", params={"ts_code": "000001.SH", "trade_date": "20260424"})

    assert exc_info.value.api_name == "index_daily"
    assert "频率超限" in str(exc_info.value)
