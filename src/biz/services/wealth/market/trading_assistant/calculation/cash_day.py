"""Cash facts do not create profit or invented initialization transactions."""
from dataclasses import dataclass, replace
from datetime import date

from .precision import CalculationInvariantError, require_integer


@dataclass(frozen=True, slots=True)
class CashDayTotals:
    cash_in_cents: int = 0
    cash_out_cents: int = 0
    buy_input_cents: int = 0
    sell_net_cents: int = 0
    record_count: int = 0
    trade_count: int = 0

    def __post_init__(self):
        for n in (self.cash_in_cents, self.cash_out_cents, self.buy_input_cents, self.record_count, self.trade_count):
            require_integer(n, minimum=0)
        require_integer(self.sell_net_cents)
        if self.trade_count > self.record_count:
            raise CalculationInvariantError("Trade count exceeds cash movement count")


def add_cash_movement(totals: CashDayTotals, *, kind: str, direction: str, net_cents: int) -> CashDayTotals:
    require_integer(net_cents)
    if (kind, direction) == ("CASH_FLOW", "IN") and net_cents > 0:
        update = {"cash_in_cents": totals.cash_in_cents + net_cents}
    elif (kind, direction) == ("CASH_FLOW", "OUT") and net_cents < 0:
        update = {"cash_out_cents": totals.cash_out_cents - net_cents}
    elif (kind, direction) == ("TRADE", "BUY") and net_cents < 0:
        update = {"buy_input_cents": totals.buy_input_cents - net_cents}
    elif (kind, direction) == ("TRADE", "SELL"):
        # Tiny sales can have negative net proceeds after the minimum commission.
        update = {"sell_net_cents": totals.sell_net_cents + net_cents}
    else:
        raise CalculationInvariantError("Invalid cash movement kind, direction or sign")
    return replace(totals, **update, record_count=totals.record_count + 1,
                   trade_count=totals.trade_count + int(kind == "TRADE"))


def close_cash_day(totals: CashDayTotals, *, business_date: date, initialized_on: date,
                   initial_cash_cents: int, previous_cash_cents: int | None) -> int | None:
    """Caller walks cash business dates independently of the trading-day calendar.

    The initialization day must be visited, even on a weekend; this function
    never moves initialization to Monday and never creates a day-result row.
    """
    if type(business_date) is not date or type(initialized_on) is not date:
        raise CalculationInvariantError("Invalid cash baseline date")
    require_integer(initial_cash_cents, minimum=0)
    if business_date < initialized_on:
        if previous_cash_cents is not None or totals != CashDayTotals():
            raise CalculationInvariantError("Cannot infer pre-initialization cash history")
        return None
    if business_date == initialized_on:
        if previous_cash_cents is not None:
            raise CalculationInvariantError("Initial cash would be applied twice")
        opening = initial_cash_cents
    else:
        if previous_cash_cents is None:
            raise CalculationInvariantError("Known cash baseline is missing")
        require_integer(previous_cash_cents, minimum=0)
        opening = previous_cash_cents
    closing = opening + totals.cash_in_cents + totals.sell_net_cents - totals.buy_input_cents - totals.cash_out_cents
    if closing < 0:
        raise CalculationInvariantError("Registered day closes with negative cash")
    return closing
