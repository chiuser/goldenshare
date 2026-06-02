from __future__ import annotations

from copy import deepcopy

from sqlalchemy.orm import Session

from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import build_realtime_runtime_config_from_json, load_realtime_runtime_config
from src.foundation.realtime.runtime_config_seed_service import (
    DEFAULT_STOCK_RT_DAILY_RUNTIME_CONFIG,
    DEFAULT_STOCK_RT_MIN_RUNTIME_CONFIG,
)


DEFAULT_DAILY_RUNTIME_CONFIG = DEFAULT_STOCK_RT_DAILY_RUNTIME_CONFIG
DEFAULT_MIN_RUNTIME_CONFIG = DEFAULT_STOCK_RT_MIN_RUNTIME_CONFIG


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
