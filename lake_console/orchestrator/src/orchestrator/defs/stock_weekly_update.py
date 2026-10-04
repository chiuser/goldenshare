"""Pure weekly update policy and completed-period intent planning."""

from dataclasses import asdict, dataclass
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    normalize_week_key,
    stable_weekly_hash,
)

AUTOMATIC_WEEKLY_SOURCES = (
    StockWeeklySource.PRIMARY_UNADJUSTED,
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


def weekly_update_intent(source, week, intent_date, policy=WEEKLY_UPDATE_POLICY):
    source = StockWeeklySource(source)
    if source not in AUTOMATIC_WEEKLY_SOURCES:
        raise ValueError("alternate_automatic_forbidden")
    normalize_week_key(week)
    parsed = date.fromisoformat(intent_date)
    if parsed.isoformat() != intent_date or parsed < date.fromisoformat(week):
        raise ValueError("invalid_weekly_intent_date")
    payload = {
        "source": source.value,
        "week": week,
        "daily_intent_date": intent_date,
        "policy": asdict(policy),
    }
    return {**payload, "unit_id": stable_weekly_hash(payload)}


def weekly_manual_next_action(source):
    if source is StockWeeklySource.PRIMARY_UNADJUSTED:
        return "查看主源证据；必要时明确代码和周范围手动运行备用weekly，仅写独立Raw；当前未执行备用。"
    return "查看复权主源证据；weekly不提供复权，不能替代此资产。"
