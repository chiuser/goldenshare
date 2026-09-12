"""Account snapshot arithmetic: current rounds, daily deltas and cash isolation."""
from dataclasses import replace
from datetime import date
from decimal import localcontext
from fractions import Fraction

import pytest

from src.biz.services.wealth.market.trading_assistant.calculation.account_day import (
    AccountDayTotals, StockDayContribution, SnapshotValuationUnavailable,
    add_stock_day, finish_account_day,
)
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.calculation.fees import FeeSnapshot
from src.biz.services.wealth.market.trading_assistant.calculation.precision import CalculationInvariantError

ZERO = FeeSnapshot(0, 0, 0)
DAY = date(2026, 9, 10)


def finish(totals, cash=0, cash_in=0, cash_out=0):
    return finish_account_day(totals, account_id="account", business_date=DAY,
        opening_cash_cents=cash, cash_in_cents=cash_in, cash_out_cents=cash_out)


def held(*, stock="000001.SZ", opening_profit=0, price=Fraction(11), fees=ZERO):
    state = PositionState(1000, 1000, 1000000, 1000000, 0)
    return StockDayContribution(stock, state, state, opening_profit, 0, 0, 0, 0, price, fees)


def test_historical_initialization_unknown_cash_then_daily_delta():
    first = finish(add_stock_day(AccountDayTotals(), held()), cash=None)
    assert first.cash_cents is first.total_assets_cents is None
    assert (first.day_return.profit_cents, first.day_return.capital_cents, first.day_return.return_pct) == (
        100000, 1000000, "10.00")
    # Submitted today at 12; yesterday's cumulative gain was 1000, not zero.
    today = finish(add_stock_day(AccountDayTotals(), held(opening_profit=100000, price=Fraction(12))), cash=500000)
    assert today.cash_cents == 500000 and today.total_assets_cents == 1700000
    assert today.holding_return.profit_cents == 200000
    assert today.day_return.profit_cents == 100000
    assert today.day_return.return_pct == "10.00"


def test_clear_today_still_has_daily_return_without_double_closed_profit():
    start = held().opening
    end = PositionState(0, 0, 0, 1000000, 1200000)
    stock = StockDayContribution("000001.SZ", start, end, 100000, 0, 1200000,
                                 1, 200000, None, FeeSnapshot(300, 500, 5))
    result = finish(add_stock_day(AccountDayTotals(), stock))
    assert result.holding_return.status == "Empty"
    assert result.day_return.profit_cents == 100000
    assert result.day_return.return_pct == "10.00"
    assert result.totals.closed_profit_cents == 200000
    assert result.cash_cents == result.total_assets_cents == 1200000
    assert result.totals.commission_cents == result.totals.stamp_tax_cents == 0


def test_sell_and_buyback_keep_round_reuse_and_negative_dynamic_cost():
    start = held().opening
    end = PositionState(500, 0, 500000, 1500000, 2000000)
    stock = StockDayContribution("000001.SZ", start, end, 0, 500000, 2000000,
                                 1, 1000000, Fraction(10), ZERO)
    result = finish(add_stock_day(AccountDayTotals(), stock))
    assert result.totals.current_buy_input_cents - result.totals.current_sell_net_cents == -500000
    assert result.day_return.profit_cents == 1000000
    assert result.day_return.capital_cents == 1000000  # Not 1500000: reused sale proceeds.
    assert result.holding_return.capital_cents == 1500000
    assert result.holding_return.return_pct == "66.67"


def test_real_zero_pure_cash_and_missing_are_distinct():
    zero = finish(add_stock_day(AccountDayTotals(), held(price=Fraction(10))))
    assert zero.day_return.status == "Ready" and zero.day_return.return_pct == "0.00"
    cash = finish(AccountDayTotals(), cash=1000000, cash_in=500000, cash_out=200000)
    assert cash.day_return.status == cash.holding_return.status == "Empty"
    assert cash.cash_cents == 1300000
    for stock in (held(price=None), held(opening_profit=None)):
        with pytest.raises(SnapshotValuationUnavailable):
            finish(add_stock_day(AccountDayTotals(), stock))


def test_stock_pages_exact_fees_and_order_guard():
    totals = AccountDayTotals()
    fees = FeeSnapshot(300, 500, 5)
    for stock in ("000001.SZ", "000002.SZ"):
        totals = add_stock_day(totals, held(stock=stock, price=Fraction("10.1234"), fees=fees))
    result = finish(totals)
    assert totals.market_value_cents == 2024680  # Source price must not first round to 10.12.
    assert totals.commission_cents == 1000     # Minimum separately per stock.
    assert totals.stamp_tax_cents == 1012
    assert result.day_return.profit_cents == 22668
    with pytest.raises(CalculationInvariantError, match="Repeated"):
        add_stock_day(totals, held(stock="000002.SZ"))


def test_account_cash_isolation_and_no_synthetic_historical_purchases():
    zero = PositionState(0, 0, 0, 0, 0)
    state = held().ending
    bought = StockDayContribution("000001.SZ", zero, state, 0, 1000000, 0, 0, 0, Fraction(11), ZERO)
    totals = add_stock_day(AccountDayTotals(), bought)
    with pytest.raises(CalculationInvariantError):
        finish(totals, cash=999999)
    with pytest.raises(CalculationInvariantError, match="historical cash"):
        finish(totals, cash=None)
    assert finish(totals, cash=1000000).day_return.return_pct == "10.00"
    with pytest.raises(CalculationInvariantError, match="historical cash"):
        finish(AccountDayTotals(), cash=None, cash_in=1)


def test_large_values_independent_of_decimal_precision():
    size = 10 ** 70
    state = PositionState(size, size, size * 1000, size * 1000, 0)
    stock = StockDayContribution("000001.SZ", state, state, 0, 0, 0, 0, 0, Fraction(11), ZERO)
    with localcontext() as ctx:
        ctx.prec = 2
        result = finish(add_stock_day(AccountDayTotals(), stock))
    assert result.day_return.profit_cents == size * 100
    assert result.day_return.return_pct == "10.00"


def test_reject_inconsistent_closed_profit_or_round_cash():
    with pytest.raises(CalculationInvariantError, match="Closed cost"):
        replace(held(), closed_profit_cents=1)
    with pytest.raises(CalculationInvariantError, match="Round cash"):
        replace(held(), buy_input_cents=1)
