from copy import deepcopy
from dataclasses import replace

import pytest

from scripts.research.index_market.chan.stock_opportunity_filters import SPEC, features, passes
from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.tests.test_stock_opportunity import rows


def event(data,i=45,anchor=44):
    return dict(event_id='test',group='B1',signal_index=i,anchor_index=anchor,
                signal_time=data[i]['time'],sure=True,buy=True)


def test_exact_rolling_indices_and_gap_atr():
    data=rows(60)
    f=features(data,event(data))
    assert f['ma']==pytest.approx(sum(101+j for j in range(6,46))/40)
    assert f['previous_ma']==pytest.approx(sum(101+j for j in range(1,41))/40)
    assert f['atr']==3 and f['trend'] and f['near']
    data[45].update(high=200,low=190,close=195)
    assert features(data,event(data))['atr']==pytest.approx((19*3+55)/20)


def test_threshold_equality_and_negative_distance():
    data=rows(60)
    data[10]['low']=140  # Outside ATR window; distance at t45 = 6 = 2*ATR.
    assert features(data,event(data,anchor=10))['near']
    data[10]['low']=139.99
    assert not features(data,event(data,anchor=10))['near']
    data[10]['low']=147
    assert features(data,event(data,anchor=10))['reason']=='negative_distance'


def test_zero_atr_flat_ma_and_insufficient_history():
    data=rows(60)
    for r in data:
        r.update(open=100,high=100,low=100,close=100)
    f=features(data,event(data))
    assert not f['near'] and not f['trend'] and f['reason']=='zero_atr'
    assert features(data,event(data,i=42,anchor=41))['reason']=='insufficient_history'


def test_prefix_future_and_anchor_rejection():
    data=rows(60)
    e=event(data)
    assert features(data,e)==features(data[:46],e)
    other=deepcopy(data)
    for r in other[46:]:
        r.update(close=9999,low=1,high=99999)
    assert features(data,e)==features(other,e)
    with pytest.raises(ValueError):
        features(data,event(data,anchor=46))


@pytest.mark.parametrize('trend,near',[(True,True),(True,False),(False,True),(False,False)])
def test_four_groups(trend,near):
    f=dict(trend=trend,near=near)
    assert [passes(f,v) for v in SPEC.variants]==[True,trend,near,trend and near]
    with pytest.raises(ValueError):
        passes(f,'tuned')


def test_filter_then_dedup_and_empty_groups():
    data=rows(60)
    e=event(data)
    e2=dict(e,event_id='other',anchor_index=0)
    selected=[x for x in (e,e2) if passes(features(data,x),'near')]
    assert selected==[e]
    spec=replace(base.SPEC,warmup_days=2,bars_per_day=1,horizons=(5,))
    r=base.evaluate(data,selected,spec)
    assert r['summary'][0]['signals']['n']==1
    empty=base.evaluate(data,[],spec)
    assert all(s['signals']=={'n':0} and s['matched']=={} for s in empty['summary'])
    assert empty['recall']['early_count']==0
    assert [(x['entry_index'],x['exit_index']) for x in r['recall']['rallies']]==[(x['entry_index'],x['exit_index']) for x in empty['recall']['rallies']]
