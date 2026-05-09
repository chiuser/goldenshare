from __future__ import annotations

from lake_console.backend.app.services.indicators.models import MacdParams


DEFAULT_MACD_PARAMS = MacdParams(
    fast=12,
    slow=26,
    signal=9,
    params_key="12_26_9",
    indicator_version=1,
)
