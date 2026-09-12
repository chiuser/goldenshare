"""M1 pure-memory acceptance: PRD §17 A–M; design CENT/EXACT/FEE/§6."""

from dataclasses import FrozenInstanceError
from datetime import date
from fractions import Fraction
from itertools import permutations
import random

import pytest

from src.biz.services.wealth.market.trading_assistant.calculation.allocation import SellQuantity, allocate_sell_costs
from src.biz.services.wealth.market.trading_assistant.calculation.daily import (
    PositionState, Trade, calculate_stock_day, initialize_position, next_trading_day_position,
)
from src.biz.services.wealth.market.trading_assistant.calculation.fees import (
    FeeSnapshot, calculate_trade_fees, estimate_liquidation,
)
from src.biz.services.wealth.market.trading_assistant.calculation.periods import (
    DayCash, advance_period, advance_return_period, calendar_window, finish_return_period,
    start_period, start_return_period, stock_period_return, whole_period_return,
)
from src.biz.services.wealth.market.trading_assistant.calculation.precision import (
    CalculationInvariantError, compare_return, format_cents, format_return_pct,
    parse_money_cents, round_ratio_half_up,
)
from src.biz.services.wealth.market.trading_assistant.calculation.returns import (
    aggregate_returns, current_holdings_return, incremental_round_profit, profit_result, value_round,
)

ZERO = FeeSnapshot(0, 0, 0)
FEES = FeeSnapshot.from_inputs("3", "5", "0.05")
DATES = tuple(date(2026, 9, day) for day in (14, 15, 16, 17, 18, 21))


def money(value):
    return parse_money_cents(str(value))


def trade(identity, direction, quantity, price, *, day=DATES[0], fees=ZERO, stock="A", account="acct"):
    return Trade(identity, account, stock, day, direction, quantity, money(price), fees)


def run_window(*, initial_cash=0, initial=None, opening_prices=None, ending_prices=None, days=(), fees=ZERO):
    """A caller adapter over supplied complete effective facts, not a persistence service."""
    positions = dict(initial or {})
    cash = money(initial_cash)
    principal = start_period("acct", cash, sum(s.pool_cents for s in positions.values()))
    opening_costs = {code: s.pool_cents for code, s in positions.items()}
    opening_profit = {code: value_round(s, Fraction(str((opening_prices or {})[code])), fees).result.profit_cents
                      for code, s in positions.items()}
    buy_costs, completed, closed = {}, {}, []
    for index, actions in enumerate(days):
        day = DATES[index]
        positions = {code: next_trading_day_position(s) for code, s in positions.items()}
        transactions, incoming, outgoing = {}, 0, 0
        for ordinal, action in enumerate(actions):
            kind, code, quantity, price = action
            if kind == "IN":
                incoming += money(price)
            elif kind == "OUT":
                outgoing += money(price)
            else:
                transactions.setdefault(code, []).append(trade(f"{index}-{ordinal}", kind, quantity, price,
                                                               day=day, fees=fees, stock=code))
        buys, sales = 0, 0
        for code, records in transactions.items():
            result = calculate_stock_day("acct", code, day, positions.get(code, PositionState(0, 0, 0, 0, 0)), tuple(records))
            positions[code] = result.closing
            closed.extend(result.closed_sales)
            buys += result.buy_investment_cents
            sales += result.sell_net_cents
            buy_costs[code] = buy_costs.get(code, 0) + result.buy_investment_cents
            if result.round_ended:
                completed[code] = completed.get(code, 0) + value_round(result.closing, None, fees).result.profit_cents
        cash += incoming + sales - buys - outgoing
        principal = advance_period(principal, DayCash("acct", day, incoming, outgoing, buys, sales, cash))
    profits = {}
    for code in set(positions) | set(completed):
        state = positions[code]
        # Closed rounds were already collected exactly once above.
        ending = value_round(state, Fraction(str((ending_prices or {})[code])) if state.quantity else None, fees).result
        profits[code] = incremental_round_profit(opening_profit.get(code, 0),
                       (completed.get(code, 0), ending.profit_cents if state.quantity else 0))
    whole = whole_period_return(principal, sum(profits.values()), participates=bool(opening_costs or buy_costs))
    single = {code: stock_period_return(opening_costs.get(code, 0), buy_costs.get(code, 0), profit,
                                       participates=True) for code, profit in profits.items()}
    return whole, single, tuple(closed), positions, cash


