"""Incremental pre-acceptance cash/quantity checks, not returns calculation.

The reader selects a fixed effective version and supplies complete day boundaries.
These immutable accumulators may be checkpointed between pages, including mid-day.
"""
from dataclasses import dataclass, replace
from datetime import date


@dataclass(frozen=True, slots=True)
class InvalidLedger(ValueError):
    field: str
    occurred_on: date
    message: str
    ts_code: str | None = None


@dataclass(frozen=True, slots=True)
class CashValidation:
    cash_cents: int
    current_day: date | None = None
    day_delta_cents: int = 0
    checked_rows: int = 0

    def __post_init__(self):
        if (type(self.cash_cents) is not int or self.cash_cents < 0
                or type(self.day_delta_cents) is not int
                or type(self.checked_rows) is not int or self.checked_rows < 0):
            raise ValueError("Invalid exact cash validation state")


def finish_cash_day(state: CashValidation) -> CashValidation:
    if state.current_day is None:
        return state
    result = state.cash_cents + state.day_delta_cents
    if result < 0:
        raise InvalidLedger("amount", state.current_day, "该日期的现金余额不足，请检查相关记录")
    return replace(state, cash_cents=result, day_delta_cents=0)


def advance_cash(state: CashValidation, occurred_on: date, delta_cents: int) -> CashValidation:
    if type(delta_cents) is not int or type(occurred_on) is not date:
        raise ValueError("Expected exact cash cents and a business date")
    if state.current_day is not None and occurred_on < state.current_day:
        raise ValueError("Facts must be ordered")
    if state.current_day is not None and occurred_on > state.current_day:
        state = finish_cash_day(state)
    return replace(state, current_day=occurred_on, day_delta_cents=state.day_delta_cents + delta_cents,
                   checked_rows=state.checked_rows + 1)


@dataclass(frozen=True, slots=True)
class QuantityValidation:
    initialized_on: date
    quantity: int
    initial_available: int
    current_day: date | None = None
    bought: int = 0
    sold: int = 0
    checked_rows: int = 0

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in (
            self.quantity, self.initial_available, self.bought, self.sold, self.checked_rows)):
            raise ValueError("Invalid quantity state")
        if self.current_day is None and self.initial_available > self.quantity:
            raise ValueError("Initial available exceeds holdings")


def finish_quantity_day(state: QuantityValidation) -> QuantityValidation:
    if state.current_day is None:
        return state
    available = state.initial_available if state.current_day == state.initialized_on else state.quantity
    if state.sold > available:
        raise InvalidLedger("quantity", state.current_day, "卖出数量超过当日可卖数量，请检查")
    return replace(state, quantity=state.quantity + state.bought - state.sold, bought=0, sold=0)


def advance_quantity(state: QuantityValidation, occurred_on: date, direction: str,
                     quantity: int, *, is_open: bool) -> QuantityValidation:
    if type(is_open) is not bool or type(quantity) is not int or quantity <= 0 or direction not in ("BUY", "SELL"):
        raise ValueError("Invalid validated trade fact")
    if occurred_on < state.initialized_on:
        raise InvalidLedger("tradeDate", occurred_on, "交易日期不能早于账户初始化日期")
    if not is_open:
        raise InvalidLedger("tradeDate", occurred_on, "请选择交易日")
    if state.current_day is not None and occurred_on < state.current_day:
        raise ValueError("Facts must be ordered")
    if state.current_day is not None and occurred_on > state.current_day:
        state = finish_quantity_day(state)
    return replace(state, current_day=occurred_on,
                   bought=state.bought + (quantity if direction == "BUY" else 0),
                   sold=state.sold + (quantity if direction == "SELL" else 0),
                   checked_rows=state.checked_rows + 1)
