"""Existing weekly sensor configuration; execution belongs to stock_period_update."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WeeklyUpdatePolicy:
    timezone: str = "Asia/Shanghai"
    daily_start_time: str = "19:30"
    tick_min_seconds: int = 60


WEEKLY_UPDATE_POLICY = WeeklyUpdatePolicy()
