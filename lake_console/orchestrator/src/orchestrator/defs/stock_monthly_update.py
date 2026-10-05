"""Pure completed-month planning; dates and daily intents are separate coordinates."""

from dataclasses import asdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.stock_monthly import (
    MONTHLY_UPDATE_POLICY,
    StockMonthlySource,
    month_window,
    monthly_contract_hash,
    normalize_month_key,
)


def local_monthly_time(now):
    if now.tzinfo is None:
        raise ValueError("monthly_time_must_be_aware")
    return now.astimezone(ZoneInfo(MONTHLY_UPDATE_POLICY.timezone))


def monthly_window_open(now):
    return (
        local_monthly_time(now).strftime("%H:%M")
        >= MONTHLY_UPDATE_POLICY.daily_start_time
    )


def completed_month(now, month):
    _, upper = month_window(month)
    return upper <= local_monthly_time(now).date()


def next_month(month):
    normalize_month_key(month)
    return month_window(month)[1].strftime("%Y-%m")


def monthly_open_dates(month, calendar):
    first, upper = month_window(month)
    expected = tuple(
        (first + timedelta(days=i)).isoformat() for i in range((upper - first).days)
    )
    if set(calendar) != set(expected) or any(
        type(v) is not int or v not in (0, 1) for v in calendar.values()
    ):
        raise ValueError("monthly_calendar_incomplete")
    return tuple(day for day in expected if calendar[day])


def monthly_update_intent(source, month, intent_date):
    source = StockMonthlySource(source)
    normalize_month_key(month)
    if date.fromisoformat(intent_date).isoformat() != intent_date:
        raise ValueError("monthly_intent_date_invalid")
    if month_window(month)[1] > date.fromisoformat(intent_date):
        raise ValueError("monthly_period_not_completed")
    intent = {
        "source": source.value,
        "month": month,
        "daily_intent_date": intent_date,
        "policy": asdict(MONTHLY_UPDATE_POLICY),
    }
    return {**intent, "unit_id": monthly_contract_hash(intent)}
