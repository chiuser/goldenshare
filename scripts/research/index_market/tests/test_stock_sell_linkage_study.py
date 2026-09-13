"""Synthetic tests only; never replay market data or access the Lake."""
from copy import deepcopy
from dataclasses import replace
import json
import socket
from zipfile import ZipFile

import pytest

from scripts.research.index_market.chan import stock_sell_linkage_study as s


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def config():
    return dict(bs_point_conf=dict(b_conf=dict(bsp3_follow_1=False), s_conf=dict(bsp3_follow_1=True)),
                seg_bs_point_conf=dict(b_conf=dict(bsp3_follow_1=True), s_conf=dict(bsp3_follow_1=True)))


def test_one_config_only():
    b = config(); a = deepcopy(b)
    a['bs_point_conf']['s_conf']['bsp3_follow_1'] = False
    s.require_single_change(b, a)
    assert b == config()
    raw = s.SymmetricSpec().chan_config()
    assert raw == dict(s.VARIANT_A.chan_config(), **{'bsp3_follow_1-sell': False})


@pytest.mark.parametrize('section,side', [('bs_point_conf', 'b_conf'),
    ('seg_bs_point_conf', 'b_conf'), ('seg_bs_point_conf', 's_conf')])
def test_extra_config_change_rejected(section, side):
    b = config(); a = deepcopy(b)
    a['bs_point_conf']['s_conf']['bsp3_follow_1'] = False
    a[section][side]['bsp3_follow_1'] = not a[section][side]['bsp3_follow_1']
    with pytest.raises(ValueError):
        s.require_single_change(b, a)


def test_unchanged_or_wrong_baseline_rejected():
    with pytest.raises(ValueError):
        s.require_single_change(config(), config())
    b = config(); b['bs_point_conf']['s_conf']['bsp3_follow_1'] = False
    with pytest.raises(ValueError):
        s.require_single_change(b, b)


def event(key='sell', **kwargs):
    return dict(event_id=key, buy=key.startswith('buy'), group='S3', signal_time='t', **kwargs)


def test_full_event_diff_includes_metadata_addition_removal():
    b = [event('buy'), event('old'), event('same', types=['2'])]
    a = [event('buy'), event('new'), event('same', types=['2','3a'])]
    d = s.event_difference(b, a)
    assert [e['event_id'] for e in d['added']] == ['new']
    assert [e['event_id'] for e in d['removed']] == ['old']
    assert d['changed'] == [dict(event_id='same', fields={'types':dict(before=['2'], after=['2','3a'])})]


@pytest.mark.parametrize('after', [[event('buy', extra=1)], [], [event('buy2'), event('buy')]])
def test_changed_missing_reordered_buy_rejected(after):
    with pytest.raises(ValueError):
        s.event_difference([event('buy')], after)


def test_duplicate_events_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        s.event_difference([], [event(), event()])


@pytest.mark.parametrize('types,wanted', [(['B1'], {1}), (['B2'], {2}),
    (['B3'], {3}), (['B1','B3'], {1,3})])
def test_numbered_pairing_unchanged(types, wanted):
    events = [dict(buy=False, group=f'S{i}', signal_time=str(i)) for i in (1,2,3)]
    assert s.triggers(dict(types=types), events, {str(i):i for i in (1,2,3)}) == wanted


def test_membership_uses_all_old_arms_and_period_end(monkeypatch):
    monkeypatch.setattr(s.old, 'PERIODS', {'full':('2025-01-01','2025-02-01')})
    def c(i, end, day):
        return dict(signal_index=i, signal_time=day,
            arms={a:dict(status='closed', exit_index=end, exit_time='2025-01-31') for a in s.old.SPEC.arms})
    xs = [c(0,20,'2025-01-01'), c(10,21,'2025-01-02'), c(22,35,'2025-01-03')]
    membership = s.freeze_membership(xs)
    assert len(membership['periods']['full']) == 3
    assert membership['nonoverlap']['full'] == ['2025-01-01','2025-01-03']
    xs[1]['arms']['sell']['exit_index'] = 11
    assert membership == s.freeze_membership(xs)


def pair(b=0.1, a=0.2):
    def arm(v):
        return dict(status='closed', return_value=v, reason='sell', holding_days=2, adverse=-0.1, favorable=0.3)
    return dict(before=arm(b), after=arm(a), fixed60=arm(b), delta=a-b)


def test_denominator_delta_and_empty():
    m = s.metrics([pair(), pair(0.2,0.1), pair(0,0)])
    assert m['n'] == 3 and m['delta']['mean'] == 0
    assert (m['delta']['better'],m['delta']['worse'],m['delta']['unchanged']) == (1,1,1)
    assert s.metrics([]) == dict(n=0,unclosed=0)


def test_unclosed_kept_blocks_mean():
    p = pair(); p.update(after=dict(status='unclosed'), delta=None)
    assert s.metrics([pair(),p]) == dict(n=2,unclosed=1)


def prefix_rows():
    return [dict(time=t+' 10:30:00', open=10,close=10,high=11,low=9)
            for t in ('2024-01-01','2025-01-01','2026-07-01')]


def fake_replay(rows, *args):
    return [dict(signal_index=i,signal_time=r['time'],price=r['close']) for i,r in enumerate(rows)]


def test_prefix_and_future_perturbation_are_bounded():
    rows = prefix_rows(); before = deepcopy(rows)
    x = s.check_prefix(rows,'X',None,fake_replay(rows),fake_replay)
    assert [c['bars'] for c in x['truncated']] == [1,2]
    assert x['future_perturbation']['passed'] and rows == before


@pytest.mark.parametrize('future', [False, True])
def test_prefix_or_future_leak_rejected(future):
    rows = prefix_rows()
    def leaky(rs, *args):
        result = fake_replay(rs)
        if (future and len(rs)==3 and rs[-1]['close']!=10) or (not future and len(rs)<3):
            result[0]['price'] = -1
        return result
    with pytest.raises(ValueError):
        s.check_prefix(rows,'X',None,fake_replay(rows),leaky)


def test_output_rejects_existing_and_outside(tmp_path):
    with pytest.raises(ValueError):
        s.safe_output(tmp_path)
    with pytest.raises(ValueError):
        s.safe_output(s.audit.REPO/'reports')


def test_checkpoint_roundtrip(tmp_path):
    m = dict(consumed_records={}, status='running')
    result = {'X': {'events':[], 'pairs':[]}}
    s.checkpoint(tmp_path,m,result)
    with ZipFile(tmp_path/'evidence.zip') as z:
        assert json.loads(z.read('X.json')) == result['X']
    assert json.loads((tmp_path/'manifest.json').read_bytes()) == m


def test_output_budget_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'SPEC', replace(s.SPEC,output_bytes=1))
    with pytest.raises(ValueError,match='budget'):
        s.checkpoint(tmp_path,dict(consumed_records={}),{'X':{'events':[]}})


def test_baseline_drift_stops_before_treatment_execution(monkeypatch):
    monkeypatch.setattr(s.old,'simulate',lambda *args: dict(status='closed',return_value=9))
    c=dict(signal_index=0, types=['B3'], arms={'sell':dict(status='closed',return_value=0)})
    with pytest.raises(ValueError,match='original sell'):
        s.compare_cases([c],[],[],[],[],[],[])
