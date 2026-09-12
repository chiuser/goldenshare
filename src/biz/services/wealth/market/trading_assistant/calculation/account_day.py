"""Bounded account-day aggregation, design §4.6.2; no database or input selection.

The caller supplies one complete stock-day at a time in stock-code order. A new
initial holding contributes its entered cost, not an invented cash purchase.
Closed-round profit participates in the daily delta, never in current holdings.
"""
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction

from .daily import PositionState
from .fees import FeeSnapshot
from .periods import DayCash, advance_period, start_period
from .precision import CalculationInvariantError, require_integer
from .returns import ProfitResult, profit_result, value_round


class SnapshotValuationUnavailable(RuntimeError):
    """No complete snapshot may be saved while a required endpoint is missing."""


@dataclass(frozen=True, slots=True)
class StockDayContribution:
    stock: str
    opening: PositionState
    ending: PositionState
    opening_profit_cents: int | None
    buy_input_cents: int
    sell_net_cents: int
    closed_trade_count: int
    closed_profit_cents: int
    price: Fraction | None
    fees: FeeSnapshot

    def __post_init__(self):
        if not isinstance(self.stock, str) or not self.stock or len(self.stock) > 16:
            raise CalculationInvariantError("Invalid stock identity")
        for n in (self.buy_input_cents, self.closed_trade_count):
            require_integer(n, minimum=0)
        for n in (self.sell_net_cents, self.closed_profit_cents):
            require_integer(n)
        if self.opening_profit_cents is not None:
            require_integer(self.opening_profit_cents)
        if (self.ending.buy_investment_cents != self.opening.buy_investment_cents + self.buy_input_cents
                or self.ending.sell_net_cents != self.opening.sell_net_cents + self.sell_net_cents):
            raise CalculationInvariantError("Round cash totals do not reconcile")
        allocated = self.opening.pool_cents + self.buy_input_cents - self.ending.pool_cents
        if allocated < 0 or self.closed_profit_cents != self.sell_net_cents - allocated:
            raise CalculationInvariantError("Closed cost and profit do not reconcile")
        if self.closed_trade_count == 0 and (allocated != 0 or self.sell_net_cents != 0):
            raise CalculationInvariantError("Sell cash or allocated cost has no closed trade")


@dataclass(frozen=True, slots=True)
class AccountDayTotals:
    """Constant-size continuation state; monetary counters are integer cents."""
    after_stock: str | None = None
    opening_cost_cents: int = 0
    buy_input_cents: int = 0
    sell_net_cents: int = 0
    current_buy_input_cents: int = 0
    current_sell_net_cents: int = 0
    market_value_cents: int = 0
    commission_cents: int = 0
    stamp_tax_cents: int = 0
    day_profit_cents: int = 0
    closed_trade_count: int = 0
    closed_profit_cents: int = 0
    valuation_missing: bool = False

    def __post_init__(self):
        for n in (self.opening_cost_cents, self.buy_input_cents, self.current_buy_input_cents,
                  self.market_value_cents, self.commission_cents, self.stamp_tax_cents, self.closed_trade_count):
            require_integer(n, minimum=0)
        for n in (self.sell_net_cents, self.current_sell_net_cents, self.day_profit_cents, self.closed_profit_cents):
            require_integer(n)
        if type(self.valuation_missing) is not bool:
            raise CalculationInvariantError("Missing valuation flag must be boolean")
        if self.after_stock is not None and (not isinstance(self.after_stock, str) or not self.after_stock
                                             or len(self.after_stock) > 16):
            raise CalculationInvariantError("Invalid stock continuation cursor")


def add_stock_day(totals: AccountDayTotals, stock: StockDayContribution) -> AccountDayTotals:
    if totals.after_stock is not None and stock.stock <= totals.after_stock:
        raise CalculationInvariantError("Repeated or out-of-order stock day")
    valuation = value_round(stock.ending, stock.price, stock.fees)
    missing = valuation.result.status == "Delayed" or stock.opening_profit_cents is None
    delta = (0 if missing else (valuation.result.profit_cents or 0) - stock.opening_profit_cents)
    held = stock.ending.quantity > 0
    liquidation = valuation.liquidation
    return replace(totals, after_stock=stock.stock,
        opening_cost_cents=totals.opening_cost_cents + stock.opening.pool_cents,
        buy_input_cents=totals.buy_input_cents + stock.buy_input_cents,
        sell_net_cents=totals.sell_net_cents + stock.sell_net_cents,
        current_buy_input_cents=totals.current_buy_input_cents + (stock.ending.buy_investment_cents if held else 0),
        current_sell_net_cents=totals.current_sell_net_cents + (stock.ending.sell_net_cents if held else 0),
        market_value_cents=totals.market_value_cents + (liquidation.gross_cents if liquidation else 0),
        commission_cents=totals.commission_cents + (liquidation.commission_cents if liquidation else 0),
        stamp_tax_cents=totals.stamp_tax_cents + (liquidation.stamp_tax_cents if liquidation else 0),
        day_profit_cents=totals.day_profit_cents + delta,
        closed_trade_count=totals.closed_trade_count + stock.closed_trade_count,
        closed_profit_cents=totals.closed_profit_cents + stock.closed_profit_cents,
        valuation_missing=totals.valuation_missing or missing)


@dataclass(frozen=True, slots=True)
class AccountDayAmounts:
    totals: AccountDayTotals
    cash_cents: int | None
    total_assets_cents: int | None
    cash_in_cents: int
    cash_out_cents: int
    holding_return: ProfitResult
    day_return: ProfitResult


def finish_account_day(totals: AccountDayTotals, *, account_id: str, business_date: date,
                       opening_cash_cents: int | None, cash_in_cents: int,
                       cash_out_cents: int) -> AccountDayAmounts:
    """Reset daily capital, not round profit. Before initialization cash is unknown.

    On initialization day the caller supplies the entered cash as opening cash;
    it is not a deposit and cannot increase profit or participating principal.
    """
    if not isinstance(account_id, str) or not account_id or type(business_date) is not date:
        raise CalculationInvariantError("Invalid account or business date")
    for n in (cash_in_cents, cash_out_cents):
        require_integer(n, minimum=0)
    if totals.valuation_missing:
        raise SnapshotValuationUnavailable("A stock-day valuation endpoint is unavailable")
    if opening_cash_cents is None:
        if (cash_in_cents or cash_out_cents or totals.buy_input_cents or totals.sell_net_cents
                or totals.closed_trade_count):
            raise CalculationInvariantError("Cannot invent historical cash for recorded transactions")
        cash = assets = None
        principal = totals.opening_cost_cents
    else:
        require_integer(opening_cash_cents, minimum=0)
        cash = opening_cash_cents + cash_in_cents + totals.sell_net_cents - totals.buy_input_cents - cash_out_cents
        capital = advance_period(start_period(account_id, opening_cash_cents, totals.opening_cost_cents),
            DayCash(account_id, business_date, cash_in_cents, cash_out_cents,
                    totals.buy_input_cents, totals.sell_net_cents, cash))
        principal = capital.principal_cents
        assets = cash + totals.market_value_cents
    holding_profit = (totals.current_sell_net_cents + totals.market_value_cents - totals.commission_cents
                      - totals.stamp_tax_cents - totals.current_buy_input_cents)
    return AccountDayAmounts(totals, cash, assets, cash_in_cents, cash_out_cents,
        profit_result(holding_profit, totals.current_buy_input_cents, participates=totals.current_buy_input_cents > 0),
        profit_result(totals.day_profit_cents, principal, participates=principal > 0))
