from __future__ import annotations

import pytest

from lake_console.backend.app.services.tushare_client import (
    TushareLakeClient,
    TushareQuotaExceededError,
    TushareRateLimiter,
)


def test_tushare_rate_limiter_uses_configured_per_minute_interval():
    now = 100.0
    sleeps: list[float] = []

    def clock() -> float:
        return now + sum(sleeps)

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    limiter = TushareRateLimiter(request_limit_per_minute=500, clock=clock, sleeper=sleeper)

    limiter.wait()
    limiter.wait()

    assert sleeps == pytest.approx([0.12])


def test_tushare_rate_limiter_rejects_invalid_limit():
    with pytest.raises(ValueError):
        TushareRateLimiter(request_limit_per_minute=0)


def test_tushare_request_rewraps_daily_quota_error():
    client = object.__new__(TushareLakeClient)
    client._rate_limiter = TushareRateLimiter(request_limit_per_minute=500)

    def quota_method(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("抱歉，您访问接口(stk_mins)频率超限(250000次/天)")

    with pytest.raises(TushareQuotaExceededError) as exc:
        client._request(quota_method, api_name="stk_mins")

    assert exc.value.api_name == "stk_mins"
    assert "250000次/天" in str(exc.value)


def test_tushare_request_keeps_non_quota_error_original():
    client = object.__new__(TushareLakeClient)
    client._rate_limiter = TushareRateLimiter(request_limit_per_minute=500)

    def failing_method(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("普通参数错误")

    with pytest.raises(RuntimeError, match="普通参数错误"):
        client._request(failing_method, api_name="stk_mins")
