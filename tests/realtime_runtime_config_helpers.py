from __future__ import annotations

from copy import deepcopy

from sqlalchemy.orm import Session

from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import build_realtime_runtime_config_from_json, load_realtime_runtime_config


DEFAULT_DAILY_RUNTIME_CONFIG = {
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

DEFAULT_MIN_RUNTIME_CONFIG = {
    "enabled": False,
    "enabled_freqs": ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
    "poll_interval_seconds": 60,
    "max_calls_per_minute": 20,
    "lease_ttl_seconds": 90,
    "stale_after_seconds": 90,
    "snapshot_ttl_seconds": 259200,
    "keep_recent_batches": 3,
    "batch_stream_maxlen": 5000,
    "delta_stream_maxlen": 200000,
    "source_timeout_seconds": 20,
}


def seed_realtime_runtime_config(
    session: Session,
    *,
    daily: dict | None = None,
    minute: dict | None = None,
) -> None:
    daily_config = _merged_config(DEFAULT_DAILY_RUNTIME_CONFIG, daily)
    minute_config = _merged_config(DEFAULT_MIN_RUNTIME_CONFIG, minute)
    session.merge(
        RealtimeRuntimeConfigRecord(
            object_key="stock_rt_daily",
            object_kind="collector_feed",
            runtime_config_json=daily_config,
            version=1,
            requires_collector_restart=True,
        )
    )
    session.merge(
        RealtimeRuntimeConfigRecord(
            object_key="stock_rt_min",
            object_kind="feed_group",
            runtime_config_json=minute_config,
            version=1,
            requires_collector_restart=True,
        )
    )
    session.commit()


def load_test_realtime_runtime_config(
    session: Session,
    *,
    daily: dict | None = None,
    minute: dict | None = None,
):
    seed_realtime_runtime_config(session, daily=daily, minute=minute)
    return load_realtime_runtime_config(session)


def make_realtime_runtime_config(
    *,
    daily: dict | None = None,
    minute: dict | None = None,
):
    return build_realtime_runtime_config_from_json(
        daily_config=_merged_config(DEFAULT_DAILY_RUNTIME_CONFIG, daily),
        minute_config=_merged_config(DEFAULT_MIN_RUNTIME_CONFIG, minute),
    )


def _merged_config(defaults: dict, overrides: dict | None) -> dict:
    result = deepcopy(defaults)
    if overrides:
        result.update(overrides)
    return result
