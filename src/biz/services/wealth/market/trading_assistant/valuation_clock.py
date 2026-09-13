"""Daily time eligibility, not a claim that source prices are complete.

Tushare daily (doc 27) is an after-close source. The 15:00 boundary
is source semantics, not a configurable fee-effective time or publish timer.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .calendar_inputs import CalendarInputs
from .calculation_inputs import CalculationDataUnavailable


def valuation_cutoff(business_date, *, is_open, observed_at):
    if (type(business_date) is not date or type(is_open) is not bool
            or not isinstance(observed_at, datetime) or observed_at.tzinfo is None
            or observed_at.utcoffset() is None):
        raise ValueError("Confirmed calendar date and timezone-aware server time required")
    local = observed_at.astimezone(ZoneInfo("Asia/Shanghai"))
    if business_date > local.date():
        raise CalculationDataUnavailable("Future dates cannot be valued")
    if is_open:
        close = datetime.combine(business_date, time(15), local.tzinfo)
        if local < close:
            raise CalculationDataUnavailable("Daily close is not yet eligible")
        return close
    # Closed dates have cash movement continuation but no stock-day snapshot.
    return min(datetime.combine(business_date, time.max, local.tzinfo), local)


def read_valuation_cutoff(session, execution, lease, *, generation_id, business_date, deadline):
    fact = CalendarInputs(execution).read_date(session, lease, generation_id=generation_id,
        business_date=business_date, deadline=deadline)
    now = session.scalar(select(func.clock_timestamp()))
    deadline.remaining_ms()
    return valuation_cutoff(business_date, is_open=fact["is_open"], observed_at=now)
