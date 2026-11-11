from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.ingestion.index_month_calendar import load_complete_open_dates
from src.foundation.ingestion.index_period_serving import MARKET_CLOSE, SHANGHAI
from src.ops.models.ops.task_run import TaskRun


WEEKLY_LAST_TRADING_DAY = "weekly_last_trading_day"
MONTHLY_FIRST_TRADING_DAY = "monthly_first_trading_day"
TRADING_DAY_POINT = "trading_day_point"
INDEX_PERIOD_CALENDAR_POLICIES = frozenset({
    WEEKLY_LAST_TRADING_DAY, MONTHLY_FIRST_TRADING_DAY, TRADING_DAY_POINT,
})


def is_scheduled_index_monthly_raw_task(task: TaskRun) -> bool:
    return (
        task.task_type == "dataset_action" and task.resource_key == "index_monthly"
        and task.action == "maintain" and task.schedule_id is not None
        and task.trigger_source in {"scheduled", "schedule", "retry"}
    )


def index_period_schedule_time(
    policy: str, schedule_type: str, cron_expr: str | None, timezone_name: str,
) -> time:
    if schedule_type != "cron" or timezone_name != SHANGHAI.key:
        raise WebAppError(status_code=422, code="validation_error", message="指数周、月线自动任务使用上海时区的周期排程。")
    parts = (cron_expr or "").split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"] or not all(part.isdecimal() for part in parts[:2]):
        raise WebAppError(status_code=422, code="validation_error", message="指数周、月线自动任务只填写一个执行时刻。")
    minute, hour = map(int, parts[:2])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise WebAppError(status_code=422, code="validation_error", message="执行时刻必须是有效的小时和分钟。")
    configured = time(hour, minute)
    earliest = time(19) if policy == MONTHLY_FIRST_TRADING_DAY else MARKET_CLOSE
    if configured < earliest:
        raise WebAppError(status_code=422, code="validation_error", message=f"执行时刻须为上海时间 {earliest:%H:%M} 或之后。")
    return configured


def _open_dates(session: Session, start: date, end: date) -> tuple[date, ...]:
    dates = load_complete_open_dates(session, exchange=get_settings().default_exchange, start=start, end=end)
    if dates is None:
        raise WebAppError(
            status_code=422, code="validation_error",
            message=f"{start} 至 {end} 的交易日历不完整，请先更新交易日历。",
        )
    return dates


def next_index_period_occurrence(session: Session, policy: str, at: time, after: datetime) -> datetime:
    local_after = after.astimezone(SHANGHAI)
    day = local_after.date()
    while True:
        if policy == MONTHLY_FIRST_TRADING_DAY:
            start = day.replace(day=1)
            end = day.replace(day=monthrange(day.year, day.month)[1])
            candidates = _open_dates(session, start, end)[:1]
        else:
            start = day - timedelta(days=day.weekday()) if policy == WEEKLY_LAST_TRADING_DAY else day
            end = day + timedelta(days=6 - day.weekday())
            candidates = _open_dates(session, start, end)
            if policy == WEEKLY_LAST_TRADING_DAY:
                candidates = candidates[-1:]
        for candidate in candidates:
            occurrence = datetime.combine(candidate, at, tzinfo=SHANGHAI)
            if occurrence > local_after:
                return occurrence.astimezone(timezone.utc)
        day = end + timedelta(days=1)


def index_period_target_date(session: Session, policy: str, scheduled_at: datetime) -> date:
    day = scheduled_at.astimezone(SHANGHAI).date()
    if policy != MONTHLY_FIRST_TRADING_DAY:
        return day
    previous_month_end = day.replace(day=1) - timedelta(days=1)
    dates = _open_dates(session, previous_month_end.replace(day=1), previous_month_end)
    if not dates:
        raise WebAppError(status_code=422, code="validation_error", message="上月没有可取数的交易日。")
    return dates[-1]
