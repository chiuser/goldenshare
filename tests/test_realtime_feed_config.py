from __future__ import annotations

import os

import pytest

from src.foundation.config.settings import get_settings
from src.foundation.realtime import get_realtime_runtime_config, normalize_stock_rt_min_freq


def test_realtime_feed_config_defaults_are_valid(monkeypatch) -> None:
    _reset_realtime_env(monkeypatch)

    config = get_realtime_runtime_config()

    assert config.redis_url == "redis://127.0.0.1:6379/0"
    assert config.stock_rt_daily.lease_ttl_seconds == 30
    assert config.stock_rt_daily.storage.snapshot_ttl_seconds == 259200
    assert config.stock_rt_min.enabled is False
    assert config.stock_rt_min.enabled_freqs == ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
    assert config.stock_rt_min.poll_interval_seconds == 60
    assert config.stock_rt_min.feed_key_for_freq("1min") == "tushare_stock_rt_min_1min"


def test_realtime_feed_config_reads_env_overrides(monkeypatch) -> None:
    _reset_realtime_env(monkeypatch)
    monkeypatch.setenv("REALTIME_STOCK_RT_DAILY_LEASE_TTL_SECONDS", "42")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,30MIN")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_POLL_INTERVAL_SECONDS", "20")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE", "12")
    get_settings.cache_clear()

    config = get_realtime_runtime_config()

    assert config.stock_rt_daily.lease_ttl_seconds == 42
    assert config.stock_rt_min.enabled_freqs == ("1MIN", "30MIN")
    assert config.stock_rt_min.poll_interval_seconds == 20
    assert config.stock_rt_min.max_calls_per_minute == 12


def test_realtime_feed_config_rejects_invalid_minute_frequency(monkeypatch) -> None:
    _reset_realtime_env(monkeypatch)
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", "1MIN,BAD")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="invalid stock realtime minute freq"):
        get_realtime_runtime_config()


def test_realtime_feed_config_rejects_empty_minute_frequency_list(monkeypatch) -> None:
    _reset_realtime_env(monkeypatch)
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_ENABLED_FREQS", ", ,")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="cannot be empty"):
        get_realtime_runtime_config()


def test_realtime_feed_config_rejects_underprovisioned_request_budget(monkeypatch) -> None:
    _reset_realtime_env(monkeypatch)
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_POLL_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE", "4")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="cannot cover"):
        get_realtime_runtime_config()


def test_normalize_stock_rt_min_freq_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        normalize_stock_rt_min_freq("2MIN")


def _reset_realtime_env(monkeypatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("REALTIME_") or key == "REDIS_URL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", "/private/tmp/goldenshare-test-missing.env")
    get_settings.cache_clear()
