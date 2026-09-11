"""Keep round, current holding and period profit distinct."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from .daily import PositionState
from .fees import FeeAmounts, FeeSnapshot, estimate_liquidation
from .precision import CalculationInvariantError, format_cents, format_return_pct, require_integer, round_ratio_half_up


@dataclass(frozen=True, slots=True)
class ProfitResult:
    status: Literal["Ready", "Empty", "Delayed"]
    profit_cents: int | None
    capital_cents: int | None
    return_pct: str | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "Ready":
            require_integer(self.profit_cents)
            require_integer(self.capital_cents, minimum=1)
            if self.return_pct != format_return_pct(self.profit_cents, self.capital_cents):
                raise CalculationInvariantError("Return result does not match its exact amounts")
        elif self.status not in ("Empty", "Delayed") or any(
            value is not None for value in (self.profit_cents, self.capital_cents, self.return_pct)
        ):
            raise CalculationInvariantError("Unavailable result must not contain invented values")


def profit_result(profit: int | None, capital: int, *, participates: bool) -> ProfitResult:
    require_integer(capital, minimum=0)
    if profit is not None:
        require_integer(profit)
    if type(participates) is not bool:
        raise CalculationInvariantError("Participation must be a boolean fact")
    if not participates:
        if capital != 0 or profit not in (0, None):
            raise CalculationInvariantError("Empty scope contains capital or profit")
        return ProfitResult("Empty", None, None, None)
    if capital <= 0:
        raise CalculationInvariantError("Participating scope has no positive cost basis")
    if profit is None:
        return ProfitResult("Delayed", None, None, None, "估值数据未就绪")
    return ProfitResult("Ready", profit, capital, format_return_pct(profit, capital))


@dataclass(frozen=True, slots=True)
class RoundValuation:
    result: ProfitResult
    dynamic_cost_cents: int
    dynamic_cost_price: str | None
    liquidation: FeeAmounts | None


def value_round(state: PositionState, price: Fraction | None, fees: FeeSnapshot) -> RoundValuation:
    dynamic = state.buy_investment_cents - state.sell_net_cents
    unit = format_cents(round_ratio_half_up(dynamic, state.quantity)) if state.quantity else None
    liquidation = (None if state.quantity and price is None else
                   estimate_liquidation(state.quantity, price if price is not None else Fraction(0), fees))
    profit = (None if liquidation is None else
              state.sell_net_cents + liquidation.net_cash_change_cents - state.buy_investment_cents)
    return RoundValuation(profit_result(profit, state.buy_investment_cents,
                                       participates=state.buy_investment_cents > 0), dynamic, unit, liquidation)


def aggregate_returns(results: tuple[ProfitResult, ...]) -> ProfitResult:
    if any(r.status == "Delayed" for r in results):
        return ProfitResult("Delayed", None, None, None, "部分范围估值数据未就绪")
    ready = tuple(r for r in results if r.status == "Ready")
    return profit_result(sum(r.profit_cents for r in ready), sum(r.capital_cents for r in ready),
                         participates=bool(ready))


def current_holdings_return(holdings: tuple[tuple[PositionState, Fraction | None, FeeSnapshot], ...]) -> ProfitResult:
    return aggregate_returns(tuple(value_round(state, price, fees).result
                                   for state, price, fees in holdings if state.quantity > 0))


def incremental_round_profit(opening_profit_cents: int | None,
                             ending_profits_cents: tuple[int | None, ...]) -> int | None:
    """Caller includes closed rounds in the window; new/initialized round baseline is zero."""
    if opening_profit_cents is None or any(p is None for p in ending_profits_cents):
        return None
    return sum(ending_profits_cents) - opening_profit_cents
