from __future__ import annotations

from datetime import datetime
from typing import Any

from src.foundation.realtime.runtime_config import RealtimeRuntimeConfig


REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY = "realtime_config_apply_state"


def build_realtime_config_apply_state(
    *,
    config: RealtimeRuntimeConfig,
    collector_id: str,
    process_started_at: str,
    applied_at: datetime,
) -> dict[str, Any]:
    return {
        "collector_id": collector_id,
        "process_started_at": process_started_at,
        "applied_at": applied_at.isoformat(),
        "objects": {
            "stock_rt_daily": {
                "version": config.stock_rt_daily.version,
            },
            "stock_rt_min": {
                "version": config.stock_rt_min.version,
            },
        },
    }
