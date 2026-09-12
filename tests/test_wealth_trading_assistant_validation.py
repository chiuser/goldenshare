from datetime import date
from itertools import permutations

import pytest

from src.biz.services.wealth.market.trading_assistant.validation import (
    CashValidation, QuantityValidation, InvalidLedger, advance_cash, finish_cash_day,
    advance_quantity, finish_quantity_day)

D = date(2026, 9, 11)
NEXT = date(2026, 9, 14)


def test_day_cash_is_not_checked_at_arbitrary_page_boundary():
    for amounts in permutations((-20000, 15000, 10000)):
        state = CashValidation(0)
        for amount in amounts:
            state = advance_cash(state, D, amount)
        assert finish_cash_day(state).cash_cents == 5000


def test_negative_prior_day_rejected_before_later_inflow():
    state = advance_cash(CashValidation(0), D, -100)
    with pytest.raises(InvalidLedger) as exc:
        advance_cash(state, NEXT, 10000)
    assert exc.value.occurred_on == D


def test_same_day_buy_does_not_make_sell_available():
    for directions in permutations(("BUY", "SELL")):
        state = QuantityValidation(D, 0, 0)
        for direction in directions:
            state = advance_quantity(state, D, direction, 100, is_open=True)
        with pytest.raises(InvalidLedger):
            finish_quantity_day(state)


def test_initial_available_and_next_trade_day():
    state = advance_quantity(QuantityValidation(D, 1000, 600), D, "SELL", 600, is_open=True)
    state = advance_quantity(state, NEXT, "SELL", 400, is_open=True)
    assert finish_quantity_day(state).quantity == 0
    state = advance_quantity(QuantityValidation(D, 1000, 600), D, "SELL", 601, is_open=True)
    with pytest.raises(InvalidLedger):
        finish_quantity_day(state)


def test_closed_calendar_day_cannot_pass_as_t_plus_one():
    with pytest.raises(InvalidLedger):
        advance_quantity(QuantityValidation(D, 1000, 0), date(2026, 9, 12), "SELL", 1000, is_open=False)


def test_initialization_day_cannot_be_moved_backwards():
    with pytest.raises(InvalidLedger):
        advance_quantity(QuantityValidation(D, 1000, 1000), date(2026, 9, 10), "SELL", 1, is_open=True)