# Every vector asserts numerator, denominator and displayed percentage, not merely capital.
CASES = [
    ("A", dict(initial={"A": initialize_position(1000, 1000, 1000)}, opening_prices={"A": 12}, ending_prices={"A": 13}), (1000, 10000, "10.00")),
    ("B", dict(initial_cash=10000, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),), (('BUY','A',1000,11),), (('SELL','A',1000,12),))), (2000, 10000, "20.00")),
    ("C", dict(initial_cash=12000, days=((('BUY','A',1000,12),),), ending_prices={"A": 13}), (1000, 12000, "8.33")),
    ("D", dict(initial={"A": initialize_position(1000,1000,1000)}, opening_prices={"A":12}, ending_prices={"A":13}), (1000,10000,"10.00")),
    ("E", dict(initial={"A": initialize_position(1000,1000,1000)}, opening_prices={"A":12}, days=((('SELL','A',1000,13),),)), (1000,10000,"10.00")),
    ("F", dict(initial={"A": initialize_position(1000,1000,1000)}, opening_prices={"A":12}, ending_prices={"A":13}, days=((('SELL','A',400,13),),)), (1000,10000,"10.00")),
    ("G", dict(initial_cash=10000, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),), (), ())), (1000,10000,"10.00")),
    ("H", dict(initial_cash=10000, days=((('BUY','A',1000,10),), (('SELL','A',1000,12),), (('BUY','B',1000,12),)), ending_prices={"B":13}), (3000,10000,"30.00")),
    ("I", dict(initial_cash=10005, fees=FEES, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),))), (984.50,10005,"9.84")),
    ("J", dict(initial_cash=20000, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),), (('OUT','',0,10000),), (('BUY','B',1000,11),), (('SELL','B',1000,12),))), (2000,10000,"20.00")),
    ("K", dict(initial_cash=20000, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),), (('BUY','B',1000,11),), (('BUY','A',1000,10),)), ending_prices={"A":11,"B":11}), (2000,20000,"10.00")),
    ("L", dict(initial_cash=10000, days=((('BUY','A',1000,10),), (('SELL','A',1000,11),), (('BUY','A',1000,11),), (('SELL','A',1000,12),))), (2000,10000,"20.00")),
    ("M", dict(initial_cash=10000, fees=FeeSnapshot.from_inputs("0","4","0.05"), days=((('BUY','A',300,'33.32'),), (('SELL','A',100,34),('SELL','A',100,34),('SELL','A',100,34)))), ('182.90',10000,"1.83")),
]


@pytest.mark.parametrize("case,inputs,expected", CASES, ids=[c[0] for c in CASES])
def test_prd_a_to_m(case, inputs, expected):
    whole, single, closed, positions, cash = run_window(**inputs)
    assert (whole.profit_cents, whole.capital_cents, whole.return_pct) == (money(expected[0]), money(expected[1]), expected[2])
    assert whole.status == "Ready"
    if case == "L":
        assert (single["A"].profit_cents, single["A"].capital_cents, single["A"].return_pct) == (200000, 2100000, "9.52")
    if case == "K":
        assert (single["A"].profit_cents, single["A"].capital_cents, single["A"].return_pct) == (200000,2000000,"10.00")
    if case == "M":
        assert sorted(c.allocated_cost_cents for c in closed) == [333333,333333,333334]
        assert sum(c.profit_cents for c in closed) == 18290
        assert positions["A"].pool_cents == 0 and cash == 1018290


def test_precision_and_fixed_fee_versions():
    assert round_ratio_half_up(1005,10) == 101
    assert round_ratio_half_up(-1005,10) == -101
    assert format_cents(round_ratio_half_up(-1,3)) == "0.00"
    assert format_return_pct(1000,10000) == "10.00"
    assert compare_return(1,3,2,6) == 0
    assert compare_return(100001,1000000,100002,1000000) == -1
    huge = 10 ** 70 + 1
    assert round_ratio_half_up(huge * 7,7) == huge
    old, new = FEES, FeeSnapshot.from_inputs("5","5","0.06")
    assert calculate_trade_fees(2000000,old,"SELL").commission_cents == 600
    assert calculate_trade_fees(2000000,new,"SELL").stamp_tax_cents == 1200
    assert calculate_trade_fees(2400000,old,"SELL").commission_cents == 720
    assert calculate_trade_fees(2000000,new,"BUY").stamp_tax_cents == 0
    small = calculate_trade_fees(10000,old,"BUY")
    assert small.commission_cents * 2 == 1000
    assert calculate_trade_fees(20000,old,"BUY").commission_cents == 500


