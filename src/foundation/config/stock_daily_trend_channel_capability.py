from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path

from src.foundation.clients.local_lake.stock_daily_trend_channel_contract import (
    FORMAL_LAKE_ROOT,
    stock_daily_trend_channel_dataset_root,
    stock_daily_trend_channel_state_dataset_root,
)
from src.foundation.config.settings import Settings


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelCapability:
    enabled: bool
    lake_root: Path | None
    reason_code: str | None


def resolve_stock_daily_trend_channel_capability(
    settings: Settings,
) -> StockDailyTrendChannelCapability:
    """Resolve the independent local-only stock trend-channel capability."""

    environment = (settings.app_env or os.getenv("APP_ENV", "")).strip().lower()
    if (
        environment not in {"dev", "local"}
        or not settings.wealth_local_lake_stock_daily_trend_channel_api_enabled
    ):
        return StockDailyTrendChannelCapability(False, None, None)

    raw_root = settings.goldenshare_lake_root.strip()
    if not raw_root:
        return StockDailyTrendChannelCapability(
            False,
            None,
            "STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
        )

    lake_root = Path(raw_root).expanduser().resolve()
    if lake_root != FORMAL_LAKE_ROOT.resolve():
        return StockDailyTrendChannelCapability(
            False,
            lake_root,
            "STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
        )
    if not lake_root.is_dir() or not os.access(lake_root, os.R_OK):
        return StockDailyTrendChannelCapability(
            False,
            lake_root,
            "STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
        )
    if importlib.util.find_spec("duckdb") is None:
        return StockDailyTrendChannelCapability(
            False,
            lake_root,
            "STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
        )

    result_root = stock_daily_trend_channel_dataset_root(lake_root)
    state_root = stock_daily_trend_channel_state_dataset_root(lake_root)
    if not all(
        path.is_dir() and os.access(path, os.R_OK)
        for path in (result_root, state_root)
    ):
        return StockDailyTrendChannelCapability(
            False,
            lake_root,
            "STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
        )
    return StockDailyTrendChannelCapability(True, lake_root, None)
