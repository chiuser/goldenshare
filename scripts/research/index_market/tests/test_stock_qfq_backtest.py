"""Synthetic QFQ adapters, independent account semantics and no corporate double count."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta

import pytest

from scripts.research.index_market.chan.stock_qfq_model import SPEC, account_prefix_equal, simulate, summarize, to_bar
from scripts.research.index_market.chan.stock_qfq_run import validate_rows
from scripts.research.index_market.chan.stock_share_model import D, RawBar


def spec():
    return replace(SPEC, account=replace(SPEC.account, warmup_days=0, initial_cash=D(120000)))


def row(i, price, start=None):
    end = start or datetime(2026, 1, 5, 10)+timedelta(days=i)
    return dict(code=SPEC.code, frequency=30, exchange='SZSE', date=str(end.date()),
                time=str(end), open=price, high=price, low=price, close=price,
                vol=1000000, amount=1000000*price, price_basis='qfq')


def event(r, group):
    return dict(event_id=r['time']+'|'+group, code=SPEC.code, frequency=30, group=group,
                buy=group.startswith('B'), sure=True, types=['3a' if group[-1]=='3' else group[-1]],
                signal_time=r['time'], anchor_time=r['time'], evaluation=False)


def golden():
    rows = [row(i, p) for i, p in enumerate([12, 10, 11, 12, 13, 12, 11])]
    events = [event(r, g) for r, g in zip(rows, ['B1','B2','B3','S1','S2','S3'])]
    return rows, events


def test_qfq_golden_share_quantities_and_no_corporate_effects():
    rows, events = golden()
    result = simulate(rows, events, spec(), 'gross')
    assert [f['quantity'] for f in result['fills']] == [2000,3000,5000,5000,3000,2000]
    assert result['end_state']['cash'] == 130000
    assert result['cycles'][0]['profit'] == 10000
    assert {r['kind'] for r in result['journal']} == {'mark', 'fill'}
    assert not isinstance(to_bar(rows[0], spec()), RawBar)


def test_same_timestamp_next_open_does_not_contaminate_prefix():
    a = row(0, 10)
    b = row(0, 11, datetime(2026, 1, 5, 10, 30))
    es = [event(a, 'B1')]
    full = simulate([a,b], es, spec(), 'gross')
    prefix = simulate([a], es, spec(), 'gross')
    assert full['fills'][0]['time'] == '2026-01-05T10:00:00'
    assert prefix['fills'] == []
    assert account_prefix_equal(full, prefix, a['time'])


def test_hold_uses_common_start_not_first_strategy_buy():
    rows, _ = golden()
    es = [event(rows[4], 'B3')]
    held = simulate(rows, es, spec(), 'gross', hold=True)
    strategy = simulate(rows, es, spec(), 'gross')
    assert held['fills'][0]['bar_end'] == rows[1]['time'].replace(' ', 'T')
    assert strategy['fills'][0]['bar_end'] == rows[5]['time'].replace(' ', 'T')
    assert all(f['side']=='buy' for f in held['fills'])


def test_cost_modes_recompute_Q_and_cash():
    rows, es = golden()
    gross, net = [simulate(rows, es, spec(), mode) for mode in ('gross', 'model_cost')]
    assert gross['fills'][0]['q'] == 10000
    assert net['fills'][0]['q'] == 9000
    assert net['fills'][0]['fees']['commission'] > 0


@pytest.mark.parametrize('change', [{'price_basis':'raw'}, {'code':'000001.SH'}, {'frequency':60}, {'vol':10.1}])
def test_bad_qfq_inputs_rejected(change):
    r = dict(row(0, 10), **change)
    with pytest.raises(ValueError):
        to_bar(r)


def test_unknown_or_future_signal_rejected():
    rows, es = golden()
    with pytest.raises(ValueError, match='event outside'):
        simulate(rows[:2], es, spec())


def test_metrics_mark_open_position_no_forced_exit():
    rows = [row(0,10), row(1,10), row(2,5)]
    es = [event(rows[0],'B3')]
    result = simulate(rows, es, spec(), 'gross')
    summary = summarize(result, rows, es, spec())
    assert summary['total_return'] == D('-.25')
    assert summary['maximum_drawdown'] == D('.25')
    assert summary['win_rate'] is None and summary['end_shares'] == 6000


def test_grid_validation_cannot_drop_missing_bars():
    rows, _ = golden()
    with pytest.raises(ValueError, match='grid mismatch'):
        validate_rows(rows, [r['date'] for r in rows], spec())


def test_spec_serializes_frozen_cash_policy():
    assert asdict(SPEC)['account']['initial_cash'] == 1000000
    assert SPEC.corporate_actions == 'none_qfq_only'