@pytest.mark.parametrize("value", [1.2, True, "1.001", "1e2", "NaN", "Infinity", "1,000", "1000000000000000000"])
def test_invalid_money(value):
    with pytest.raises(CalculationInvariantError):
        parse_money_cents(value)


@pytest.mark.parametrize("denominator", [0,-1,True,1.0])
def test_invalid_denominator(denominator):
    with pytest.raises(CalculationInvariantError):
        format_return_pct(100,denominator)


def test_cent_permutation_and_random_conservation():
    sells = (SellQuantity("a",100),SellQuantity("b",100),SellQuantity("c",100))
    expected = allocate_sell_costs(1000000,300,sells)
    assert [a.cost_cents for a in expected.items] == [333334,333333,333333]
    for perm in permutations(sells):
        assert allocate_sell_costs(1000000,300,perm) == expected
    rng = random.Random(20260910)
    for _ in range(3000):
        q = rng.randint(3,10000)
        pool = rng.randint(q,10**25)
        sizes = [1,1,rng.randint(1,q-2)]
        items = tuple(SellQuantity(str(i),n) for i,n in enumerate(sizes))
        result = allocate_sell_costs(pool,q,items)
        assert sum(x.cost_cents for x in result.items) + result.remaining_cost_cents == pool
        assert result.allocated_cents == round_ratio_half_up(pool*sum(sizes),q)
        for output,input_item in zip(result.items,items):
            assert abs(Fraction(pool*input_item.quantity,q)-output.cost_cents) < 1
            assert abs(output.adjustment_cents) <= 1
        assert allocate_sell_costs(pool,q,tuple(reversed(items))) == result


def test_cost_pool_dynamic_cost_and_t_plus_one():
    opening = initialize_position(1000,600,1000)
    result = calculate_stock_day("acct","A",DATES[0],opening,(trade("s","SELL",400,15),))
    valuation = value_round(result.closing,Fraction(10),ZERO)
    assert result.closing.pool_cents == 600000
    assert valuation.dynamic_cost_cents == 400000 and valuation.dynamic_cost_price == "6.67"
    assert valuation.result.return_pct == "20.00"
    assert result.closed_sales[0].profit_cents == 200000
    with pytest.raises(CalculationInvariantError):
        calculate_stock_day("acct","A",DATES[0],opening,(trade("b","BUY",400,10),trade("s","SELL",800,10)))
    inputs = (trade("s","SELL",1000,15),trade("b","BUY",1000,20))
    opening = initialize_position(1000,1000,1000)
    a = calculate_stock_day("acct","A",DATES[0],opening,inputs)
    b = calculate_stock_day("acct","A",DATES[0],opening,tuple(reversed(inputs)))
    assert a == b and not a.round_ended
    assert value_round(a.closing,Fraction(20),ZERO).dynamic_cost_price == "15.00"
    assert a.closing.pool_cents == 2000000
    with pytest.raises(FrozenInstanceError):
        opening.quantity = 1


@pytest.mark.parametrize("sell_price,expected_cost,expected_rate", [(20,0,"100.00"),(30,-500000,"200.00")])
def test_zero_negative_dynamic_cost(sell_price,expected_cost,expected_rate):
    result = calculate_stock_day("acct","A",DATES[0],initialize_position(1000,1000,1000),
                                 (trade("s","SELL",500,sell_price),))
    valuation = value_round(result.closing,Fraction(sell_price),ZERO)
    assert valuation.dynamic_cost_cents == expected_cost
    assert valuation.result.return_pct == expected_rate


