from copy import deepcopy
from dataclasses import replace
import pytest

from scripts.research.index_market.chan import stock_sell_usage_audit as audit
from scripts.research.index_market.chan import stock_exit_study as old


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setattr(old, 'SPEC', replace(old.SPEC, max_days=3))
    times = [f'2025-01-{i//8+1:02d} {i%8:02d}:00:00' for i in range(40)]
    rows = [dict(time=t, open=10., close=10., high=11., low=9., vol=1., amount=10.) for t in times]
    return times, rows


def event(times, index, group='S1'):
    return dict(event_id=f'{group}:{index}', code='000731.SZ', frequency=60,
                group=group, buy=group.startswith('B'), sure=True, signal_index=index,
                signal_time=times[index], anchor_index=index-1, anchor_time=times[index-1])


def result(sample, es, types=('B1',), corrupt=False):
    t, r = sample
    triggers = {e['signal_index'] for e in es if e['group'] in {'S'+g[1:] for g in types}}
    observed = old.simulate(t, r, 0, 'sell', triggers)
    if corrupt:
        observed['exit_price'] = 999
    case = dict(code='000731.SZ', signal_index=0, signal_time=t[0], types=list(types), arms={'sell':observed})
    return audit.diagnose(case, es, r, t, r, 24)


def test_no_sellers(sample):
    x = result(sample, [])
    assert x['category'] == 'no_sell_in_trigger_window'
    assert x['sellers'] == [] and x['differences'] == {}


def test_nonmatching_only_is_actionable_not_a_fill(sample):
    x = result(sample, [event(sample[0], 9, 'S2')])
    assert x['category'] == 'nonmatching_only'
    assert x['actionable_other_before_exit'] == 1
    assert x['recorded_exit']['reason'] == 'timeout'
    assert 'return_value' not in x['first_actionable_other']['execution']
    assert not x['differences']


def test_matching_first_sell_and_multi_type(sample):
    t, _ = sample
    es = [event(t, 9, 'S2'), event(t, 13, 'S1')]
    x = result(sample, es, ('B1', 'B2'))
    assert x['category'] == 'matched_sell_exit'
    assert x['independent_exit']['exit_index'] == 10
    assert not x['differences']


def test_same_signal_bar_and_deadline_are_not_usable(sample):
    t, _ = sample
    x = result(sample, [event(t, 0), event(t, 24)])
    assert x['category'] == 'no_sell_in_trigger_window'
    assert len(x['sellers']) == 1 and not x['sellers'][0]['before_deadline']
    assert not x['differences']


def test_t1_and_suspension_then_zero_turnover_wait(sample):
    t, r = sample
    r[8] = None
    r[9]['vol'] = 0
    x = result(sample, [event(t, 2)])
    s = x['sellers'][0]
    assert s['execution']['index'] == 10
    assert s['execution']['blocked_slots'] == {'T+1':5, 'missing_bar':1, 'zero_turnover':1}
    assert not x['differences']


def test_no_executable_slot_before_deadline(sample):
    t, r = sample
    r[24] = None
    x = result(sample, [event(t, 23)])
    assert x['sellers'][0]['execution']['index'] is None
    assert x['independent_exit']['exit_index'] == 25
    assert x['recorded_exit']['reason'] == 'sell'
    assert not x['differences']


def test_signal_after_original_exit_is_not_missed(sample):
    t, _ = sample
    x = result(sample, [event(t, 9), event(t, 13, 'S2')])
    assert not x['sellers'][1]['while_original_holding']
    assert x['actionable_other_before_exit'] == 0


def test_corrupted_record_is_exposed(sample):
    x = result(sample, [event(sample[0], 9)], corrupt=True)
    assert 'exit_price' in x['differences']


@pytest.mark.parametrize('field,value', [('sure', False), ('anchor_index', 12),
    ('buy', True), ('frequency', 30), ('code', '000001.SH'), ('anchor_time', '2099-01-01')])
def test_event_identity_and_future_rejected(sample, field, value):
    t, r = sample
    e = event(t, 9)
    audit.validate_events([e], r, '000731.SZ')
    e[field] = value
    with pytest.raises(ValueError):
        audit.validate_events([e], r, '000731.SZ')


def test_duplicate_event_rejected(sample):
    t, r = sample
    e = event(t, 9)
    with pytest.raises(ValueError):
        audit.validate_events([e, deepcopy(e)], r, '000731.SZ')
