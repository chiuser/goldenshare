"""Literal plan examples and adversarial cases; no real Lake, APIs or installs."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import json
import random
import sys

import pytest

from scripts.research.index_market.chan.stock_share_account import Account
from scripts.research.index_market.chan.stock_share_audit import audit, metrics
from scripts.research.index_market.chan.stock_share_model import (
    CorporateEffect, DataBlocked, Signal, StockShareBacktestSpec, affordable, fees, model_price,
)
from scripts.research.index_market.chan import stock_share_synthetic as synthetic


SPEC, EXAMPLE_BARS, _ = synthetic.golden_inputs()
RULE = EXAMPLE_BARS[0].rule


def bar(day, price=10, **changes):
    start = datetime(2026, 1, 1, 9, 30)+timedelta(days=day)
    return replace(EXAMPLE_BARS[0], start=start, end=start+timedelta(minutes=30),
                   open=D(price), close=D(price), **changes)


def signals(b, *groups):
    return [Signal(f'{b.end.isoformat()}|{g}', b.code, b.frequency, b.end, g) for g in groups]


def account(cash=100000, **changes):
    return Account('000001.SZ', spec=replace(SPEC, initial_cash=D(cash), **changes))


def step(a, day, *groups, price=10, **changes):
    b = bar(day, price, **changes)
    a.step(b, signals(b, *groups))
    audit(a.result())
    return b


def test_literal_six_fills_and_cash_return():
    result = synthetic.run_golden()
    assert [f['quantity'] for f in result['account']['fills']] == [2000, 3000, 5000, 5000, 3000, 2000]
    assert [f['cash'] for f in result['account']['fills']] == [100000, 67000, 7000, 72000, 108000, 130000]
    assert result['account']['cycles'][0]['profit'] == 10000
    assert abs(result['metrics']['total_return']-D(1)/12) < D('1e-25')


@pytest.mark.parametrize('order,expected', [
    (('S1', 'S2', 'S3'), [1000, 600, 400]),
    (('S3', 'S1', 'S2'), [400, 1000, 600]),
    (('S2', 'S3', 'S1'), [600, 400, 1000]),
])
def test_partial_build_sell_denominator_never_uses_Q_or_remaining(order, expected):
    a = account()
    step(a, 0, 'B1')
    step(a, 1, order[0])
    step(a, 2, order[1])
    step(a, 3, order[2])
    step(a, 4)
    assert [f['quantity'] for f in a.fills] == [2000]+expected
    assert all(f['v'] == 2000 for f in a.fills if f['side'] == 'sell')
    assert a.phase == 'flat'


def test_b3_first_is_half_not_full_position():
    a = account()
    step(a, 0, 'B3')
    step(a, 1)
    assert a.q == 10000 and a.shares == 5000 and a.cash == 50000


def test_same_bar_classes_add_and_repeats_do_not_add():
    a = account()
    step(a, 0, 'B1', 'B2')
    step(a, 1, 'B1', 'B2')
    step(a, 2, 'B1')
    assert [f['quantity'] for f in a.fills] == [5000]
    step(a, 3, 'S1')
    step(a, 4, 'S1')
    step(a, 5)
    assert a.shares == 2500 and len(a.fills) == 2


def test_exact_event_duplicate_ignored_but_mutation_rejected():
    a = account()
    b = bar(0)
    event = signals(b, 'B1')[0]
    a.step(b, [event, event])
    a.step(bar(1), [event])
    assert a.shares == 2000
    with pytest.raises(DataBlocked, match='changed first-known'):
        a.step(bar(2), [replace(event, group='B2')])
    with pytest.raises(DataBlocked, match='failed account'):
        a.result()


def test_sell_priority_in_flat_and_holding():
    a = account()
    step(a, 0, 'B3', 'S3')
    step(a, 1, 'B1')
    step(a, 2, 'B2', 'S3')
    assert a.q == 10000 and a.v == 2000 and a.phase == 'reducing'
    step(a, 3, 'B3')
    step(a, 4)
    assert [f['quantity'] for f in a.fills] == [2000, 400]
    assert a.shares == 1600


def test_zero_filled_cycle_cancelled_by_sell_without_counting_trade():
    a = account()
    step(a, 0, 'B1', volume_shares=0)
    step(a, 1, 'S1', 'B3', volume_shares=0)
    step(a, 2)
    assert a.phase == 'flat' and a.fills == [] and a.cycles == []


def test_pending_buy_cancelled_on_first_sell():
    a = account()
    step(a, 0, 'B3', volume_shares=10000)
    step(a, 1, 'S1')
    assert a.shares == 100 and a.v == 100
    step(a, 2)
    assert len(a.fills) == 1  # 50 shares is below this fixture's minimum sale.
    step(a, 3, 'S2', 'S3')
    step(a, 4)
    assert [f['quantity'] for f in a.fills] == [100, 100]


def test_next_open_not_signal_close_and_Q_does_not_use_future_price():
    a = account()
    step(a, 0, 'B3')
    assert a.fills == [] and a.q == 10000
    step(a, 1, price=30)
    assert a.q == 10000 and a.shares == 3300 and a.cash == 1000
    assert a.fills[0]['time'] == bar(1).start.isoformat()
    assert a.result()['end_state']['pending_buy'] == 1700


def test_Q_freezes_until_next_round_then_reinvests():
    a = account()
    step(a, 0, 'B1')
    step(a, 1, 'B2', price=11)
    assert a.q == 10000
    step(a, 2, 'S1', 'S2', 'S3', price=12)
    step(a, 3, 'B3', price=20)
    assert a.phase == 'flat'  # A close on this bar cannot be followed by a re-entry here.
    step(a, 4)
    assert a.phase == 'flat'  # The ignored B3 must not be resurrected.
    step(a, 5, 'B3', price=20)
    assert a.q == 7000 and a.cycle_number == 2  # cash142000 / 20 floored to 1000 shares.


def test_T_plus_one_and_lunch_open_time():
    a = account()
    first = replace(bar(0), start=datetime(2026, 1, 1, 11), end=datetime(2026, 1, 1, 11, 30))
    a.step(first, signals(first, 'B1'))
    lunch = replace(first, start=datetime(2026, 1, 1, 13), end=datetime(2026, 1, 1, 13, 30))
    a.step(lunch, signals(lunch, 'S1', 'S2', 'S3'))
    later = replace(lunch, start=datetime(2026, 1, 1, 13, 30), end=datetime(2026, 1, 1, 14))
    a.step(later)
    assert len(a.fills) == 1 and a.fills[0]['time'].endswith('13:00:00')
    step(a, 1)
    assert a.shares == 0 and len(a.fills) == 2


def test_previous_volume_only_and_partial_retry():
    a = account()
    step(a, 0, 'B1', volume_shares=10000)
    step(a, 1, volume_shares=20000)
    step(a, 2, volume_shares=0)
    step(a, 3, volume_shares=99999999)
    assert [f['quantity'] for f in a.fills] == [100, 200]
    step(a, 4)
    assert [f['quantity'] for f in a.fills] == [100, 200, 1700]


def test_limits_block_only_adverse_direction():
    a = account()
    step(a, 0, 'B1')
    step(a, 1, lower=D(9), upper=D(10))
    assert not a.fills
    step(a, 2, 'S1', 'S2', 'S3', lower=D(10), upper=D(11))
    step(a, 3, lower=D(10), upper=D(11))
    assert len(a.fills) == 1  # buy at lower limit allowed, sell at lower limit denied.
    step(a, 4, lower=D(9), upper=D(10))
    assert a.shares == 0


def test_slippage_tick_rounding_and_invalid_limit_price():
    spec = replace(SPEC, slippage=D('.0005'))
    assert model_price(D(10), True, RULE, spec) == D('10.01')
    assert model_price(D(10), False, RULE, spec) == D('9.99')
    a = Account('000001.SZ', spec=replace(spec, slippage=D('.1')))
    step(a, 0, 'B1')
    step(a, 1, lower=D(9), upper=D('10.01'))
    assert not a.fills


def test_minimum_commission_each_partial_fill_and_dated_taxes():
    spec = replace(SPEC, commission_rate=D('.0003'), minimum_commission=D(5))
    rule = replace(RULE, transfer_rate=D('.00001'), stamp_sell_rate=D('.001'))
    assert fees(100, D(10), True, rule, spec) == dict(commission=D(5), transfer=D('.01'), stamp=D(0))
    assert fees(100, D(10), False, rule, spec) == dict(commission=D(5), transfer=D('.01'), stamp=D(1))
    a = Account('000001.SZ', spec=spec)
    step(a, 0, 'B1', volume_shares=10000, rule=rule)
    step(a, 1, volume_shares=10000, rule=rule)
    step(a, 2, rule=rule)
    assert a.cash == D('117989.98')
    assert [f['fees']['commission'] for f in a.fills] == [5, 5]


def test_affordable_binary_search_includes_fee_and_handles_zero():
    spec = replace(SPEC, commission_rate=D('.0003'), minimum_commission=D(5))
    assert affordable(D(1000), D(10), 100, 100, 100, RULE, spec) == 0
    assert affordable(D(1005), D(10), 100, 100, 100, RULE, spec) == 100
    assert affordable(D(1000000), D(10), 0, 100, 100, RULE, spec) == 0


def test_board_minimum_and_increment_not_assumed_100():
    rule = replace(RULE, buy_min=200, buy_step=1, sell_min=200, sell_step=1)
    a = account()
    step(a, 0, 'B1', volume_shares=25000, rule=rule)
    step(a, 1, rule=rule)
    assert a.shares == 250
    step(a, 2, 'S3', rule=rule)
    step(a, 3, rule=rule)
    assert [f['quantity'] for f in a.fills] == [250, 1750, 400]
    assert a.shares == 1600  # B1 total stays2000; the partial250 fill must not enlarge it.


def test_all_sells_clean_odd_tail_only_when_permitted():
    assert RULE.quantity(50, False, 50) == 50
    assert RULE.quantity(50, False, 100) == 0
    assert replace(RULE, odd_final_sell=False).quantity(50, False, 50) == 0


def test_warmup_counts_distinct_actual_days_not_bars():
    a = account(warmup_days=2)
    step(a, 0, 'B1')
    extra = replace(bar(0), start=datetime(2026, 1, 1, 10), end=datetime(2026, 1, 1, 10, 30))
    a.step(extra, signals(extra, 'B3'))
    step(a, 1, 'B2')
    step(a, 2)
    assert a.fills == [] and a.phase == 'flat'
    step(a, 3, 'B3')
    step(a, 4)
    assert a.shares == 5000


def test_no_signals_no_fake_win_rate():
    a = account()
    step(a, 0)
    step(a, 1)
    result = metrics(a.result())
    assert result['total_return'] == 0 and result['win_rate'] is None


def test_open_loss_counted_no_forced_final_exit():
    a = account()
    step(a, 0, 'B3')
    step(a, 1)
    step(a, 2, price=6)
    result = metrics(a.result())
    assert a.shares == 5000 and a.cycles == []
    assert result['total_return'] == D('-.2') and result['maximum_drawdown'] == D('.2')
    assert result['unfinished_cycle'] and result['win_rate'] is None


def test_prefix_and_future_perturbation_cannot_change_past():
    spec, bars, event_lists = synthetic.golden_inputs()
    full = Account('000001.SZ', spec=spec)
    prefix = Account('000001.SZ', spec=spec)
    perturbed = Account('000001.SZ', spec=spec)
    for i, (b, es) in enumerate(zip(bars, event_lists, strict=True)):
        full.step(b, es)
        if i < 4:
            prefix.step(b, es)
        altered = replace(b, open=b.open*2, close=b.close*2, volume_shares=0) if i >= 4 else b
        perturbed.step(altered, es)
    end = bars[3].end.isoformat()
    for key in ('fills', 'journal', 'decisions', 'equity'):
        assert [r for r in full.result()[key] if r['time'] <= end] == prefix.result()[key]
        assert [r for r in perturbed.result()[key] if r['time'] <= end] == prefix.result()[key]


def effect(b, kind, value, reference='right1', event_id=None):
    return CorporateEffect(event_id or f'{b.start}:{kind}', b.start, kind, D(value), reference,
                           'SYNTHETIC explicitly normalized effect')


def test_split_converts_quota_fills_lots_and_prior_volume_without_creating_profit():
    a = account()
    step(a, 0, 'B1')
    step(a, 1, 'S1', volume_shares=10000)
    split = bar(2, price=5)
    a.step(split, effects=[effect(split, 'unit_split', 2)])
    assert (a.q, a.v, a.bought, a.sold, a.shares) == (20000, 4000, 4000, 200, 3800)
    assert a.fills[-1]['quantity'] == 200  # previous volume rebased to20000, not stale10000.
    assert a.equity[-1]['equity'] == 100000
    audit(a.result())


def test_split_rebases_already_sold_quantity_and_odd_tail():
    a = account()
    step(a, 0, 'B1')
    step(a, 1, 'S1')
    step(a, 2)
    split = bar(3, price=8)
    a.step(split, signals(split, 'S2', 'S3'), [effect(split, 'unit_split', '1.25')])
    assert (a.v, a.sold, a.shares) == (2500, 1250, 1250)
    step(a, 4, price=8)
    assert a.shares == 0 and a.cycles[0]['profit'] == 0


def test_cash_right_payment_not_double_income_and_delays_cycle_closure():
    a = account()
    step(a, 0, 'B1')
    step(a, 1, 'S1', 'S2', 'S3')
    ex = bar(2, price=9)
    a.step(ex, effects=[effect(ex, 'cash_right', 2000)])
    assert a.shares == 0 and a.phase == 'reducing' and a.cycles == []
    assert a.equity[-1]['equity'] == 100000 and a.cash == 98000
    pay = bar(3, price=9)
    a.step(pay, signals(pay, 'B3'), [effect(pay, 'cash_pay', 2000)])
    assert a.cash == 100000 and a.phase == 'flat' and len(a.cycles) == 1
    assert a.cycles[0]['profit'] == 0 and a.realized == 0
    audit(a.result())


@pytest.mark.parametrize('kind', ['bonus_pending_listing', 'rights_issue', 'dividend_tax', 'unknown'])
def test_unimplemented_corporate_actions_explicitly_block(kind):
    with pytest.raises(DataBlocked, match='unsupported'):
        effect(bar(0), kind, 1)


@pytest.mark.parametrize('mutation', ['fraction', 'wrong_payment', 'duplicate_right', 'future'])
def test_bad_corporate_facts_poison_account(mutation):
    a = account()
    step(a, 0, 'B1', volume_shares=10000)
    step(a, 1)
    b = bar(2)
    if mutation == 'fraction':
        effects = [effect(b, 'unit_split', '1.003')]
    elif mutation == 'wrong_payment':
        effects = [effect(b, 'cash_pay', 10)]
    elif mutation == 'duplicate_right':
        effects = [effect(b, 'cash_right', 10, event_id='x'), effect(b, 'cash_right', 10, event_id='y')]
    else:
        effects = [effect(bar(3), 'cash_right', 10)]
    with pytest.raises(DataBlocked):
        a.step(b, effects=effects)
    with pytest.raises(DataBlocked, match='failed account'):
        a.step(bar(3))


@pytest.mark.parametrize('changes', [
    {'price_basis': 'qfq'}, {'limits_known': False}, {'volume_shares': -1},
    {'open': D('NaN')}, {'close': D('Infinity')}, {'open': D('10.001')},
    {'lower': D(11), 'upper': D(12)}, {'rule': replace(RULE, start=date(2026, 2, 1))},
])
def test_invalid_raw_or_unknown_execution_facts(changes):
    with pytest.raises(DataBlocked):
        replace(bar(0), **changes)


@pytest.mark.parametrize('changes', [
    {'code': '000002.SZ'}, {'frequency': 60}, {'time': bar(1).end},
])
def test_mixed_or_future_signal_rejected(changes):
    a = account()
    b = bar(0)
    with pytest.raises(DataBlocked):
        a.step(b, [replace(signals(b, 'B1')[0], **changes)])


def test_duplicate_bars_and_budget_cannot_continue():
    a = account(max_bars=1)
    step(a, 0)
    with pytest.raises(DataBlocked, match='order/budget'):
        a.step(bar(1))
    a = account()
    step(a, 0)
    with pytest.raises(DataBlocked, match='order/budget'):
        a.step(bar(0))


def test_signal_adapter_uses_first_known_not_anchor_or_evaluation():
    event = dict(event_id='x', code='000001.SZ', frequency=30, group='B3',
                 sure=True, buy=True, types=['3a'], signal_time='2026-01-05 10:00:00',
                 anchor_time='2025-12-20 10:00:00', evaluation=False)
    assert Signal.from_chan_event(event).time == datetime(2026, 1, 5, 10)
    for change in ({'sure': False}, {'buy': False}, {'types': ['1p', '2s']},
                   {'anchor_time': '2026-01-06 10:00:00'}):
        with pytest.raises(DataBlocked):
            Signal.from_chan_event(dict(event, **change))


@pytest.mark.parametrize('target', ['cash', 'quantity', 'fee', 'time', 'quota', 'equity', 'rights', 'profit'])
def test_independent_auditor_catches_corrupt_account(target):
    r = deepcopy(synthetic.run_golden()['account'])
    if target == 'cash':
        r['fills'][0]['cash'] += 1
    elif target == 'quantity':
        r['fills'][0]['quantity'] += 100
    elif target == 'fee':
        r['fills'][0]['fees']['stamp'] += 1
    elif target == 'time':
        r['fills'][0]['time'] = r['fills'][0]['bar_end']
    elif target == 'quota':
        r['fills'][0]['q'] = 1000
    elif target == 'equity':
        r['equity'][-1]['equity'] += 1
    elif target == 'rights':
        r['end_state']['rights'] = D(1)
    else:
        r['cycles'][0]['profit'] += 1
    with pytest.raises(ValueError, match='account audit'):
        audit(r)


def test_new_output_only_and_recompute_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(synthetic, 'REPORTS', tmp_path)
    output = tmp_path/'case'
    synthetic.execute(output)
    assert synthetic.verify(output)['status'] == 'synthetic_replay_verified'
    with pytest.raises(ValueError, match='new direct child'):
        synthetic.execute(output)
    # Tampering both artifact and its checksum still fails recomputation.
    value = json.loads((output/'example.json').read_text())
    value['metrics']['ending_equity'] = '999999'
    raw = synthetic.encode(value)
    (output/'example.json').write_bytes(raw)
    manifest = json.loads((output/'manifest.json').read_text())
    manifest['artifacts_sha256']['example.json'] = synthetic.sha256(raw).hexdigest()
    (output/'manifest.json').write_bytes(synthetic.encode(manifest))
    with pytest.raises(ValueError, match='replay differs'):
        synthetic.verify(output)


def test_cli_serializes_decimal_spec_without_failing_after_seal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(synthetic, 'REPORTS', tmp_path)
    output = tmp_path/'cli'
    monkeypatch.setattr(sys, 'argv', ['stock_share_synthetic', '--output', str(output)])
    synthetic.main()
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'synthetic_example_passed'
    assert result['spec']['initial_cash'] == '120000'
    monkeypatch.setattr(sys, 'argv', ['stock_share_synthetic', '--verify', str(output)])
    synthetic.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'synthetic_replay_verified'


@pytest.mark.parametrize('code', ['000001.SH', '399001.SZ', '900001.SH', '200001.SZ', '920305.BJ', '510300.SH'])
def test_index_B_share_BSE_and_fund_codes_rejected(code):
    with pytest.raises(DataBlocked, match='stock identity'):
        Account(code)


def test_returned_ledger_is_not_mutable_account_state():
    a = account()
    step(a, 0, 'B1')
    step(a, 1)
    snapshot = a.result()
    snapshot['fills'][0]['cash'] = D(-1)
    snapshot['end_state']['cash'] = D(-1)
    assert a.fills[0]['cash'] == 80000 and a.cash == 80000
    audit(a.result())


def test_auditor_rejects_equity_components_even_if_total_unchanged():
    r = synthetic.run_golden()['account']
    r['equity'][1]['cash'] += 10
    r['equity'][1]['shares'] -= 1
    with pytest.raises(ValueError, match='equity table'):
        audit(r)


def test_auditor_rejects_duplicate_cycles():
    r = synthetic.run_golden()['account']
    r['cycles'].append(deepcopy(r['cycles'][0]))
    with pytest.raises(ValueError, match='duplicate/out-of-order completed cycles'):
        audit(r)


@pytest.mark.parametrize('seed', range(12))
def test_randomized_interleaved_account_conservation_and_replay(seed):
    rng = random.Random(seed)
    spec = replace(StockShareBacktestSpec(), initial_cash=D(100000), warmup_days=0)
    accounts = [Account('000001.SZ', spec=spec), Account('000001.SZ', spec=spec)]
    for day in range(200):
        b = bar(day, price=rng.randint(5, 30), volume_shares=rng.randint(0, 10000)*100)
        groups = rng.sample(['B1', 'B2', 'B3', 'S1', 'S2', 'S3'], rng.randint(0, 3))
        events = signals(b, *groups)
        for a in accounts:
            a.step(b, events)
    audit(accounts[0].result())
    assert accounts[0].result() == accounts[1].result()
