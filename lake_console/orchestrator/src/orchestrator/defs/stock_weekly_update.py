"""Pure weekly update policy and completed-period intent planning."""

from dataclasses import dataclass
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    normalize_week_key,
)

AUTOMATIC_WEEKLY_SOURCES = (
    StockWeeklySource.PRIMARY_ADJUSTED,
)


@dataclass(frozen=True)
class WeeklyUpdatePolicy:
    version: str = "completed-week-v1"
    timezone: str = "Asia/Shanghai"
    daily_start_time: str = "19:30"
    tick_min_seconds: int = 60
    history_verified_through: str = "2026-09-25"
    max_daily_files: int = 5
    max_reference_rows: int = 50000
    max_control_bytes: int = 1048576
    max_business_sql: int = 8
    max_upstream_check_records: int = 20
    max_materialization_versions_per_period: int = 10


WEEKLY_UPDATE_POLICY = WeeklyUpdatePolicy()


def local_weekly_time(now, policy=WEEKLY_UPDATE_POLICY):
    if now.tzinfo is None:
        raise ValueError("weekly_time_requires_timezone")
    return now.astimezone(ZoneInfo(policy.timezone))


def weekly_window_open(now, policy=WEEKLY_UPDATE_POLICY):
    return local_weekly_time(now, policy).time() >= time.fromisoformat(
        policy.daily_start_time
    )


def next_weekly_period(frontier):
    normalize_week_key(frontier)
    return (date.fromisoformat(frontier) + timedelta(days=7)).isoformat()


def completed_week(now, week, policy=WEEKLY_UPDATE_POLICY):
    normalize_week_key(week)
    return date.fromisoformat(week) <= local_weekly_time(now, policy).date()


def weekly_open_dates(week, calendar):
    """Require all five calendar rows, including closed days; no holiday remap."""
    normalize_week_key(week)
    friday = date.fromisoformat(week)
    expected = tuple((friday - timedelta(days=d)).isoformat() for d in range(4, -1, -1))
    if set(calendar) != set(expected) or any(
        type(value) is not int or value not in (0, 1) for value in calendar.values()
    ):
        raise ValueError("calendar_incomplete")
    return tuple(day for day in expected if calendar[day] == 1)


def weekly_manual_next_action(source):
    StockWeeklySource(source)
    return "核对Prod闭合批；按原批ID和revision恢复复权交付。"