def test_missing_empty_zero_and_cross_account_fees():
    state = initialize_position(1000,1000,1000)
    assert value_round(state,None,ZERO).result.status == "Delayed"
    assert value_round(state,Fraction(10),ZERO).result.return_pct == "0.00"
    closed = calculate_stock_day("acct","A",DATES[0],state,(trade("s","SELL",1000,11),)).closing
    assert current_holdings_return(((closed,None,ZERO),)).status == "Empty"
    assert value_round(closed,None,FEES).liquidation.commission_cents == 0
    assert current_holdings_return(((state,Fraction(11),ZERO),(state,None,ZERO))).status == "Delayed"
    first = value_round(state,Fraction(11),ZERO).result
    second = value_round(initialize_position(1000,1000,2000),Fraction(24),ZERO).result
    assert aggregate_returns((first,second)).return_pct == "16.67"
    assert estimate_liquidation(1,Fraction("1.0049"),ZERO).gross_cents == 100
    assert estimate_liquidation(100,Fraction("1.0049"),ZERO).gross_cents == 10049
    assert sum(estimate_liquidation(1,Fraction(10),FEES).commission_cents for _ in range(2)) == 1000


def test_period_extra_cash_cases_and_replay_rejection():
    state = start_period("acct",2000000,0)
    state = advance_period(state,DayCash("acct",DATES[0],0,0,1000000,0,1000000))
    state = advance_period(state,DayCash("acct",DATES[1],0,0,0,1100000,2100000))
    state = advance_period(state,DayCash("acct",DATES[2],0,2100000,0,0,0))
    state = advance_period(state,DayCash("acct",DATES[3],2000000,0,2000000,0,0))
    assert state.principal_cents == 3000000
    with pytest.raises(CalculationInvariantError):
        advance_period(state,DayCash("acct",DATES[3],0,0,0,0,0))
    with pytest.raises(CalculationInvariantError):
        advance_period(state,DayCash("other",DATES[4],0,0,0,0,0))
    state = advance_period(start_period("acct",10000,10000),DayCash("acct",DATES[0],0,0,0,-500,9500))
    assert state.principal_cents == 10000 and state.idle_cash_cents == 9500


def test_calendar_boundaries_and_revised_effective_facts():
    assert calendar_window(date(2026,1,1),"WEEK") == (date(2025,12,29),date(2026,1,4))
    assert calendar_window(date(2024,2,20),"MONTH") == (date(2024,2,1),date(2024,2,29))
    initial = initialize_position(1000,1000,1000)
    original = calculate_stock_day("acct","A",DATES[0],initial,(trade("same","SELL",400,11,fees=FEES),))
    corrected = calculate_stock_day("acct","A",DATES[0],initial,(trade("same","SELL",400,12,fees=FEES),))
    assert len(corrected.closed_sales) == 1
    assert corrected.closed_sales[0].profit_cents != original.closed_sales[0].profit_cents
    assert calculate_stock_day("acct","A",DATES[0],initial,()).closing == initial


def test_arithmetic_does_not_depend_on_decimal_precision_or_accept_floats():
    from decimal import localcontext
    amount = parse_money_cents("999999999999999999.99") * 9007199254740991
    with localcontext() as context:
        context.prec = 2
        result = calculate_trade_fees(amount, FEES, "SELL")
        assert result.commission_cents == round_ratio_half_up(amount * 300, 1000000)
        assert result.stamp_tax_cents == round_ratio_half_up(amount * 5, 10000)
        assert result.net_cash_change_cents + result.commission_cents + result.stamp_tax_cents == amount
        assert format_return_pct(amount, amount) == "100.00"
    for profit, capital, participates in ((0.0,100,True),(0,100.0,True),(0,True,True),(0,100,"false")):
        with pytest.raises(CalculationInvariantError):
            profit_result(profit,capital,participates=participates)
    with pytest.raises(CalculationInvariantError):
        PositionState(1,1,0,100,0)


def test_complete_day_permutations_and_nonmutating_values():
    initial = initialize_position(1000,600,1000)
    transactions = (trade("a","SELL",200,11),trade("b","BUY",100,12),trade("c","SELL",400,13))
    expected = calculate_stock_day("acct","A",DATES[0],initial,transactions)
    for order in permutations(transactions):
        assert calculate_stock_day("acct","A",DATES[0],initial,order) == expected
    assert initial == initialize_position(1000,600,1000)
    assert expected.closing.quantity == 500 and expected.closing.available_quantity == 0
    assert initial.pool_cents + expected.buy_investment_cents == expected.closing.pool_cents + sum(item.allocated_cost_cents for item in expected.closed_sales)
    assert expected.cash_change_cents == expected.sell_net_cents - expected.buy_investment_cents
    with pytest.raises(FrozenInstanceError):
        initial.quantity = 1


