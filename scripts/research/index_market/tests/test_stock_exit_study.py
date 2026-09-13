from scripts.research.index_market.chan import stock_exit_study as study
from dataclasses import replace


def data():
    times=[f'2025-01-{i//8+1:02d} {i%8:02d}:00:00' for i in range(40)]
    rows=[dict(open=10,close=10,high=11,low=9,vol=1,amount=10) for _ in times]
    return times,rows


def test_next_open_t1_and_gap(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3,fixed_days=1))
    t,r=data();r[8]['open']=8
    x=study.simulate(t,r,0,'structure',{2})
    assert x['exit_index']==8 and x['exit_price']==8 and x['return_value']==-0.19999999999999996
    assert x['exit_phase']=='open'


def test_pending_survives_suspension_and_signal_disappearing(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3))
    t,r=data();r[8]=None;r[9]['vol']=0
    x=study.simulate(t,r,0,'sell',{2})
    assert x['exit_index']==10 and x['reason']=='sell'


def test_no_signal_timeout_and_tail(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3))
    t,r=data()
    x=study.simulate(t,r,0,'sell',set())
    assert x['exit_index']==24 and x['reason']=='timeout'
    assert study.simulate(t,r,20,'sell',set())['status']=='insufficient_horizon'


def test_preentry_signal_ignored_and_samebar_not_filled(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3))
    t,r=data()
    assert study.simulate(t,r,0,'sell',{0})['reason']=='timeout'
    assert study.simulate(t,r,0,'sell',{9})['exit_index']==10


def test_shared_pairs_reject_partial_arm():
    c=dict(signal_time='2025-01-01',arms={'fixed10':dict(status='closed',exit_time='2025-01-03'),'sell':dict(status='unclosed')})
    assert study.paired([c],'2025-01-01','2025-02-01')==[]


def test_timeout_suspension_delays_to_open(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3))
    t,r=data();r[24]=None;r[25]['open']=12
    x=study.simulate(t,r,0,'sell',set())
    assert x['exit_index']==25 and x['exit_phase']=='open' and x['delay_slots']==1


def test_exit_open_does_not_use_later_high_low(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_days=3))
    t,r=data();r[10].update(high=1000,low=1)
    x=study.simulate(t,r,0,'sell',{9})
    assert x['favorable']<0.11 and x['adverse']>-.11
