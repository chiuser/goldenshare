import copy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval, as_interval
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS
from scripts.research.index_market.tests.test_xxm_key_point_forecast import frozen, endpoints, replay
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection

from src.biz.services.wealth.market.index_detail_xxm.forecast_text import (
    build_display_context, make_display, reference_band, select_display, price_text,
)
ROOT=Path(__file__).resolve().parents[4]
PERIODS=('day','m60','m90','m120')

def clocks(period):
 return ('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in ENDPOINTS[int(period[1:])])

def payload(period='day'):
 return json.loads((ROOT/'reports/xxm_forecast_range_implementation_20261014'/f'http_latest_{period}.json').read_text())

def context(entry=(3733,3869),target=(3716,3885)):
 def band(points):return dict(reason=None,priceRange=Interval(*points,True,True).json())
 return dict(entry=band(entry),target=band(target))

def test_approved_copy_retains_protected_failures_without_mutating_full_math():
 value=payload();before=copy.deepcopy(value);ctx=context()
 text=make_display(value,'day',value['computedThrough'],'LATEST',ctx)['conditionsText']
 assert all(s in text for s in ('钝化触发','未触发','推算失效','结构成立','3764.1546','3764.1548～3950.9680','3950.9681','3793～3937'))
 assert not any(s in text for s in ('3457','4112','前置收盘','目标收盘','充分条件','差异举例','临界点'))
 assert value==before and len(value['examples'])==3 and value['activation']['ranges'][0]['priceRange']['lower']<3500


def test_far_boundary_is_restored_when_it_becomes_near_and_protection_is_not_filtered():
 v=payload();ctx=context(entry=(3400,3900));selected=select_display(v,ctx)
 assert any(e['reason']=='DIF_NOT_DIVERGENT' for e in selected['exclusions'])
 text=make_display(v,'day',v['computedThrough'],'LATEST',ctx)['conditionsText']
 assert '3457.7025～3764.1546' in text and '3457.7024' in text and '3950.9681' in text


def test_far_math_target_keeps_raw_facts_but_does_not_announce_another_date():
 v=payload('m90');before=copy.deepcopy(v);ctx=context(entry=(3730,3860),target=(3730,3860))
 display=make_display(v,'m90',v['computedThrough'],'LATEST',ctx)
 assert display['statusLabel']=='近期暂无条件' and '11:00' in display['targetText'] and '14:00' not in display['targetText']
 assert '未触发' in display['conditionsText'] and '推算失效' in display['conditionsText']
 assert '3960.0873' not in display['conditionsText'] and '4305' not in display['conditionsText']
 assert v==before and v['status']=='CONDITIONAL_ENTRY' and v['targetEndpoint'].endswith('14:00:00+08:00')


def test_partial_reference_has_explicit_dated_precondition_not_a_global_threshold():
 v=payload('m90');ctx=context(entry=(3950,4010),target=(3660,3820))
 text=make_display(v,'m90',v['computedThrough'],'LATEST',ctx)['conditionsText']
 assert '仅当10/15 11:00 收盘在3960.0873～3988.5429点' in text
 assert '3960.0873～3988.5429' in text and '3988.5431～4305.0409' in text
 assert '3988.5429～3988.5431' not in text


@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('span',[1,2,5])
def test_matching_endpoint_cohort_quantile_and_causal_prefix(period,span):
 bars=frozen(period);through=bars[-1].time;target=endpoints(period,through)[span-1]
 actual=reference_band(bars,period,through,target,span,clocks(period),lambda:None)
 matching=[i for i in range(span,len(bars)) if period=='day' or bars[i].time[11:16]==target[11:16]][-60:]
 expected=sorted(abs(bars[i].close/bars[i-span].close-1) for i in matching)[56]
 assert actual['samples']==60 and actual['rank']==57 and actual['q']==expected
 future=replace(bars[-1],time='2999-01-01' if period=='day' else '2999-01-01T15:00:00+08:00',close=999999.)
 assert reference_band((*bars,future),period,through,target,span,clocks(period),lambda:None)==actual


@pytest.mark.parametrize('period',PERIODS)
def test_short_history_no_scale_does_not_invent_confident_points(period):
 bars=frozen(period)[-59:];target=endpoints(period,bars[-1].time)[0]
 value=reference_band(bars,period,bars[-1].time,target,1,clocks(period),lambda:None)
 assert value['reason']=='INSUFFICIENT_SAMPLES' and value['samples']<60 and 'priceRange' not in value


@pytest.mark.parametrize('period',['m60','m90','m120'])
def test_invalid_target_clock_or_missing_slot_cannot_be_used(period):
 bars=frozen(period);through=bars[-1].time
 assert reference_band(bars,period,through,'2026-10-14T11:07:00+08:00',1,clocks(period),lambda:None)['reason']=='ENDPOINT_MISMATCH'
 # Remove the bar just before a matching final endpoint: no silent use of a different span.
 broken=(*bars[:-2],bars[-1]);target=endpoints(period,through)[len(clocks(period))-1]
 assert reference_band(broken,period,through,target,len(clocks(period)),clocks(period),lambda:None)['reason']=='ENDPOINT_MISMATCH'


def test_nonpositive_or_nonfinite_price_is_not_a_fallback_scale():
 bars=frozen('day');through=bars[-1].time;target=endpoints('day',through)[0]
 for close in [0.,-1.,float('nan'),float('inf')]:
  bad=(*bars[:-1],replace(bars[-1],close=close))
  assert reference_band(bad,'day',through,target,1,clocks('day'),lambda:None)['reason']=='INVALID_PRICE'


def test_integer_rounding_falls_back_without_expanding_a_narrow_interval():
 assert price_text(Interval(3792.4427,3937.1707),(0,2,4))=='3793～3937点'
 assert price_text(Interval(100.101,100.105),(0,2,4))=='100.1011～100.1049点'
 assert price_text(Interval(100.000001,100.000002),(0,2,4)) is None


def test_budget_check_is_not_skipped_by_statistics_or_selection():
 def reject():raise TimeoutError('deadline')
 bars=frozen('day');v=payload()
 with pytest.raises(TimeoutError,match='deadline'):build_display_context(bars,'day',bars[-1].time,v,clocks('day'),reject)
 with pytest.raises(TimeoutError,match='deadline'):select_display(v,context(),reject)


@pytest.mark.parametrize('status',['ENTRY_ONLY','PRECISION_PENDING','DELAYED','EMPTY','CONFIRMED','NO_CANDIDATE'])
def test_existing_states_remain_distinct_without_fabricated_structure_price(status):
 v=payload();v['status']=status;v['targetEndpoint']=None;v['barsAhead']=None;v['commonConditions']=[]
 if status in ('CONFIRMED','NO_CANDIDATE','DELAYED','EMPTY'):v['activation']=None
 v.update(confirmedAt='2026-10-14',confirmedDirection='BOTTOM')
 d=make_display(v,'day',v['computedThrough'],'LATEST',context())
 assert '结构成立：' not in d['conditionsText'] and '3793' not in d['conditionsText']
 assert '临界点' not in d['conditionsText']


def test_actual_dulling_keeps_cancellation_and_zero_rule_but_not_blanket_color_flip_failure():
 v=payload();v.update(status='READY',activation=None,ordinaryState='DULL')
 for group in v['commonConditions']:group['entryDomain']=None;group['entryRangeIds']=[]
 d=make_display(v,'day',v['computedThrough'],'LATEST',dict(entry=None,target=context()['target']))
 assert '当前底钝化有效' in d['conditionsText'] and '钝化消失或出现零柱' in d['conditionsText']
 assert 'MACD柱色改变' not in d['conditionsText'] and '先形成' not in d['conditionsText']


def test_reference_change_boundary_cannot_be_omitted_when_only_one_range_is_near():
 v=payload('m90');ctx=context(entry=(3950,3970),target=(3660,3820))
 d=make_display(v,'m90',v['computedThrough'],'LATEST',ctx)
 assert '钝化触发：10/15 11:00 收盘3960.0873～3988.5429点' in d['conditionsText']
 assert '4305' not in d['conditionsText']


def test_exact_reference_band_touch_obeys_original_open_boundary():
 v=payload();raw=v['activation']['ranges'][0]['priceRange'];edge=raw['upper']
 ctx=context();ctx['entry']['priceRange']=Interval(edge,edge,True,True).json()
 assert not select_display(v,ctx)['selected']
 ctx['entry']['priceRange']=Interval(edge-.001,edge-.001,True,True).json()
 assert select_display(v,ctx)['selected']


def test_no_common_condition_does_not_copy_example_prices_or_change_math_target():
 v=payload();v['commonConditions']=[];before=copy.deepcopy(v)
 d=make_display(v,'day',v['computedThrough'],'LATEST',context())
 assert '结构条件待10/15 收盘后更新' in d['conditionsText']
 assert '3793' not in d['conditionsText'] and '差异举例' not in d['conditionsText'] and v==before


def test_dulling_without_a_structure_in_horizon_retains_its_actual_state_and_invalidation():
 v=payload();v.update(status='NO_CANDIDATE',reasonCode='NO_CONFIRMATION_IN_HORIZON',activation=None,targetEndpoint=None,barsAhead=None,commonConditions=[])
 d=make_display(v,'day',v['computedThrough'],'LATEST',dict(entry=None,target=None))
 assert d['statusLabel']=='底钝化有效' and '后续结构时点暂未找到' in d['conditionsText']
 assert '钝化消失或出现零柱' in d['conditionsText'] and '结构成立：' not in d['conditionsText']


def test_partial_entry_domain_remains_explicit_even_when_it_covers_the_near_band():
 v=payload();raw=v['activation']['ranges'][0]['priceRange']
 domain=Interval(3600,raw['upper'],True,raw['upperInclusive']).json()
 for group in v['commonConditions']:group['entryDomain']=domain
 d=make_display(v,'day',v['computedThrough'],'LATEST',context(entry=(3700,3800)))
 assert '结构成立：仅当10/15 收盘在3600.0001～3764.1546点' in d['conditionsText']
 assert '结构成立：若底钝化形成并保持有效' not in d['conditionsText']


@pytest.mark.parametrize('status',['NO_CANDIDATE','PRECISION_PENDING'])
def test_waiting_without_ranges_never_claims_actual_dulling(status):
 v=json.loads((ROOT/'reports/xxm_same_segment_a1_implementation_20261016/api/api_forecast_9_m120.json').read_text())
 v.update(status=status,reasonCode='NO_CONFIRMATION_IN_HORIZON',activation=None,targetEndpoint=None,barsAhead=None,
          commonConditions=[],relations=[],targetEntryRanges=[],targetEntryExclusions=[],examples=[],assumption=None)
 d=make_display(v,'m120',v['computedThrough'],'REPLAY',dict(entry=None,target=None))
 assert d['statusLabel']=='结构消失，待重新钝化'
 assert '当前未重新形成底钝化' in d['conditionsText'] and '钝化有效' not in d['conditionsText']
 assert '柱色改变或出现零柱' in d['conditionsText']