def test_loss_requires_new_principal_and_partial_proceeds_are_reused():
    state = advance_period(start_period("acct",200000,0),DayCash("acct",DATES[0],0,0,100000,0,100000))
    state = advance_period(state,DayCash("acct",DATES[1],0,0,0,80000,180000))
    state = advance_period(state,DayCash("acct",DATES[2],0,0,100000,0,80000))
    assert state.principal_cents == 120000  # 800 reused, 200 newly participates.
    assert whole_period_return(state,0,participates=True).return_pct == "0.00"
    state2 = advance_period(start_period("other",100000,0),DayCash("other",DATES[0],0,0,100000,0,0))
    assert state2.principal_cents == 100000
    assert aggregate_returns((whole_period_return(state,12000,participates=True),
                              whole_period_return(state2,10000,participates=True))).return_pct == "10.00"


def test_calculation_to_strict_closed_trade_contract():
    from src.biz.schemas.wealth.market.trading_assistant.records import ClosedTrade
    identity = "00000000-0000-0000-0000-000000000001"
    fees = FeeSnapshot.from_inputs("0","4","0.05")
    initial = PositionState(300,300,1000000,1000000,0)  # 9996 + original buy fee 4.
    transactions = tuple(trade(f"s{i}","SELL",100,34,fees=fees) for i in range(3))
    result = calculate_stock_day("acct","A",DATES[0],initial,transactions)
    rows = []
    for index, closed in enumerate(result.closed_sales, start=1):
        fee = calculate_trade_fees(340000,fees,"SELL")
        rows.append(ClosedTrade(accountRef=dict(accountId=identity,name="账户",brokerName="券商"),
            stockRef=dict(tsCode="600000.SH",name="股票"),tradeId=f"00000000-0000-0000-0000-{index:012d}",sellRevision="1",tradeDate=DATES[0].isoformat(),
            recordedAt="2026-09-14T16:00:00+08:00",roundRef=dict(accountId=identity,roundId=identity,roundNumber=1,status="CLOSED"),
            quantity=100,price="34.00",grossAmount=format_cents(fee.gross_cents),commissionAmount=format_cents(fee.commission_cents),
            stampTaxAmount=format_cents(fee.stamp_tax_cents),totalFeeAmount=format_cents(fee.commission_cents+fee.stamp_tax_cents),
            netProceeds=format_cents(closed.net_proceeds_cents),dayOpeningUnitCost="33.33",allocatedCost=format_cents(closed.allocated_cost_cents),
            dayEndQuantity="0",dayGroup=dict(accountId=identity,tsCode="600000.SH",tradeDate=DATES[0].isoformat()),
            calculationRuleVersion="1",dayResultId=identity,profitAmount=format_cents(closed.profit_cents),returnPct=closed.return_pct))
    assert sum(parse_money_cents(row.allocatedCost) for row in rows) == 1000000
    assert sum(parse_money_cents(row.profitAmount) for row in rows) == 18290


def test_daily_continuation_matches_period_endpoints_without_summing_daily_capital():
    state = start_return_period("acct",1000000,0)
    for index, (buy,sell,cash,profit,capital) in enumerate((
        (1000000,0,0,0,1000000), (0,1100000,1100000,100000,1000000),
        (1100000,0,0,0,1100000), (0,1200000,1200000,100000,1100000),
    )):
        state = advance_return_period(state,DayCash("acct",DATES[index],0,0,buy,sell,cash),
                                      profit_result(profit,capital,participates=True))
    result = finish_return_period(state)
    assert (result.profit_cents,result.capital_cents,result.return_pct) == (200000,1000000,"20.00")
    assert result == run_window(**CASES[11][1])[0]
    # Cash-only later days don't erase the period's realized profit.
    state = advance_return_period(state,DayCash("acct",DATES[4],0,0,0,0,1200000),profit_result(None,0,participates=False))
    assert finish_return_period(state) == result
    # A required missing valuation is not turned into a zero increment.
    unknown = advance_return_period(start_return_period("acct",0,1000000),
                                    DayCash("acct",DATES[0],0,0,0,0,0),profit_result(None,1000000,participates=True))
    assert finish_return_period(unknown).status == "Delayed"
