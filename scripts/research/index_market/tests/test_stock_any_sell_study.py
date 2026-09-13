"""Synthetic checks for section 30, with no data services or live backtest."""
from copy import deepcopy
from dataclasses import replace
import socket

import pytest

from scripts.research.index_market.chan import stock_any_sell_study as s


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args,**kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket,'create_connection',deny)


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setattr(s.old,'SPEC',replace(s.old.SPEC,max_days=3))
    t=[f'2025-01-{i//8+1:02d} {i%8:02d}:00:00' for i in range(40)]
    rows=[dict(open=10,close=11,high=12,low=9,vol=1,amount=10) for _ in t]
    arm=s.old.simulate(t,rows,0,'sell',set())
    c=dict(code='X',signal_time=t[0],signal_index=0,types=['B1'],event_ids=['buy'],
           arms={a:deepcopy(arm) for a in s.old.SPEC.arms})
    return t,rows,c


def event(t,i=2,group='S2'):
    return dict(event_id=f'X|sell|anchor|{group}',signal_time=t[i],signal_index=i,
                anchor_time=t[1],group=group,buy=False)


def previous(c,category='nonmatching_only'):
    return [dict(signal_time=c['signal_time'],category=category)]


def test_config_exact_a_only():
    a=dict(bs_point_conf={'s_conf':{'bsp3_follow_1':True}}, other=1)
    s.require_original_a(a,deepcopy(a))
    b=deepcopy(a); b['other']=2
    with pytest.raises(ValueError): s.require_original_a(b,a)
    b=deepcopy(a); b['bs_point_conf']['s_conf']['bsp3_follow_1']=False
    with pytest.raises(ValueError): s.require_original_a(b,a)
    with pytest.raises(ValueError): s.require_original_a(b,b)


@pytest.mark.parametrize('group',['S1','S2','S3'])
def test_any_number_allowed_and_deduplicated(group):
    e=dict(signal_time='t',group=group,buy=False)
    assert s.sell_triggers([e,e],{'t':3})=={3}


@pytest.mark.parametrize('group',['1p','2s','B1','B2','B3'])
def test_no_new_raw_type_or_buy_admission(group):
    assert not s.sell_triggers([dict(signal_time='t',group=group,buy=group.startswith('B'))],{'t':3})


def test_cross_number_t1_and_projection_preserves_buy(sample):
    t,rows,c=sample; frozen=deepcopy(c)
    p=s.compare([c],[event(t)],rows,t,rows,previous(c))[0]
    assert c==frozen and p['types']==['B1'] and p['event_ids']==['buy']
    assert p['before']['reason']=='timeout' and p['after']['exit_index']==8
    assert p['after']['exit_phase']=='open' and p['used_sell_event_ids']==[event(t)['event_id']]
    assert p['independent']['types']==['B1']
    assert p['independent']['eligible_sell_groups']==['S1','S2','S3']
    assert not p['independent']['differences']


def test_suspension_zero_turnover_and_exit_open_mae(sample):
    t,rows,c=sample; rows[8]=None; rows[9]['vol']=0
    rows[10].update(open=8,low=1,high=1000)
    c['arms']['sell']=s.old.simulate(t,rows,0,'sell',set())
    p=s.compare([c],[event(t)],rows,t,rows,previous(c))[0]
    assert p['after']['exit_index']==10 and p['after']['exit_price']==8
    assert p['after']['adverse']==pytest.approx(-.2) and p['after']['favorable']==pytest.approx(.2)


def test_no_sell_window_unchanged(sample):
    t,rows,c=sample
    p=s.compare([c],[],rows,t,rows,previous(c,s.audit.NO_SELL))[0]
    assert p['before']==p['after'] and p['delta']==0 and p['used_sell_event_ids']==[]


@pytest.mark.parametrize('i',[0,24,25])
def test_preentry_and_deadline_or_later_cannot_trigger(sample,i):
    t,rows,c=sample
    p=s.compare([c],[event(t,i)],rows,t,rows,previous(c))[0]
    assert p['before']==p['after'] and not p['used_sell_event_ids']


def test_original_matching_can_be_preempted(sample):
    t,rows,c=sample
    events=[event(t,2,'S2'),event(t,16,'S1')]
    c['arms']['sell']=s.old.simulate(t,rows,0,'sell',{16})
    p=s.compare([c],events,rows,t,rows,previous(c,'matched_sell_exit'))[0]
    assert p['before']['exit_index']==17 and p['after']['exit_index']==8


def test_independent_mismatch_stops(sample):
    t,rows,c=sample
    wrong=deepcopy(c['arms']['sell'])
    with pytest.raises(ValueError,match='independent'):
        s.independent(c,wrong,[event(t)],rows,t,rows)


def test_baseline_or_no_sell_drift_stops(sample):
    t,rows,c=sample
    with pytest.raises(ValueError,match='no-sell window'):
        s.compare([c],[event(t)],rows,t,rows,previous(c,s.audit.NO_SELL))
    c['arms']['sell']['return_value']=999
    with pytest.raises(ValueError,match='original execution'):
        s.compare([c],[],rows,t,rows,previous(c))


def test_execution_prefix_and_failure(sample):
    t,rows,c=sample; events=[event(t)]
    pairs=s.compare([c],events,rows,t,rows,previous(c))
    checked=s.execution_prefix([c],pairs,events,t,rows)
    assert [len(x['checked']) for x in checked]==[0,1]
    assert checked[0]['not_checked']==1
    pairs[0]['after']['return_value']=999
    with pytest.raises(ValueError,match='execution prefix'):
        s.execution_prefix([c],pairs,events,t,rows)


def test_unclosed_retained_and_no_subset_mean(sample,monkeypatch):
    t,rows,c=sample
    original=s.old.simulate; calls=[]
    def fake(*args):
        calls.append(True)
        return original(*args) if len(calls)==1 else dict(status='unclosed')
    monkeypatch.setattr(s.old,'simulate',fake)
    p=s.compare([c],[event(t)],rows,t,rows,previous(c))[0]
    assert p['independent'] is None and p['delta'] is None
    assert s.shared.metrics([p])==dict(n=1,unclosed=1)


def test_event_change_or_order_rejected():
    with pytest.raises(ValueError): s.audit.equal([1,2],[2,1],'all original events')
    with pytest.raises(ValueError): s.audit.equal([dict(types=['3a'])],[dict(types=['1'])],'all original events')
