from __future__ import annotations

import pytest

from lake_console.backend.app.services.tushare_client import TushareRateLimiter


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
