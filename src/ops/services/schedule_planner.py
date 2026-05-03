from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.app.exceptions import WebAppError


SUPPORTED_SCHEDULE_TYPES = {"once", "cron"}
SUPPORTED_CALENDAR_POLICIES = {"monthly_last_day", "monthly_window_current_month"}


@dataclass(frozen=True, slots=True)
class CronExpression:
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    dom_wildcard: bool
    dow_wildcard: bool


def ensure_schedule_type(schedule_type: str) -> None:
    if schedule_type not in SUPPORTED_SCHEDULE_TYPES:
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"不支持的排程类型：{schedule_type}",
        )


def ensure_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise WebAppError(status_code=422, code="validation_error", message="排程时区无效") from exc


def normalize_schedule_datetime(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"{_schedule_datetime_label(field_name)}必须包含时区信息",
        )
    return value.astimezone(timezone.utc)


def _schedule_datetime_label(field_name: str) -> str:
    labels = {
        "next_run_at": "下次运行时间",
        "after": "排程计算时间",
    }
    return labels.get(field_name, field_name)


def compute_next_run_at(
    *,
    schedule_type: str,
    timezone_name: str,
    after: datetime,
    cron_expr: str | None = None,
    calendar_policy: str | None = None,
) -> datetime | None:
    ensure_schedule_type(schedule_type)
    calendar_policy = _normalize_calendar_policy(calendar_policy)
    if after.tzinfo is None:
        raise WebAppError(status_code=422, code="validation_error", message="排程计算时间必须包含时区信息")
    if schedule_type == "once":
        if calendar_policy is not None:
            raise WebAppError(status_code=422, code="validation_error", message="单次排程不支持日期策略")
        return None
    if schedule_type == "cron":
        if not cron_expr:
            raise WebAppError(status_code=422, code="validation_error", message="周期排程必须填写周期表达式")
        zone = ensure_timezone(timezone_name)
        if calendar_policy in {"monthly_last_day", "monthly_window_current_month"}:
            return _next_monthly_last_day_occurrence(cron_expr, after=after, zone=zone)
        return _next_cron_occurrence(cron_expr, after=after, zone=zone)
    raise WebAppError(status_code=422, code="validation_error", message=f"不支持的排程类型：{schedule_type}")


def preview_schedule_runs(
    *,
    schedule_type: str,
    timezone_name: str,
    count: int = 5,
    after: datetime | None = None,
    cron_expr: str | None = None,
    next_run_at: datetime | None = None,
    calendar_policy: str | None = None,
) -> list[datetime]:
    ensure_schedule_type(schedule_type)
    calendar_policy = _normalize_calendar_policy(calendar_policy)
    count = max(1, min(count, 10))
    now = after or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise WebAppError(status_code=422, code="validation_error", message="排程预览时间必须包含时区信息")

    if schedule_type == "once":
        if calendar_policy is not None:
            raise WebAppError(status_code=422, code="validation_error", message="单次排程不支持日期策略")
        resolved_next_run = normalize_schedule_datetime(next_run_at, field_name="next_run_at")
        if resolved_next_run is None:
            raise WebAppError(status_code=422, code="validation_error", message="单次排程必须填写下次运行时间")
        return [resolved_next_run]

    runs: list[datetime] = []
    cursor = now
    for _ in range(count):
        next_occurrence = compute_next_run_at(
            schedule_type=schedule_type,
            timezone_name=timezone_name,
            cron_expr=cron_expr,
            after=cursor,
            calendar_policy=calendar_policy,
        )
        if next_occurrence is None:
            break
        runs.append(next_occurrence)
        cursor = next_occurrence + timedelta(minutes=1)
    return runs


def _next_cron_occurrence(cron_expr: str, *, after: datetime, zone: ZoneInfo) -> datetime:
    cron = _parse_cron_expr(cron_expr)
    local_after = after.astimezone(zone)
    cursor = local_after.replace(second=0, microsecond=0)
    if cursor <= local_after:
        cursor += timedelta(minutes=1)

    max_checks = 366 * 24 * 60
    for _ in range(max_checks):
        if _cron_matches(cron, cursor):
            return cursor.astimezone(timezone.utc)
        cursor += timedelta(minutes=1)

    raise WebAppError(
        status_code=422,
        code="validation_error",
        message="无法在未来 366 天内计算出下一次运行时间",
    )


