"""C1 synthetic-only tests: no Lake, network, engine or real experiment run."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from scripts.research.index_market.chan.minute_comparison import (
    SPEC, common_comparison, contexts, evaluate, execute, intervals, matched_labels,
    nearest_pairs, sensitivity, simple_signals,
)
from scripts.research.index_market.chan.minute_score import label_rows, select_events
from scripts.research.index_market.chan.verify_comparison import reference_candidates, verify_cell


def prices(n=90):
    rows = []
    for d in range(n):
        day = str(date(2024,1,1)+timedelta(days=d))
        for slot in ('10:30:00','11:30:00','14:00:00','15:00:00'):
            rows.append(dict(date=day,time=day+' '+slot,open=100.,high=101.,low=99.,close=100.))
    return rows


def event(rows,i,name=None):
    return dict(event_id=name or str(i),signal_index=i,signal_time=rows[i]['time'],evaluation=True,group='B3')


def shape(close=(100.,102.,101.5), low=(100.,101.,100.)):
    rows = prices(4)[:len(close)]
    for r,c,lo in zip(rows,close,low):
        r.update(close=c,low=lo,open=c,high=max(c,lo))
    ctx = [dict(time=r['time'],level=100.,atr20=1.) for r in rows]
    return rows,ctx


def test_context_completed_day_windows_and_zero_denominator():
    rows = prices()
    ctx = contexts(rows)
    assert ctx[83]['atr20'] is None
    assert ctx[84]['atr20']==2.
    assert ctx[243]['background'] is None
    assert ctx[244]['level']==101. and ctx[244]['trend_return']==0
    assert ctx[244]['volatility_ratio']==1. and ctx[244]['background']=='1|1'
    flat = [{**r,'high':100.,'low':100.} for r in rows]
    assert contexts(flat)[244]['volatility_ratio'] is None
    assert not simple_signals(flat,contexts(flat),60)[0]


def test_context_today_does_not_change_reference_or_atr():
    rows = prices()
    rows[245].update(high=500.,low=1.,close=105.)
    x = contexts(rows)[245]
    assert x['atr20']==2. and x['level']==101.
    assert x['trend_return']==pytest.approx(.05)
    assert contexts(rows[:246])[-1]==x


def test_daily_gap_in_tr_and_out_of_order():
    rows = prices()
    for r in rows[240:244]:
        r.update(open=105.,high=106.,low=104.,close=105.)
    assert contexts(rows)[244]['atr20']==pytest.approx((19*2+6)/20)
    rows[1],rows[2] = rows[2],rows[1]
    with pytest.raises(ValueError,match='ordered'):
        contexts(rows)


def test_breakout_not_retest_and_first_later_retest():
    rows,ctx = shape()
    ee,cc = simple_signals(rows,ctx,60)
    assert len(ee)==len(cc)==1 and ee[0]['signal_index']==2
    assert cc[0]['status']=='triggered'
    assert reference_candidates(rows,ctx,60,SPEC)==(cc,[2])
    assert not simple_signals(rows[:2],ctx[:2],60)[0]


@pytest.mark.parametrize('low,status',[(99.75,'triggered'),(100.25,'triggered'),(99.749,'failed'),(100.251,'pending_at_end')])
def test_retest_tolerance_boundaries(low,status):
    rows,ctx = shape(low=(100.,101.,low))
    ee,cc = simple_signals(rows,ctx,60)
    assert cc[0]['status']==status
    assert bool(ee)==(status=='triggered')


@pytest.mark.parametrize('closing,status',[(100.,'failed'),(99.9,'failed'),(102.,'pending_at_end'),(102.1,'pending_at_end')])
def test_close_must_hold_and_fall(closing,status):
    rows,ctx = shape(close=(100.,102.,closing))
    assert simple_signals(rows,ctx,60)[1][0]['status']==status


def test_breakout_equality_and_no_missing_atr():
    rows,ctx = shape(close=(100.,100.,100.))
    assert simple_signals(rows,ctx,60)==([],[])
    rows,ctx = shape()
    for c in ctx:
        c['atr20'] = None
    assert simple_signals(rows,ctx,60)==([],[])


def test_frozen_reference_and_one_candidate_per_day():
    rows,ctx = shape(close=(100.,102.,99.,103.),low=(100.,101.,99.,102.))
    assert len(simple_signals(rows,ctx,60)[1])==1
    rows,ctx = shape()
    ctx[2].update(level=500.,atr20=100.)
    ee,_ = simple_signals(rows,ctx,60)
    assert ee[0]['level']==100. and ee[0]['tolerance']==.25


@pytest.mark.parametrize('last_low,expected',[(100.,'triggered'),(101.,'expired')])
def test_wait_window_includes_fourth_bar(last_low,expected):
    rows,ctx = shape(close=(100.,102.,102.,102.,102.,101.5,101.),low=(100.,101.,101.,101.,101.,last_low,100.))
    ee,cc = simple_signals(rows,ctx,60)
    assert cc[0]['end_index']==5 and cc[0]['status']==expected
    assert [e['signal_index'] for e in ee]==([5] if expected=='triggered' else [])
    assert reference_candidates(rows,ctx,60,SPEC)==(cc,[e['signal_index'] for e in ee])


def test_calendar_gap_does_not_consume_wait_bars():
    rows,ctx = shape()
    rows[1].update(date='2024-01-05',time='2024-01-05 15:00:00')
    rows[2].update(date='2024-01-08',time='2024-01-08 10:30:00')
    for r,c in zip(rows,ctx):
        c['time']=r['time']
    assert simple_signals(rows,ctx,60)[0][0]['signal_index']==2


def test_context_alignment_and_unapproved_frequency():
    rows,ctx = shape()
    with pytest.raises(ValueError,match='alignment'):
        simple_signals(rows,ctx[:-1],60)
    with pytest.raises(ValueError,match='frequency'):
        simple_signals(rows,ctx,15)


def test_initialization_does_not_start_cooldown_and_boundary():
    rows = prices()
    days = sorted({r['date'] for r in rows})
    ee = [event(rows,i) for i in (0,4,80,84)]
    ee[0]['evaluation']=False
    assert [e['signal_index'] for e in select_events(ee,days,'B3',True)]==[4,84]
    short,ctx = shape()
    assert not simple_signals(short,ctx,60,replace(SPEC,evaluation_start='2025-01-01'))[0][0]['evaluation']


def test_prefix_and_future_perturbation():
    rows = prices()
    rows[281].update(close=103.,high=104.,low=102.)
    rows[282].update(close=102.,high=103.,low=101.)
    ctx=contexts(rows)
    ee,_=simple_signals(rows,ctx,60)
    altered=deepcopy(rows)
    for r in altered[283:]:
        for key in ('open','high','low','close'):
            r[key]*=4
    assert contexts(altered)[:283]==ctx[:283]
    assert [e for e in ee if e['signal_index']<283]==simple_signals(rows[:283],ctx[:283],60)[0]
    assert [e for e in simple_signals(altered,contexts(altered),60)[0] if e['signal_index']<283]==simple_signals(rows[:283],ctx[:283],60)[0]


def mini_labels():
    rows=prices(4)
    days=sorted({r['date'] for r in rows})
    ll=label_rows(rows,days,1)
    for i,r in ll.items():
        r.update(stratum='common' if i<8 else 'other',q=i/100,up=float(i%2),q_up=float(i>0))
    return rows,days,ll


def test_support_is_not_a_signal_filter_or_cooldown_replacement():
    rows,_,ll=mini_labels()
    ee={'simple':[event(rows,0),event(rows,8)],'chan':[event(rows,1)]}
    out,rr,_=evaluate(ee,ll,replace(SPEC,min_baseline_bars=5))
    assert out['simple']['all']['n']==2 and out['simple']['supported']['n']==1
    assert out['simple']['unsupported_scored']==1 and len(rr['simple'])==1
    assert out['direct']['simple_n']==out['direct']['chan_n']==1


def test_common_target_weights_are_shared_not_separate_means():
    def rec(s,q):
        return dict(stratum=s,q=q,up=float(q>0),date='2024-01-01')
    simple=[rec('a',0),rec('b',10),rec('b',10),rec('b',10)]
    chan=[rec('a',1),rec('a',1),rec('a',1),rec('b',11)]
    result=common_comparison(simple,chan)
    assert result['weights']=={'a':.5,'b':.5}
    assert result['delta_q']==1. and not result['sample_gate']
    assert common_comparison(simple,[])['delta_q'] is None


def test_empty_methods_and_tail_exclusion():
    rows,days,ll=mini_labels()
    ee={'simple':[event(rows,15)],'chan':[]}
    out,_,_=evaluate(ee,ll)
    assert out['simple']['all']['tail_excluded']==1 and out['simple']['all']['n']==0
    assert out['direct']['strata']==0
    with pytest.raises(ValueError,match='missing'):
        matched_labels(ll,[{'background':None} for r in rows])
    assert days[-1]=='2024-01-04'


def test_bootstrap_identical_methods_zero_delta_and_keeps_full_calendar():
    rows,days,ll=mini_labels()
    # Both methods occur every scorable date, but some dates/strata are unsupported.
    ee={'simple':[event(rows,i) for i in (0,4)],'chan':[event(rows,i) for i in (0,4)]}
    spec=replace(SPEC,min_baseline_bars=5,repetitions=100,blocks=(1,))
    _,rr,eligible=evaluate(ee,ll,spec)
    result=intervals(rr,eligible,ll,days,spec)['1']
    assert result['full_calendar_days']==3
    if result['comparisons']['direct']['q'] is not None:
        assert result['comparisons']['direct']['q']['simultaneous']==[0.,0.]
    assert result['comparisons']['simple']==result['comparisons']['chan']


def test_missing_common_cells_are_not_zero_draws():
    rows,days,ll=mini_labels()
    for r in ll.values():
        r['stratum']='same'
    ee={'simple':[event(rows,0)],'chan':[event(rows,8)]}
    spec=replace(SPEC,min_baseline_bars=1,repetitions=100,blocks=(1,))
    _,rr,eligible=evaluate(ee,ll,spec)
    direct=intervals(rr,eligible,ll,days,spec)['1']['comparisons']['direct']
    assert direct['missing_repetitions']>10
    assert direct['q'] is None


def test_pairs_tie_early_unique_and_distance_inclusive():
    rows=prices()
    ss=[event(rows,0,'s0'),event(rows,8,'s8')]
    cc=[event(rows,4,'c4'),event(rows,5,'c5'),event(rows,9,'c9')]
    result=nearest_pairs(ss,cc,rows,60)
    assert [(p['simple_id'],p['chan_id']) for p in result['pairs']]==[('s0','c4'),('s8','c5')]
    assert result['unmatched_chan']==['c9']
    assert result['pairs'][0]['chan_minus_simple_bars']==4


def test_sensitivity_deletes_baseline_dates_and_preserves_events():
    rows,_,ll=mini_labels()
    ee={'simple':[event(rows,0),event(rows,8)],'chan':[event(rows,1)]}
    before=deepcopy(ee)
    out=sensitivity(ee,ll,replace(SPEC,min_baseline_bars=1))
    assert out['date']['2024-01-01']['simple']['all']['n']==1
    assert out['year']['2024']['chan']['all']['n']==0
    assert ee==before


def test_sql_and_reference_validation_on_synthetic_prices():
    rows=prices()
    rows[281].update(open=103.,close=103.,high=104.,low=102.)
    rows[282].update(open=102.,close=102.,high=103.,low=101.)
    days=sorted({r['date'] for r in rows})
    spec=replace(SPEC,evaluation_start=days[65],prefix_dates=(days[70],days[75]))
    ctx=contexts(rows,spec)
    ss,cc=simple_signals(rows,ctx,60,spec)
    assert ss
    ll=matched_labels(label_rows(rows,days,1,spec),ctx)
    methods={'simple':ss,'chan':ss}
    stats,_,_=evaluate(methods,ll,spec)
    result=verify_cell(rows,days,ctx,ss,cc,ll,methods,{'modes':{'cooldown':stats}},60,spec)
    assert result['sql_label_paths']==len(ll)
    assert result['independent_simple_triggers']==len(ss)


def test_modified_spec_and_existing_output_rejected_before_input(tmp_path,monkeypatch):
    def forbidden():
        pytest.fail('must not read input')
    monkeypatch.setattr('scripts.research.index_market.chan.minute_comparison.authenticated_input',forbidden)
    with pytest.raises(ValueError,match='unapproved'):
        execute(tmp_path/'new',replace(SPEC,tolerance_atr=.3))
    with pytest.raises(ValueError,match='new child'):
        execute(tmp_path)


def test_no_overlap_means_no_direct_interval():
    rows,days,ll=mini_labels()
    ee={'simple':[event(rows,0)],'chan':[event(rows,8)]}
    spec=replace(SPEC,min_baseline_bars=1,repetitions=100,blocks=(1,))
    stats,rr,eligible=evaluate(ee,ll,spec)
    assert stats['direct']['strata']==0
    out=intervals(rr,eligible,ll,days,spec)['1']['comparisons']['direct']
    assert out['valid_repetitions']==0 and out['q'] is None
    assert np.isfinite(stats['simple']['all']['q'])
