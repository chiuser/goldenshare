"""One complete stock/day reduction. Calendar and effective facts are supplied."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .allocation import SellQuantity, allocate_sell_costs
from .fees import FeeSnapshot, calculate_trade_fees
from .precision import CalculationInvariantError, format_return_pct, require_integer


@dataclass(frozen=True, slots=True)
class PositionState:
    quantity: int
    available_quantity: int
    pool_cents: int
    buy_investment_cents: int
    sell_net_cents: int

    def __post_init__(self) -> None:
        for value in (self.quantity, self.available_quantity, self.pool_cents, self.buy_investment_cents):
            require_integer(value, minimum=0)
        require_integer(self.sell_net_cents)
        if self.available_quantity > self.quantity or self.pool_cents > self.buy_investment_cents:
            raise CalculationInvariantError("Inconsistent position cost or quantity")
        if (self.quantity == 0 and self.pool_cents != 0) or (self.quantity > 0 and (self.buy_investment_cents <= 0 or self.pool_cents <= 0)):
            raise CalculationInvariantError("Position has invalid cost basis")


def initialize_position(quantity: int, available_quantity: int, cost_price_cents: int) -> PositionState:
    require_integer(quantity, minimum=1)
    require_integer(cost_price_cents, minimum=1)
    return PositionState(quantity, available_quantity, quantity * cost_price_cents,
                         quantity * cost_price_cents, 0)


def next_trading_day_position(state: PositionState) -> PositionState:
    """Caller must prove the date is the next trading day, not the next calendar day."""
    if state.quantity == 0:
        return PositionState(0, 0, 0, 0, 0)
    return PositionState(state.quantity, state.quantity, state.pool_cents,
                         state.buy_investment_cents, state.sell_net_cents)


@dataclass(frozen=True, slots=True)
class Trade:
    source_id: str
    account_id: str
    stock_code: str
    trade_date: date
    direction: Literal["BUY", "SELL"]
    quantity: int
    price_cents: int
    fee_snapshot: FeeSnapshot

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.source_id, self.account_id, self.stock_code)):
            raise CalculationInvariantError("Missing trade identity")
        if type(self.trade_date) is not date or self.direction not in ("BUY", "SELL"):
            raise CalculationInvariantError("Invalid trade date or direction")
        require_integer(self.quantity, minimum=1)
        require_integer(self.price_cents, minimum=1)


@dataclass(frozen=True, slots=True)
class ClosedSale:
    source_id: str
    quantity: int
    allocated_cost_cents: int
    cost_adjustment_cents: int
    net_proceeds_cents: int
    profit_cents: int
    return_pct: str


@dataclass(frozen=True, slots=True)
class StockDayResult:
    closing: PositionState
    closed_sales: tuple[ClosedSale, ...]
    buy_investment_cents: int
    sell_net_cents: int
    cash_change_cents: int
    commission_cents: int
    stamp_tax_cents: int
    round_ended: bool


def calculate_stock_day(account_id: str, stock_code: str, trade_date: date,
                        opening: PositionState, trades: tuple[Trade, ...]) -> StockDayResult:
    if type(trade_date) is not date:
        raise CalculationInvariantError("Expected business date")
    if any((t.account_id, t.stock_code, t.trade_date) != (account_id, stock_code, trade_date) for t in trades):
        raise CalculationInvariantError("Mixed account, stock or day")
    if len({t.source_id for t in trades}) != len(trades):
        raise CalculationInvariantError("Duplicate effective trade identity")
    if opening.quantity == 0 and (opening.buy_investment_cents or opening.sell_net_cents):
        raise CalculationInvariantError("Closed round must be reset before a new day")
    sells = tuple(t for t in trades if t.direction == "SELL")
    if sum(t.quantity for t in sells) > opening.available_quantity:
        raise CalculationInvariantError("Sell exceeds opening available quantity (T+1)")
    allocation = allocate_sell_costs(opening.pool_cents, opening.quantity,
                                     tuple(SellQuantity(t.source_id, t.quantity) for t in sells))
    amounts = {t.source_id: calculate_trade_fees(t.quantity * t.price_cents, t.fee_snapshot, t.direction)
               for t in trades}
    costs = {item.source_id: item for item in allocation.items}
    closed = tuple(ClosedSale(t.source_id, t.quantity, costs[t.source_id].cost_cents,
                              costs[t.source_id].adjustment_cents,
                              amounts[t.source_id].net_cash_change_cents,
                              amounts[t.source_id].net_cash_change_cents - costs[t.source_id].cost_cents,
                              format_return_pct(amounts[t.source_id].net_cash_change_cents - costs[t.source_id].cost_cents,
                                                costs[t.source_id].cost_cents))
                   for t in sorted(sells, key=lambda t: t.source_id))
    buys = tuple(t for t in trades if t.direction == "BUY")
    investment = -sum(amounts[t.source_id].net_cash_change_cents for t in buys)
    proceeds = sum(amounts[t.source_id].net_cash_change_cents for t in sells)
    sold_quantity = sum(t.quantity for t in sells)
    closing = PositionState(allocation.remaining_quantity + sum(t.quantity for t in buys),
                            opening.available_quantity - sold_quantity,
                            allocation.remaining_cost_cents + investment,
                            opening.buy_investment_cents + investment, opening.sell_net_cents + proceeds)
    return StockDayResult(closing, closed, investment, proceeds, proceeds - investment,
                          sum(a.commission_cents for a in amounts.values()),
                          sum(a.stamp_tax_cents for a in amounts.values()),
                          closing.quantity == 0 and bool(opening.quantity or trades))