def _next_monthly_last_day_occurrence(cron_expr: str, *, after: datetime, zone: ZoneInfo) -> datetime:
    cron = _parse_cron_expr(cron_expr)
    hour, minute = _single_time_from_cron(cron)
    local_after = after.astimezone(zone)
    year = local_after.year
    month = local_after.month

    for _ in range(120):
        last_day = monthrange(year, month)[1]
        candidate = datetime(year, month, last_day, hour, minute, tzinfo=zone)
        if candidate > local_after:
            return candidate.astimezone(timezone.utc)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    raise WebAppError(
        status_code=422,
        code="validation_error",
        message="无法在未来 120 个月内计算出下一次月末运行时间",
    )


def _single_time_from_cron(cron: CronExpression) -> tuple[int, int]:
    if len(cron.hours) != 1 or len(cron.minutes) != 1:
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message="每月最后一天策略必须使用单一执行时间",
        )
    return next(iter(cron.hours)), next(iter(cron.minutes))


def _normalize_calendar_policy(calendar_policy: str | None) -> str | None:
    normalized = str(calendar_policy or "").strip() or None
    if normalized is None:
        return None
    if normalized not in SUPPORTED_CALENDAR_POLICIES:
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"不支持的日期策略：{normalized}",
        )
    return normalized


def _parse_cron_expr(cron_expr: str) -> CronExpression:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise WebAppError(status_code=422, code="validation_error", message="周期表达式必须包含 5 段")

    minute_expr, hour_expr, dom_expr, month_expr, dow_expr = parts
    return CronExpression(
        minutes=_parse_field(minute_expr, minimum=0, maximum=59),
        hours=_parse_field(hour_expr, minimum=0, maximum=23),
        days_of_month=_parse_field(dom_expr, minimum=1, maximum=31),
        months=_parse_field(month_expr, minimum=1, maximum=12),
        days_of_week=_parse_field(dow_expr, minimum=0, maximum=7, normalize_day_of_week=True),
        dom_wildcard=dom_expr == "*",
        dow_wildcard=dow_expr == "*",
    )


def _parse_field(expr: str, *, minimum: int, maximum: int, normalize_day_of_week: bool = False) -> frozenset[int]:
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            raise WebAppError(status_code=422, code="validation_error", message=f"周期表达式字段无效：{expr}")
        values.update(
            _expand_part(
                part,
                minimum=minimum,
                maximum=maximum,
                normalize_day_of_week=normalize_day_of_week,
            )
        )
    return frozenset(values)


def _expand_part(part: str, *, minimum: int, maximum: int, normalize_day_of_week: bool) -> set[int]:
    if "/" in part:
        base, step_str = part.split("/", 1)
        if not step_str.isdigit() or int(step_str) <= 0:
            raise WebAppError(status_code=422, code="validation_error", message=f"周期表达式步长无效：{part}")
        step = int(step_str)
    else:
        base = part
        step = 1

    if base == "*":
        start = minimum
        end = maximum
    elif "-" in base:
        start_str, end_str = base.split("-", 1)
        start = _parse_numeric_value(start_str, minimum=minimum, maximum=maximum, normalize_day_of_week=normalize_day_of_week)
        end = _parse_numeric_value(end_str, minimum=minimum, maximum=maximum, normalize_day_of_week=normalize_day_of_week)
        if end < start:
            raise WebAppError(status_code=422, code="validation_error", message=f"周期表达式范围无效：{part}")
    else:
        value = _parse_numeric_value(base, minimum=minimum, maximum=maximum, normalize_day_of_week=normalize_day_of_week)
        return {value}

    return {_normalize_value(value, normalize_day_of_week) for value in range(start, end + 1, step)}


def _parse_numeric_value(raw: str, *, minimum: int, maximum: int, normalize_day_of_week: bool) -> int:
    if not raw.isdigit():
        raise WebAppError(status_code=422, code="validation_error", message=f"周期表达式包含非数字值：{raw}")
    value = int(raw)
    normalized = _normalize_value(value, normalize_day_of_week)
    if normalized < minimum or normalized > maximum:
        raise WebAppError(status_code=422, code="validation_error", message=f"周期表达式数值超出范围：{raw}")
    return normalized


def _normalize_value(value: int, normalize_day_of_week: bool) -> int:
    if normalize_day_of_week and value == 7:
        return 0
    return value


def _cron_matches(cron: CronExpression, local_dt: datetime) -> bool:
    cron_weekday = local_dt.isoweekday() % 7
    dom_match = local_dt.day in cron.days_of_month
    dow_match = cron_weekday in cron.days_of_week

    if cron.dom_wildcard and cron.dow_wildcard:
        day_match = True
    elif cron.dom_wildcard:
        day_match = dow_match
    elif cron.dow_wildcard:
        day_match = dom_match
    else:
        day_match = dom_match or dow_match

    return (
        local_dt.minute in cron.minutes
        and local_dt.hour in cron.hours
        and local_dt.month in cron.months
        and day_match
    )
