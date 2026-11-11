"""Existing weekly sensor configuration; execution belongs to stock_period_update."""

from dataclasses import dataclass

from orchestrator.defs.run_contracts.stock_period import STOCK_PERIOD_DAILY_START_TIME


@dataclass(frozen=True)
class WeeklyUpdatePolicy:
    timezone: str = "Asia/Shanghai"
    daily_start_time: str = STOCK_PERIOD_DAILY_START_TIME
    tick_min_seconds: int = 60


WEEKLY_UPDATE_POLICY = WeeklyUpdatePolicy()
