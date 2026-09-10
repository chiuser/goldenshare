"""F1 tests use synthetic prices only; no Lake, external source or replay."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from scripts.research.index_market.chan.minute_background import (
    SPEC, background, background_intervals, block_weights, comparison, evaluate,
    execute, independent_background, split_events,
)
from scripts.research.index_market.chan.minute_score import select_events


def prices():
    rows = []
    for d in range(24):
        day = str(date(2024,1,1)+timedelta(days=d))
        for slot in ('10:30:00','11:30:00','14:00:00','15:00:00'):
            rows.append(dict(date=day, time=day+' '+slot, open=100., high=101., low=99., close=100.))
    return rows


def event(rows, i):
    return dict(event_id=str(i), signal_index=i, signal_time=rows[i]['time'], evaluation=True, group='B3')


def test_golden_uses_previous_complete_days():
    rows = prices()
    actual = background(rows)[85]
    assert actual['atr20']==2. and actual['reference_high']==101.
    assert actual['drawdown_atr']==.5 and actual['keep']
    reference = independent_background(rows,85)
    for key, value in reference.items():
        assert actual[key]==value


@pytest.mark.parametrize('close,keep', [(97.,True),(96.999,False),(97.001,True)])
def test_threshold_boundary(close,keep):
    rows = prices()
    rows[85].update(low=close, close=close)
    actual = background(rows)[85]
    assert actual['keep'] is keep
    assert actual['atr20']==2.  # today's large range must not inflate denominator


def test_gap_in_daily_tr():
    rows = prices()
    for r in rows[80:84]:
        r.update(open=105.,high=106.,low=104.,close=105.)
    result = background(rows)[85]
    assert result['atr20']==pytest.approx((19*2+6)/20)
    assert result['reference_high']==106.


def test_current_high_included_but_future_today_high_excluded():
    rows = prices()
    rows[85].update(high=103., close=103.)
    rows[86].update(high=999., close=999.)
    current = background(rows)[85]
    assert current['reference_high']==103. and current['drawdown_atr']==0.
    assert current==background(rows[:86])[-1]


def test_warmup_requires_21_completed_days():
    result = background(prices())
    assert result[83]['drawdown_atr'] is None
    assert result[84]['drawdown_atr'] is not None


def test_zero_atr_is_missing_and_event_fails():
    rows = prices()
    for r in rows:
        r.update(high=100., low=100., close=100.)
    contexts = background(rows)
    assert contexts[85]['atr20']==0. and contexts[85]['drawdown_atr'] is None
    with pytest.raises(ValueError, match='missing'):
        split_events([event(rows,85)],contexts)


def test_future_perturbation_prefix_identical():
    rows = prices()
    changed = deepcopy(rows)
    for r in changed[86:]:
        for key in ('open','high','low','close'):
            r[key] *= 5
    assert background(rows)[:86]==background(changed)[:86]


def test_out_of_order_rejected():
    rows = prices()
    rows[1], rows[2] = rows[2], rows[1]
    with pytest.raises(ValueError, match='ordered'):
        background(rows)


def test_skip_does_not_replace_original_cooldown_slot():
    rows = prices()
    days = sorted({r['date'] for r in rows})
    events = [event(rows,0), event(rows,4), event(rows,80)]
    contexts = [dict(time=r['time'], drawdown_atr=3., keep=False) for r in rows]
    contexts[4].update(drawdown_atr=1.,keep=True)
    contexts[80].update(drawdown_atr=1.,keep=True)
    original = select_events(events,days,'B3',True)
    kept,removed = split_events(original,contexts)
    assert [r['event_id'] for r in kept]==['80']
    assert [r['event_id'] for r in removed]==['0']
    assert '4' not in {r['event_id'] for r in kept}


def test_conditional_and_fixed_opportunity_denominators():
    records = [dict(q=.1, keep=True),dict(q=.2,keep=False),dict(q=-.4,keep=False),dict(q=0.,keep=False)]
    result = comparison(records)
    assert result['before']['q']==pytest.approx(-.025)
    assert result['after']['q']==.1
    assert result['fixed_opportunity_q']==.025
    assert result['fixed_opportunity_delta']==pytest.approx(.05)
    assert result['missed_positive_q_sum']==.2
    assert result['avoided_negative_q_sum']==.4
    assert result['removed']['flat']==1


def test_empty_and_all_rejected_cases():
    assert comparison([])['after']['q'] is None
    result = comparison([dict(q=.1,keep=False)])
    assert result['after']['q'] is None
    assert result['fixed_opportunity_q']==0.
    assert result['fixed_opportunity_delta']==-.1
    assert background_intervals([],{}, {}, [])=={}


def label(index, q):
    return dict(index=index, day=index, date=f'2024-01-{index+1:02d}',stratum='2024|11:30:00',
                q=q, r=q, up=float(q>0),q_up=float(q>0),mae=-.01,mfe=.01)


def test_baseline_is_background_only_not_all_market():
    labels = {i:label(i,q) for i,q in enumerate([.04,.02,-.9])}
    contexts = [dict(time=str(i),keep=i!=2,drawdown_atr=1. if i!=2 else 3.,atr20=1.,reference_high=100.) for i in range(3)]
    events = [dict(event_id='e',signal_index=0,signal_time='0')]
    result,records,scored = evaluate(events,labels,{i:r for i,r in labels.items() if i!=2},contexts)
    assert result['after']['baseline_q']==pytest.approx(.03)
    assert result['after']['lift_q']==pytest.approx(.01)
    assert len(records)==len(scored)==1


def test_block_weights_preserve_full_days_including_empty_days():
    # Days 0 and 2 could have eligible bars; day 1 must still be in the grid.
    w = block_weights([[0,1,2],[3,4]], 5, 60, 10, np.random.default_rng(1))
    assert np.all(w==1)
    assert np.all(w.sum(axis=1)==5)


def test_block_interval_support_does_not_compress_filtered_dates():
    labels = {i:label(i,q) for i,q in enumerate([.01,-.9,.03,-.8])}
    eligible = {0:labels[0],2:labels[2]}
    spec = replace(SPEC, blocks=(60,), repetitions=100)
    result = background_intervals([dict(labels[0])],eligible,labels,[r['date'] for r in labels.values()],spec)['60']
    assert result['full_calendar_days']==4 and result['eligible_days']==2
    assert result['lift_q']['ci95']==pytest.approx([-.01,-.01])
    assert result['valid_repetitions']==100


@pytest.mark.parametrize('patch', [dict(max_drawdown_atr=1.5),dict(lookback_days=10),dict(cooldown_days=10),dict(omit_year='2025')])
def test_execution_rejects_unapproved_spec_before_io(tmp_path,patch):
    with pytest.raises(ValueError, match='unapproved'):
        execute(tmp_path/'result',replace(SPEC,**patch))
