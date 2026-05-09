from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MacdParams:
    fast: int
    slow: int
    signal: int
    params_key: str
    indicator_version: int = 1


@dataclass(frozen=True)
class MacdState:
    ts_code: str
    freq: int
    last_trade_time: datetime
    ema_fast: float
    ema_slow: float
    dea: float


@dataclass(frozen=True)
class MacdCalculationResult:
    rows: list[dict[str, Any]]
    final_state: MacdState | None
