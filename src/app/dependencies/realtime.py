from __future__ import annotations

from src.foundation.config.settings import get_settings
from src.foundation.realtime import RealtimeStateStore, build_realtime_state_store


def get_realtime_state_store() -> RealtimeStateStore:
    return build_realtime_state_store(get_settings().redis_url)
