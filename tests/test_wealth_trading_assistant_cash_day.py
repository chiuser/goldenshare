"""Initialization cash is a dated baseline, never a profit or invented deposit."""
from datetime import date

import pytest

from src.biz.services.wealth.market.trading_assistant.calculation.cash_day import (
    CashDayTotals, add_cash_movement, close_cash_day,
)
from src.biz.services.wealth.market.trading_assistant.calculation.precision import CalculationInvariantError

SATURDAY = date(2026, 9, 12)


def close(totals=CashDayTotals(), *, day=SATURDAY, previous=None, initial=100000):
    return close_cash_day(totals, business_date=day, initialized_on=SATURDAY,
                          initial_cash_cents=initial, previous_cash_cents=previous)


def test_weekend_initialization_then_monday_without_backfilling_cash():
    assert close(day=date(2026, 9, 11)) is None
    saturday = add_cash_movement(CashDayTotals(), kind="CASH_FLOW", direction="OUT", net_cents=-20000)
    assert close(saturday) == 80000
    assert close(day=date(2026, 9, 13), previous=80000) == 80000
    monday = add_cash_movement(CashDayTotals(), kind="TRADE", direction="BUY", net_cents=-60000)
    assert close(monday, day=date(2026, 9, 14), previous=80000) == 20000
    assert saturday.cash_in_cents == 0  # Initial cash was not turned into a deposit.


def test_all_cash_directions_and_negative_sale_net():
    totals = CashDayTotals()
    for kind, direction, cents in (("CASH_FLOW", "IN", 10000), ("TRADE", "SELL", -400),
                                   ("TRADE", "BUY", -1000), ("CASH_FLOW", "OUT", -5000)):
        totals = add_cash_movement(totals, kind=kind, direction=direction, net_cents=cents)
    assert totals == CashDayTotals(10000, 5000, 1000, -400, 4, 2)
    assert close(totals) == 103600


@pytest.mark.parametrize("day,previous,totals", [
    (SATURDAY, 0, CashDayTotals()),
    (date(2026, 9, 14), None, CashDayTotals()),
    (date(2026, 9, 11), 0, CashDayTotals()),
    (date(2026, 9, 11), None, CashDayTotals(cash_in_cents=1)),
    (SATURDAY, None, CashDayTotals(cash_out_cents=100001)),
])
def test_invalid_baseline_and_negative_balance_are_rejected(day, previous, totals):
    with pytest.raises(CalculationInvariantError):
        close(totals, day=day, previous=previous)


@pytest.mark.parametrize("kind,direction,net", [
    ("CASH_FLOW", "IN", 0), ("CASH_FLOW", "OUT", 1), ("TRADE", "BUY", 1),
    ("CASH_FLOW", "SELL", 100), ("TRADE", "SELL", True),
])
def test_invalid_cash_inputs(kind, direction, net):
    with pytest.raises(CalculationInvariantError):
        add_cash_movement(CashDayTotals(), kind=kind, direction=direction, net_cents=net)
