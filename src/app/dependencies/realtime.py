from __future__ import annotations

from src.foundation.realtime import RealtimeStateStore, build_realtime_state_store, get_realtime_runtime_config


def get_realtime_state_store() -> RealtimeStateStore:
    return build_realtime_state_store(get_realtime_runtime_config().redis_url)
