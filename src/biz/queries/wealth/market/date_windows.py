from calendar import monthrange
from datetime import date


def months_before(day: date, months: int) -> date:
    """Shift a date back by calendar months, clamping to the target month end."""
    year, zero_based_month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = zero_based_month + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))
