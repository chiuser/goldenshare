"""P3 step 2: literal M/PF expectations, no market files or HTTP replay.

M1-M5 and the T/B/AB prefixes are transcribed from LLD 5.4.4/14.2.
Dispatch substitutes below test orchestration only; actual mathematical results
are separately checked against the literal original-kernel outcomes.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib
import json
import math
import time

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, precheck_next_bar
from src.biz.services.wealth.market.index_detail_xxm import forecast_detector as detector
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval, as_interval
from src.biz.services.wealth.market.index_detail_xxm.forecast_next import solve_active_reference
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import ForecastSpec, FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from src.biz.services.wealth.market.index_detail_xxm.types import (
    XxmBar, ForecastConditionDraft, ForecastKernelResult, ReferenceForecast,
)

engine = importlib.import_module('src.biz.services.wealth.market.index_detail_xxm.forecast')
next_solver = importlib.import_module('src.biz.services.wealth.market.index_detail_xxm.forecast_next')
PERIODS = ('day', 'm60', 'm90', 'm120')
DATES = ('2023-01-03', '2023-01-04', '2023-01-05', '2023-01-06',
         '2023-01-09', '2023-01-10', '2023-01-11', '2023-01-12', '2023-01-13')
M1 = ((100,-60,-2),(110,0,2),(90,-50,-2),(100,0,2),(89,-15,-30),(88,-14,-28))
M2 = ((100,60,2),(90,0,-2),(110,50,2),(100,0,-2),(111,15,30),(112,14,28))
M3 = ((70,10,2),(90,0,-2),(100,2,8))
T = ((100,200,2),(90,0,-2),(101,100,2),(102,100,2))
B = ((100,-200,-2),(110,0,2),(99,-100,-2),(98,-100,-2))
TS, BS = T+((103,99,2),), B+((97,-99,-2),)
ABTD = ((100,300,2),(90,0,-2),(120,200,2),(110,0,-2),(130,100,2),(131,100,2))
ABBD = ((100,-300,-2),(110,0,2),(80,-200,-2),(90,0,2),(70,-100,-2),(69,-100,-2))


def stamp(period, index):
    return DATES[index] + ('' if period == 'day' else 'T15:00:00+08:00')


def calculator(values, period='day'):
    c = XxmCalculator(period=period, source_identity='next-bar-independent-literals')
    for index, (close, dif, hist) in enumerate(values):
        c.step(XxmBar(stamp(period,index), close, dif, dif-hist/2, hist))
    return c


def run(c, projection):
    prepared = precheck_next_bar(c, lambda:None)
    return forecast(c, projection, stamp(c.period,c.processed), lambda:None, prepared=prepared)


def outcomes_at(result, price):
    return {item.outcome for item in result.conditions
            if any(as_interval(value).contains(price) for value in item.price_ranges)}


def reference_result(outcome, role, region, *, relationship=True, pending=(), relation_pending=()):
    # Independent dispatch fixture, not an expected mathematical computation.
    price = dict(region.json(),displayLower=None,displayUpper=None)
    draft = ForecastConditionDraft(outcome, role, (price,), ())
    return ReferenceForecast((draft,), (region,) if relationship else (), tuple(relation_pending),tuple(pending))


def empty_result(*, pending=(), relationship_pending=()):
    return ReferenceForecast((),(),tuple(relationship_pending),tuple(pending))


@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('values,projection,zero,flip,other',[
    (M1,ProjectionState(13,27,0),175.5,176.,'STRUCTURE_FORMED'),
    (M2,ProjectionState(187,173,0),24.5,24.,'STRUCTURE_FORMED'),
])
def test_pf01_m1_m2_zero_and_actual_flip(period,values,projection,zero,flip,other):
    c=calculator(values,period); before=c.snapshot()
    result=run(c,projection)
    assert result.status=='READY' and result.bars_ahead==1
    assert result.selected_reference=='NEAR' and not result.far_evaluated
    assert outcomes_at(result,zero)=={other}
    assert outcomes_at(result,flip)=={'STRUCTURE_FORMED_AND_FOLLOWING'}
    actual=detector.evaluate_next_at_price(c,projection,zero,stamp(period,len(values)),'NEAR',lambda:None)
    assert actual['outcome']==other and actual['reference']==c.reference.reference()
    assert c.snapshot()==before


@pytest.mark.parametrize('period',PERIODS)
def test_pf07_m3_first_activation_never_same_bar_structure(period):
    c=calculator(M3,period); result=run(c,ProjectionState(102,100,-2))
    assert outcomes_at(result,100.)=={'DULL_FORMED'}
    assert {condition.outcome for condition in result.conditions}=={'DULL_FORMED'}
    assert result.target_endpoint==stamp(period,3) and result.bars_ahead==1


@pytest.mark.parametrize('values,reason',[ ((), 'ZERO_WAVE'), (((100,0,0),),'ZERO_WAVE'),
    (((100,2,2),),'NO_REFERENCE'),
    (((100,10,2),(110,0,-2),(101,11,2)), 'NO_ENTRY_RANGE') ])
def test_pf02_static_without_projection_or_calendar(values,reason):
    c=calculator(values); prepared=precheck_next_bar(c,lambda:None)
    assert prepared.stop_reason==reason
    result=forecast(c,None,None,lambda:None,prepared=prepared)
    assert result.status=='NO_CANDIDATE' and result.reason_code==reason
    assert result.target_endpoint is None and result.bars_ahead is None
    assert not result.conditions and not result.far_evaluated


def test_pf02_current_price_and_nonpositive_top_dif_do_not_exclude_next_bar():
    c=calculator(((100,10,2),(90,0,-2),(99,-1,2)))
    assert c.state=='NONE' and c.previous.close<100 and c.previous.dif<0
    assert precheck_next_bar(c,lambda:None).stop_reason is None


@pytest.mark.parametrize('values,projection',[(M1,ProjectionState(13,27,0)),(ABTD,ProjectionState(102,100,0))])
def test_pf03_pf09_near_relationship_never_evaluates_far(values,projection,monkeypatch):
    c=calculator(values); far=list(reversed(c.history[c.wave.sign]))[1]
    original=XxmCalculator._current_reference_qualifies
    def only_near(self,bar,wave,reference,nearest):
        if reference==far: raise AssertionError('far eligibility was called')
        return original(self,bar,wave,reference,nearest)
    monkeypatch.setattr(XxmCalculator,'_current_reference_qualifies',only_near)
    result=run(c,projection)
    assert result.status=='READY' and not result.far_evaluated
    if values==ABTD:
        assert outcomes_at(result,3000.)=={'REFERENCE_INVALIDATED'}
        assert '近参照失效' in make_display(result,prepared=precheck_next_bar(c,lambda:None),
            period=c.period,through=c.previous.time,mode='LATEST',check=lambda:None)['conditionsText']


def test_pf03_none_candidate_outside_near_range_does_not_call_far_eligibility(monkeypatch):
    c=calculator(ABTD[:-1]); far=c.history[1][0]
    original=XxmCalculator._current_reference_qualifies
    def only_near(self,bar,wave,reference,nearest):
        if reference==far: raise AssertionError('far qualification during near verification')
        return original(self,bar,wave,reference,nearest)
    monkeypatch.setattr(XxmCalculator,'_current_reference_qualifies',only_near)
    result=run(c,ProjectionState(102,100,0))
    assert result.status=='READY' and not result.far_evaluated


@pytest.mark.parametrize('relation,pending,side_pending,expected,far_expected',[
    (True,False,True,'READY',False), (False,True,False,'PRECISION_PENDING',False),
    (False,False,True,'READY',True),
])
def test_pf05_dispatch_uses_relationship_uncertainty_only(monkeypatch,relation,pending,side_pending,expected,far_expected):
    c=calculator(ABTD); calls=[]; band=Interval(120.1,120.2,False,False)
    def solve(c,p,e,reference,role,check):
        calls.append(role)
        if role=='FAR': return reference_result('DULL_HELD',role,band)
        if relation: return reference_result('DULL_HELD',role,band,pending=(band,) if side_pending else ())
        return empty_result(pending=(band,) if side_pending or pending else (),
                            relationship_pending=(band,) if pending else ())
    monkeypatch.setattr(engine,'solve_active_reference',solve)
    result=run(c,ProjectionState(13,27,0))
    assert result.status==expected and result.far_evaluated==far_expected
    assert calls==(['NEAR','FAR'] if far_expected else ['NEAR'])
    assert result.selected_reference==('FAR' if far_expected else 'NEAR')


def test_pf04_none_b_previously_broken_uses_only_a(monkeypatch):
    c=calculator(((100,300,2),(90,0,-2),(120,200,2),(110,0,-2),(130,201,2)))
    assert c.state=='NONE'
    calls=[]
    def solve(c,p,e,reference,role,check):
        calls.append(role); return reference_result('DULL_FORMED',role,Interval(130.,140.,True,True))
    monkeypatch.setattr(engine,'solve_first_dull',solve)
    result=run(c,ProjectionState(13,27,0))
    assert calls==['FAR'] and result.nearest_decision['status']=='UNAVAILABLE'
    assert result.selected_reference=='FAR' and result.far_evaluated


def test_pf04_actual_same_bar_far_rescue_has_no_new_event():
    c=calculator(ABTD); before=c.snapshot(); projection=ProjectionState(500,186,0)
    result=run(c,projection)
    assert result.far_evaluated and result.selected_reference=='FAR'
    assert result.nearest_decision['status']=='NO_RANGE'
    assert outcomes_at(result,200.)=={'DULL_HELD'}
    actual=detector.evaluate_next_at_price(c,projection,200.,stamp('day',6),'FAR',lambda:None)
    assert actual=={'outcome':'DULL_HELD','reference':c.history[1][0].reference()}
    assert c.snapshot()==before


@pytest.mark.parametrize('values',[T,ABTD])
def test_pf04_no_rescue_reports_no_new_relationship_not_actual_disappearance(monkeypatch,values):
    c=calculator(values); calls=[]
    def solve(c,p,e,r,role,check): calls.append(role); return empty_result()
    monkeypatch.setattr(engine,'solve_active_reference',solve)
    result=run(c,ProjectionState(13,27,0))
    assert result.status=='NO_CANDIDATE' and result.reason_code=='NO_ENTRY_RANGE'
    assert result.target_endpoint is not None and result.bars_ahead==1
    assert not result.conditions and not result.precision_ranges
    assert calls==(['NEAR'] if values==T else ['NEAR','FAR'])
    text=make_display(result,prepared=precheck_next_bar(c,lambda:None),period='day',
        through=c.previous.time,mode='LATEST',check=lambda:None)['conditionsText']
    assert '这不表示当前真实钝化已经消失' in text


def test_pf06_far_broken_does_not_invalidate_near():
    values=((100,100,2),(90,0,-2),(120,200,2),(110,0,-2),(130,150,2),(131,150,2))
    c=calculator(values); result=run(c,ProjectionState(102,100,0))
    assert result.selected_reference=='NEAR' and not result.far_evaluated


def test_pf10_active_far_is_fixed_even_with_only_a_disappearance(monkeypatch):
    c=calculator(ABTD+((132,201,2),)); assert c.reference==c.history[1][0]
    calls=[]
    def solve(c,p,e,r,role,check):
        calls.append(role)
        return reference_result('SIGNAL_DISAPPEARED',role,Interval(300.,None,False,False),relationship=False)
    monkeypatch.setattr(engine,'solve_active_reference',solve)
    result=run(c,ProjectionState(13,27,0))
    assert result.status=='READY' and calls==['FAR'] and result.far_evaluated
    assert result.nearest_decision['status']=='NOT_EVALUATED'


@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('values,projection,cases',[
    (TS,ProjectionState(10099,10000,98),((10204.,'RETURNED_TO_DULL'),(10197.,'STRUCTURE_HELD'),(11470.,'SIGNAL_DISAPPEARED'))),
    (BS,ProjectionState(9901,10000,-98),((9796.,'RETURNED_TO_DULL'),(9803.,'STRUCTURE_HELD'),(8530.,'SIGNAL_DISAPPEARED'))),
])
def test_pf11_m5_assessing_structure_outcomes(period,values,projection,cases):
    c=calculator(values,period); before=c.snapshot(); result=run(c,projection)
    assert result.status=='READY' and result.nearest_decision['status']=='NOT_EVALUATED'
    for C,expected in cases:
        assert outcomes_at(result,C)=={expected}
        actual=detector.evaluate_next_at_price(c,projection,C,stamp(period,len(values)),'NEAR',lambda:None)
        assert actual['outcome']==expected and actual['reference']==c.reference.reference()
    assert c.snapshot()==before


def test_pf12_structure_never_rescues_far(monkeypatch):
    c=calculator(ABTD+((132,99,2),)); far=c.history[1][0]
    original=XxmCalculator._current_reference_qualifies
    def no_far(self,bar,wave,reference,nearest):
        if reference==far: raise AssertionError('structure rescue called')
        return original(self,bar,wave,reference,nearest)
    monkeypatch.setattr(XxmCalculator,'_current_reference_qualifies',no_far)
    value=detector.evaluate_next_at_price(c,ProjectionState(500,186,0),200.,stamp('day',7),'NEAR',lambda:None)
    assert value['outcome']=='SIGNAL_DISAPPEARED' and value['reference']==c.reference.reference()


@pytest.mark.parametrize('period',PERIODS)
def test_pf13_lock_has_no_new_structure_event_and_none_is_not_cancel(period):
    c=calculator(TS,period)
    value=detector.evaluate_next_at_price(c,ProjectionState(187,173,0),24.,stamp(period,5),'NEAR',lambda:None)
    assert value['outcome']=='STRUCTURE_FOLLOWING'
    # Same input, high DEA: actual flip and reference break must cancel first.
    value=detector.evaluate_next_at_price(c,ProjectionState(500,186,1000),200.,stamp(period,5),'NEAR',lambda:None)
    assert value['outcome']=='SIGNAL_DISAPPEARED'


def test_pf14_locked_history_starts_new_loop():
    c=calculator(TS+((104,98,-2),)); assert c.state=='NONE' and c.active_structure is None
    prepared=precheck_next_bar(c,lambda:None)
    # T's second row is a completed green segment: the new green loop must
    # use its price90/DIF0, rather than forget it or reopen the locked TOP.
    assert prepared.direction=='BOTTOM' and prepared.stop_reason is None
    assert prepared.references['nearest']=={
        'startTime':DATES[1],'endTime':DATES[1],'price':90,'dif':0,
        'priceAt':DATES[1],'difAt':DATES[1]}
    result=run(c,ProjectionState(102,100,50))
    assert outcomes_at(result,85.)=={'DULL_FORMED'}
    assert c.state=='NONE' and c.active_structure is None


def test_pf15_certified_point_mismatch_fails_without_mutating_real_progress(monkeypatch):
    c=calculator(M1); before=c.snapshot()
    monkeypatch.setattr(next_solver,'evaluate_next_at_price',lambda *a,**k:None)
    with pytest.raises(ValueError): run(c,ProjectionState(13,27,0))
    assert c.snapshot()==before


def test_pf15_display_integer_mismatch_reaches_its_own_failure(monkeypatch):
    c=calculator(M1); before=c.snapshot(); original=next_solver.evaluate_next_at_price
    reached=[]
    def evaluate(c,projection,C,endpoint,role,check):
        if C==2.:
            reached.append(C)
            return None  # M1's independently known first display integer.
        return original(c,projection,C,endpoint,role,check)
    monkeypatch.setattr(next_solver,'evaluate_next_at_price',evaluate)
    with pytest.raises(ValueError,match='Display integer'):
        run(c,ProjectionState(13,27,0))
    assert reached and c.snapshot()==before


@pytest.mark.parametrize('mutate',[
    lambda p:replace(p,direction='TOP'),lambda p:replace(p,stop_reason='NO_REFERENCE'),
    lambda p:replace(p,snapshot={**p.snapshot,'processed':999}),
])
def test_pf17_prepared_cannot_change_state_or_identity(mutate):
    c=calculator(M1); before=c.snapshot(); p=mutate(precheck_next_bar(c,lambda:None))
    with pytest.raises(ValueError): forecast(c,ProjectionState(13,27,0),stamp('day',6),lambda:None,prepared=p)
    assert c.snapshot()==before


@pytest.mark.parametrize('projection',[ProjectionState(math.nan,27,0),ProjectionState(True,27,0),
    ProjectionState(math.inf,27,0),ProjectionState(10**400,27,0)])
def test_pf17_nonfinite_original_projection_rejected(projection):
    with pytest.raises(ValueError): run(calculator(M1),projection)


def test_pf17_check_after_real_child_step_cleans_context_and_keeps_progress(monkeypatch):
    c=calculator(M1); prepared=precheck_next_bar(c,lambda:None); before=c.snapshot(); did_step=[]
    original=XxmCalculator.step
    def step(self,bar):
        result=original(self,bar); did_step.append(True); return result
    def check():
        if did_step: raise RuntimeError('cancel after child step')
    monkeypatch.setattr(XxmCalculator,'step',step)
    with pytest.raises(RuntimeError,match='cancel after child step'):
        forecast(c,ProjectionState(13,27,0),stamp('day',6),check,prepared=prepared)
    assert did_step and c.snapshot()==before and detector._EVALUATIONS.get() is None


def test_pf18_source_combinations_isolated_and_one_advance_per_price(monkeypatch):
    c=calculator(M1); before=c.snapshot(); projection=ProjectionState(13,27,0)
    advances=[]; children=[]; steps=[]
    original_advance,original_clone,original_step=ProjectionState.advance,detector.clone,XxmCalculator.step
    def advance(self,C): advances.append(C); return original_advance(self,C)
    def clone(parent):
        child=original_clone(parent); children.append(child); return child
    def step(self,bar): steps.append(id(self)); return original_step(self,bar)
    # Source substitute only: both values remain well inside the M1 formation case.
    monkeypatch.setattr(detector,'source_options',lambda v,day:(v-1e-9,v+1e-9))
    monkeypatch.setattr(ProjectionState,'advance',advance)
    monkeypatch.setattr(detector,'clone',clone)
    monkeypatch.setattr(XxmCalculator,'step',step)
    with detector.next_bar_evaluations():
        first=detector.evaluate_next_at_price(c,projection,2.,stamp('day',6),'NEAR',lambda:None)
        first['reference']['dif']=999
        second=detector.evaluate_next_at_price(c,projection,2.,stamp('day',6),'NEAR',lambda:None)
    assert second['outcome']=='STRUCTURE_FORMED' and second['reference']['dif']==-50
    assert advances==[2.] and len(steps)==4 and len(set(steps))==4
    assert all(child is not c for child in children) and c.snapshot()==before
    assert detector._EVALUATIONS.get() is None


def test_pf18_source_disagreement_stays_uncertain(monkeypatch):
    c=calculator(M1)
    # H remains zero while the two independent D options straddle the 1% gate.
    calls=[]
    def options(v,day):
        calls.append(v)
        return (-14.,-13.) if len(calls)==1 else (0.,)
    monkeypatch.setattr(detector,'source_options',options)
    assert detector.evaluate_next_at_price(c,ProjectionState(13,27,0),175.5,stamp('day',6),'NEAR',lambda:None) is None


def test_pf20_fixed_spec_literal_contract_and_hash():
    expected={'forecast_version':'xxm-key-point-forecast-v0.5-r4','scenario_policy':'next_completed_bar',
        'target_selection':'near_range_before_far','max_future_bars':1,'calibration_tail_bars':250,
        'daily_calibration_abs_tol':0.0005,'minute_calibration_abs_tol':1e-8,'daily_rounding_guard':1e-10,
        'display_policy':'valid_integer_boundaries','structure_text_places':0,
        'forecast_compute_budget_ms':400,'max_response_bytes':32768,'future_calendar_days':90,'refresh_after_ms':60000}
    assert asdict(FORECAST_SPEC)==expected
    assert FORECAST_SPEC.spec_hash==hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize('kw',[{'max_future_bars':20},{'max_future_bars':True},{'forecast_compute_budget_ms':400.},
    {'price_display_places':2},{'scenario_policy':'entry_range_then_flat'},{'calibration_tail_bars':250.}])
def test_pf20_old_or_wrongly_typed_spec_is_rejected(kw):
    with pytest.raises((ValueError,TypeError)): ForecastSpec(**kw)


def test_pf20_endpoint_is_one_future_string_and_prepared_is_required():
    c=calculator(M1); p=precheck_next_bar(c,lambda:None)
    with pytest.raises(ValueError): forecast(c,ProjectionState(13,27,0),[stamp('day',6)],lambda:None,prepared=p)
    with pytest.raises(ValueError): forecast(c,ProjectionState(13,27,0),c.previous.time,lambda:None,prepared=p)
    with pytest.raises(TypeError): forecast(c,ProjectionState(13,27,0),stamp('day',6),lambda:None)


def test_pf20_text_reads_actual_direction_keeps_singletons_and_all_ranges():
    c=calculator(((100,-200,-2),(110,0,2),(99,1,-2),(98,2,-2)))
    p=precheck_next_bar(c,lambda:None); assert p.direction=='BOTTOM' and c.previous.dif>0
    price=dict(lower=175.5,upper=175.5,lowerInclusive=True,upperInclusive=True,displayLower=None,displayUpper=None)
    integer=dict(lower=180.,upper=181.,lowerInclusive=True,upperInclusive=True,displayLower=180,displayUpper=181)
    draft=ForecastConditionDraft('STRUCTURE_FORMED','NEAR',(price,integer),())
    r=ForecastKernelResult('READY',None,stamp('day',4),1,deepcopy(p.references),'NEAR',
        {'status':'HAS_RANGE','reason':'字面测试'},False,(draft,),(),())
    display=make_display(r,prepared=p,period='day',through=c.previous.time,mode='LATEST',check=lambda:None)
    assert set(display)=={'statusLabel','targetText','conditionsText','asOfText'}
    assert all(type(v) is str for v in display.values())
    assert '底部结构' in display['conditionsText'] and '顶部' not in display['conditionsText']
    assert '仅单一收盘点' in display['conditionsText'] and '180' in display['conditionsText'] and '181' in display['conditionsText']
    with pytest.raises(ValueError): make_display(r,prepared=p,period='m60',through=c.previous.time,mode='LATEST',check=lambda:None)
    with pytest.raises(ValueError): make_display(r,prepared=p,period='day',through=DATES[0],mode='LATEST',check=lambda:None)


@pytest.mark.parametrize('period',PERIODS)
def test_pf19_mathematical_time_and_repeat_leave_no_shared_results(period,record_property):
    c=calculator(M1,period); before=c.snapshot(); start=time.perf_counter(); one=run(c,ProjectionState(13,27,0))
    elapsed=time.perf_counter()-start
    record_property('math_ms',round(elapsed*1000,3))
    assert elapsed<0.4  # Mathematical portion only; not the full query budget.
    two=run(c,ProjectionState(13,27,0)); assert one==two and c.snapshot()==before
    one.references['nearest']['dif']=999
    assert two.references['nearest']['dif']==-50 and c.reference.dif==-50


@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('values,expected',[
    (((100,-200,-2),(110,0,2),(99,-100,-2)),set()),
    (((100,-200,-2),(110,0,2),(101,-100,-2),(102,-100,-2)),{'DULL_FORMED'}),
])
def test_pf07_zero_does_not_supply_second_colored_bar(period,values,expected):
    # M2 projection has exact D=H=0 at C24.5; bottom price/DIF gates pass.
    c=calculator(values,period)
    result=run(c,ProjectionState(187,173,0))
    assert outcomes_at(result,24.5)==expected
    actual=detector.evaluate_next_at_price(c,ProjectionState(187,173,0),24.5,
        stamp(period,len(values)),'NEAR',lambda:None)
    assert actual['outcome']==('DULL_FORMED' if expected else None)


@pytest.mark.parametrize('period',PERIODS)
def test_pf08_zero_previous_dif_disables_turn_and_return(period):
    dull=calculator(((100,-200,-2),(110,0,2),(99,-100,-2),(98,0,-2)),period)
    assert dull.state=='DULL' and dull.previous.dif==0
    value=detector.evaluate_next_at_price(dull,ProjectionState(13,27,0),2.,stamp(period,4),'NEAR',lambda:None)
    assert value['outcome']=='DULL_HELD'
    structure=calculator(TS+((104,0,2),),period)
    assert structure.state=='STRUCTURE' and structure.previous.dif==0
    value=detector.evaluate_next_at_price(structure,ProjectionState(187,173,0),30.,stamp(period,6),'NEAR',lambda:None)
    assert value['outcome']=='STRUCTURE_HELD'


@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('sign',[1,-1])
def test_pf08_gate_underflow_keeps_strict_direction(period,sign):
    tiny=math.nextafter(0.,math.inf)
    values=((100,sign*200,sign*2),(90 if sign==1 else 110,0,-sign*2),
            (101 if sign==1 else 99,sign*100,sign*2),
            (102 if sign==1 else 98,sign*tiny,sign*2))
    c=calculator(values,period); assert c.state=='DULL' and abs(c.previous.dif)*1.0/100==0
    value=detector.evaluate_next_at_price(c,ProjectionState(187,173,0),24.5,
        stamp(period,4),'NEAR',lambda:None)
    assert value['outcome']=='STRUCTURE_FORMED'  # strict tiny -> 0, gate is zero.


def test_pf06_reference_identity_includes_dates_not_only_values():
    c=calculator(((120,200,2),(90,0,-2),(120,200,2),(110,0,-2),(130,100,2),(131,100,2)))
    assert c.history[1][0].price==c.history[1][1].price
    assert c.history[1][0].dif==c.history[1][1].dif
    assert c.history[1][0].start!=c.history[1][1].start
    result=run(c,ProjectionState(102,100,0))
    assert result.selected_reference=='NEAR' and not result.far_evaluated
    assert result.references['nearest']['startTime']==DATES[2]
    with pytest.raises(ValueError):
        solve_active_reference(c,ProjectionState(102,100,0),stamp('day',6),
                               c.history[1][0],'NEAR',lambda:None)


def test_pf07_first_top_positive_dif_policy_remains_unchanged():
    c=calculator(((100,200,2),(90,0,-2),(99,-10,2),(99,-9,2)))
    result=run(c,ProjectionState(13,27,-20))
    assert outcomes_at(result,110.)==set()  # price passes, red H, but D remains negative.
    assert outcomes_at(result,200.)=={'DULL_FORMED'}


def test_pf17_reference_comparison_overflow_is_rejected_before_forecast():
    c=calculator(((100,-1e308,2),(90,0,-2),(101,1e308,2)))
    before=c.snapshot()
    with pytest.raises(ValueError,match='Non-finite reference'):
        precheck_next_bar(c,lambda:None)
    assert c.snapshot()==before


def test_pf17_selected_far_difference_overflow_is_not_a_disappearance():
    values=((100,1.7e308,-2),(110,0,2),(80,1.75e308,-2),(90,0,2),
            (70,1.78e308,-2),(69,1.78e308,-2),(68,1.725e308,-2))
    c=calculator(values); assert c.state=='DULL' and c.reference==c.history[-1][0]
    before=c.snapshot()
    with pytest.raises(ValueError):
        detector.evaluate_next_at_price(c,ProjectionState(-1.6e307,7e306,-2e307),1.,
                                       stamp('day',7),'FAR',lambda:None)
    assert c.snapshot()==before and detector._EVALUATIONS.get() is None


@pytest.mark.parametrize('values,projection',[
    (((100,1.7e308,2),(90,0,-2),(101,100,2),(102,100,2),(103,-1.79e308,2)),
     ProjectionState(1e307,-1e306,-1e307)),
    (((100,1.79e308,2),(90,0,-2),(101,100,2),(102,100,2),(103,99,2)),
     ProjectionState(-1e307,1e306,-1e307)),
])
def test_pf17_structure_finite_dif_must_not_overflow_turn_or_reference(values,projection):
    # All inputs and projected D are finite; D-P or D-R is not.
    c=calculator(values,'m60'); assert c.state=='STRUCTURE'
    before=c.snapshot()
    with pytest.raises(ValueError):
        detector.evaluate_next_at_price(c,projection,1.,stamp('m60',len(values)),
                                       'NEAR',lambda:None)
    assert c.snapshot()==before and detector._EVALUATIONS.get() is None


def test_pf17_normal_kernel_needs_no_files_or_network(monkeypatch):
    import builtins
    import io
    import socket
    c=calculator(M1); before=c.snapshot()
    def forbidden(*args,**kwargs):
        pytest.fail('pure forecast attempted file or network access')
    with monkeypatch.context() as guard:
        guard.setattr(builtins,'open',forbidden)
        guard.setattr(io,'open',forbidden)
        guard.setattr(socket,'socket',forbidden)
        result=run(c,ProjectionState(13,27,0))
    assert result.status=='READY' and c.snapshot()==before
