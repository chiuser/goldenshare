"""Archived two-significant-digit arithmetic only; no recognition strategy."""
from decimal import Decimal, ROUND_DOWN

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import number

def decimal_value(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial value")
    return number(str(value))


def quantize_dif(value) -> Decimal:
    x = decimal_value(value)
    if not x:
        return x
    unit = Decimal(1).scaleb(abs(x).adjusted() - 1)
    return (x / unit).to_integral_value(rounding=ROUND_DOWN) * unit
