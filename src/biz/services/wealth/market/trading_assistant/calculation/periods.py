"""§6.4/6.6: independent per-account window accumulators, without IO."""

from dataclasses import dataclass
from datetime import date, timedelta
import calendar

from .precision import CalculationInvariantError, require_integer
from .returns import ProfitResult, profit_result


@dataclass(frozen=True, slots=True)
class PeriodCapital:
    account_id: str
    idle_cash_cents: int
    reusable_cash_cents: int
    principal_cents: int
    last_date: date | None = None

    def __post_init__(self) -> None:
        if not self.account_id:
            raise CalculationInvariantError("Missing account identity")
        for n in (self.idle_cash_cents, self.reusable_cash_cents, self.principal_cents):
            require_integer(n, minimum=0)


@dataclass(frozen=True, slots=True)
class DayCash:
    account_id: str
    business_date: date
    cash_in_cents: int
    cash_out_cents: int
    buy_investment_cents: int
    sell_net_cents: int
    closing_cash_cents: int

    def __post_init__(self) -> None:
        for n in (self.cash_in_cents, self.cash_out_cents, self.buy_investment_cents, self.closing_cash_cents):
            require_integer(n, minimum=0)
        require_integer(self.sell_net_cents)
        if type(self.business_date) is not date:
            raise CalculationInvariantError("Invalid business date")


def start_period(account_id: str, opening_cash_cents: int, opening_cost_cents: int) -> PeriodCapital:
    return PeriodCapital(account_id, opening_cash_cents, 0, opening_cost_cents)


def advance_period(state: PeriodCapital, day: DayCash) -> PeriodCapital:
    if state.account_id != day.account_id or (state.last_date is not None and day.business_date <= state.last_date):
        raise CalculationInvariantError("Mixed account or repeated/out-of-order day")
    idle = state.idle_cash_cents + day.cash_in_cents
    reusable = state.reusable_cash_cents + day.sell_net_cents
    if reusable < 0:
        idle += reusable
        reusable = 0
    reused = min(reusable, day.buy_investment_cents)
    reusable -= reused
    new_principal = day.buy_investment_cents - reused
    idle -= new_principal
    if idle < 0:
        raise CalculationInvariantError("Insufficient registered cash")
    idle_out = min(idle, day.cash_out_cents)
    idle -= idle_out
    reusable -= day.cash_out_cents - idle_out
    if reusable < 0 or idle + reusable != day.closing_cash_cents:
        raise CalculationInvariantError("Cash reconciliation failed")
    return PeriodCapital(state.account_id, idle, reusable, state.principal_cents + new_principal, day.business_date)


def whole_period_return(state: PeriodCapital, profit_cents: int | None, *, participates: bool) -> ProfitResult:
    return profit_result(profit_cents, state.principal_cents, participates=participates)


@dataclass(frozen=True, slots=True)
class PeriodReturnAccumulator:
    """Bounded daily continuation; no transaction or round history is retained."""
    capital: PeriodCapital
    profit_cents: int | None

    def __post_init__(self) -> None:
        if self.profit_cents is not None:
            require_integer(self.profit_cents)


def start_return_period(account_id: str, opening_cash_cents: int, opening_cost_cents: int) -> PeriodReturnAccumulator:
    return PeriodReturnAccumulator(start_period(account_id, opening_cash_cents, opening_cost_cents), 0)


def advance_return_period(state: PeriodReturnAccumulator, day: DayCash, daily_result: ProfitResult) -> PeriodReturnAccumulator:
    """Daily profit is an endpoint difference including same-day closed rounds.

    Caller selects a consistent valuation basis. Daily denominators are NEVER
    summed; capital follows the independent window's cash-reuse accumulator.
    """
    capital = advance_period(state.capital, day)
    if state.profit_cents is None or daily_result.status == "Delayed":
        profit = None
    else:
        profit = state.profit_cents + (daily_result.profit_cents if daily_result.status == "Ready" else 0)
    return PeriodReturnAccumulator(capital, profit)


def finish_return_period(state: PeriodReturnAccumulator) -> ProfitResult:
    return whole_period_return(state.capital, state.profit_cents, participates=state.capital.principal_cents > 0)


def stock_period_return(opening_cost_cents: int, buy_investment_cents: int,
                         profit_cents: int | None, *, participates: bool) -> ProfitResult:
    require_integer(opening_cost_cents, minimum=0)
    require_integer(buy_investment_cents, minimum=0)
    return profit_result(profit_cents, opening_cost_cents + buy_investment_cents, participates=participates)


def calendar_window(day: date, granularity: str) -> tuple[date, date]:
    if type(day) is not date:
        raise CalculationInvariantError("Expected business date")
    if granularity == "DAY":
        return day, day
    if granularity == "WEEK":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if granularity == "MONTH":
        return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])
    raise CalculationInvariantError("Unknown granularity")
