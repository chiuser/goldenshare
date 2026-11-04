"""PF21–28: literal one-step EMA arithmetic and independent old-structure checks."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, precheck_next_bar
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import evaluate_structure_follow_at_price, evaluate_next_at_price
from src.biz.services.wealth.market.index_detail_xxm.forecast_next import solve_followed_structure
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from scripts.research.index_market.tests.test_xxm_r4_following import T, TS, TF, TN, MULTI_SINGLE, bars, run, values


def target(c):
    return '2023-01-19' if c.period=='day' else '2023-01-19T15:00:00+08:00'


def interval_has(r,C):
    return ((C>r['lower'] or C==r['lower'] and r['lowerInclusive'])
            and (r['upper'] is None or C<r['upper'] or C==r['upper'] and r['upperInclusive']))


@pytest.mark.parametrize('period',['day','m30','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf21_22_23_literal_old_structure_color_and_strict_price_boundaries(period,sign):
    # Hand equations: D=(28C+26306)/351, H=0 at 8443/28 for top.
    # Bottom: D=(28C-37450)/351, H=0 at 2701/28.
    c,_=run(values(TF,sign),period)
    projection=ProjectionState(198,100,99) if sign==1 else ProjectionState(200,298,-99)
    record=next(r for r in c.followed_structures.values() if r)
    out=solve_followed_structure(c,projection,target(c),record,lambda:None)
    for C,wanted in ([(301,True),(104,True),(103,False)] if sign==1 else [(97,False),(96,True),(96.75,True),(98,False)]):
        assert evaluate_structure_follow_at_price(c,projection,C,target(c),record['id'],lambda:None) is wanted
        assert any(interval_has(r,C) for r in out.price_ranges) is wanted
    if sign==1:
        assert min(r['displayLower'] for r in out.price_ranges if r['displayLower'] is not None)==104
        c,_=run(TN,period);record=c.followed_structures['TOP'];projection=ProjectionState(196,100,95)
        # H=0 at 7633/28. 104 ends the segment normally, 273 can cancel.
        assert evaluate_structure_follow_at_price(c,projection,104,target(c),record['id'],lambda:None) is False
        assert evaluate_structure_follow_at_price(c,projection,273,target(c),record['id'],lambda:None) is True


@pytest.mark.parametrize('period',['day','m30','m60','m90','m120'])
def test_pf24_old_verifier_never_selects_far_or_runs_a_full_step(period):
    c,_=run(TN,period);p=precheck_next_bar(c,lambda:None);projection=ProjectionState(196,100,95)
    original=c.snapshot()
    from src.biz.services.wealth.market.index_detail_xxm import forecast as module
    qualify=type(c)._current_reference_qualifies;first=module.solve_first_dull
    far_start=c.history[c.wave.sign][0].start
    def reject_far(self,bar,wave,reference,nearest):
        if reference.start==far_start: raise AssertionError('A qualification forbidden')
        return qualify(self,bar,wave,reference,nearest)
    def near_solver(*args,**kwargs):
        if args[4]=='FAR': raise AssertionError('A solver forbidden')
        return first(*args,**kwargs)
    with patch.object(type(c),'_current_reference_qualifies',reject_far), \
         patch.object(type(c),'_rescue_dull_reference',side_effect=AssertionError('A rescue forbidden')), \
         patch.object(module,'solve_first_dull',near_solver):
        result=forecast(c,projection,target(c),lambda:None,prepared=p)
    assert result.nearest_decision['status']=='HAS_RANGE' and not result.far_evaluated
    assert len(result.structure_follow_conditions)==1
    # C400 invalidates near ordinary DIF, but remains a valid old price break.
    # Full ordinary step would attempt A. Old-only certification must not do so.
    with patch.object(type(c),'step',side_effect=AssertionError('full step forbidden')), \
         patch.object(type(c),'_select_eligible_reference',side_effect=AssertionError('selection forbidden')), \
         patch.object(type(c),'_rescue_dull_reference',side_effect=AssertionError('far rescue forbidden')):
        assert evaluate_structure_follow_at_price(c,projection,400,target(c),c.followed_structures['TOP']['id'],lambda:None) is True
    assert c.snapshot()==original
    assert any(interval_has(r,400) for r in result.structure_follow_conditions[0].price_ranges)


@pytest.mark.parametrize('period',['day','m30','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf26_static_ordinary_no_candidate_does_not_suppress_old_conditions(sign,period):
    rows=TS+[(90,-1,-2)]
    c,_=run(values(rows,sign),period);p=precheck_next_bar(c,lambda:None)
    assert p.stop_reason is not None and len(p.following_structures)==1
    projection=ProjectionState(100,101,0) if sign==1 else ProjectionState(101,100,0)
    result=forecast(c,projection,target(c),lambda:None,prepared=p)
    assert result.status=='READY' and result.selected_reference is None
    assert result.conditions==() and result.structure_follow_conditions
    C=104 if sign==1 else 96
    assert any(interval_has(r,C) for r in result.structure_follow_conditions[0].price_ranges)
    display=make_display(result,prepared=p,period=period,through=c.previous.time,mode='LATEST',check=lambda:None)
    assert len(display)==4 and '旧结构消失' in display['conditionsText']
    assert '锁死' not in display['conditionsText']


@pytest.mark.parametrize('rows',[TN+[(120,95,-2)],TF+[(104,97,2)]])
def test_pf25_ended_or_disappeared_old_record_is_not_forecast_again(rows):
    c,steps=run(rows);p=precheck_next_bar(c,lambda:None)
    assert p.following_structures==()
    old=steps[4].structures[0]
    with pytest.raises(ValueError):
        evaluate_structure_follow_at_price(c,ProjectionState(196,100,95),400,target(c),old['id'],lambda:None)
    assert not any(r for r in c.followed_structures.values())


def test_pf27_28_target_identity_cancellation_and_real_progress_isolation():
    c,_=run(TN);p=precheck_next_bar(c,lambda:None);original=c.snapshot()
    fake=deepcopy(p);fake.snapshot['followedStructures']['TOP']['originWave']['price']+=1
    with pytest.raises(ValueError): forecast(c,ProjectionState(196,100,95),target(c),lambda:None,prepared=fake)
    record=c.followed_structures['TOP'];calls=[]
    def cancel():
        calls.append(1)
        if len(calls)==8: raise TimeoutError('literal deadline')
    with pytest.raises(TimeoutError):
        solve_followed_structure(c,ProjectionState(196,100,95),target(c),record,cancel)
    assert c.snapshot()==original
    assert len(c.followed_structures)==2
    assert 'structures' not in original and 'structure_records' not in original
    # Preparing/forecasting objects must not share mutable records with c.
    p.following_structures[0]['originWave']['price']+=1
    assert c.snapshot()==original


@pytest.mark.parametrize('period',['day','m30','m60','m90','m120'])
def test_pf23_zero_checks_price_without_starting_or_ending_a_color_segment(period):
    # C351: EMA12=11+54=65, EMA26=34+26=60, D=5,
    # DEA=.8*5+.2*5=5 and H=0, using exact original operations.
    projection=ProjectionState(13,36.72,5)
    assert projection.advance(351)[1]==(5.,5.,0.)
    for rows,wanted in [(TF,True),(TN,True)]:
        c,_=run(rows,period);record=c.followed_structures['TOP']
        assert evaluate_structure_follow_at_price(c,projection,351,target(c),record['id'],lambda:None) is wanted


@pytest.mark.parametrize('kind,expected',[('old_pending','PRECISION_PENDING'),('none','NO_CANDIDATE'),('overlap','READY')])
def test_pf26_handwritten_drafts_only_test_status_composition(kind,expected):
    from src.biz.services.wealth.market.index_detail_xxm.types import ForecastKernelResult, ForecastConditionDraft, StructureFollowConditionDraft
    from src.biz.services.wealth.market.index_detail_xxm import forecast as module
    c,_=run(TS+[(90,-1,-2)]);p=precheck_next_bar(c,lambda:None);record=p.following_structures[0]
    price=dict(lower=100.,upper=110.,lowerInclusive=False,upperInclusive=True,displayLower=101,displayUpper=110)
    ordinary=(ForecastConditionDraft('DULL_FORMED','NEAR',(price,),()),) if kind=='overlap' else ()
    pending={'priceRange':dict(lower=105. if kind=='overlap' else 100.2,upper=106. if kind=='overlap' else 100.3,
                              lowerInclusive=False,upperInclusive=False),'reason':'ROUNDING_BOUNDARY'}
    old=None if kind=='none' else StructureFollowConditionDraft('SIGNAL_DISAPPEARED',record['id'],record['direction'],
        deepcopy(record['originWave']),record['nextSameColorStart'],record['nextSameColorCount'],(),(pending,),())
    literal=ForecastKernelResult('READY' if ordinary else 'NO_CANDIDATE',None,target(c),1,deepcopy(p.references),
                                'NEAR' if ordinary else None,{'status':'NOT_EVALUATED','reason':None},False,ordinary,(),())
    with patch.object(module,'_forecast_ordinary',return_value=literal),patch.object(module,'solve_followed_structure',return_value=old):
        out=module.forecast(c,ProjectionState(100,101,0),target(c),lambda:None,prepared=p)
    assert out.status==expected
    if kind!='none':
        assert out.reason_code=='ROUNDING_BOUNDARY' and out.structure_follow_conditions[0].precision_ranges
    if kind=='overlap':
        assert out.conditions==ordinary
        text=make_display(out,prepared=p,period='day',through=c.previous.time,mode='LATEST',check=lambda:None)
        assert '旧结构另有临界范围' in text['conditionsText']


def test_pf28_one_request_shares_original_projection_cache_across_old_and_current():
    c,_=run(TN);p=precheck_next_bar(c,lambda:None);projection=ProjectionState(196,100,95)
    calls={};advance=ProjectionState.advance
    def observed(self,C):
        calls[C]=calls.get(C,0)+1
        return advance(self,C)
    with patch.object(ProjectionState,'advance',observed):
        result=forecast(c,projection,target(c),lambda:None,prepared=p)
    assert result.conditions and result.structure_follow_conditions
    assert calls and max(calls.values())==1


def test_pf27_certification_conflict_fails_whole_solver_and_clears_scope():
    from src.biz.services.wealth.market.index_detail_xxm import forecast_detector as detector
    c,_=run(TN);before=c.snapshot();record=c.followed_structures['TOP']
    with patch.object(detector,'evaluate_structure_follow_at_price',return_value=False):
        with pytest.raises(ValueError,match='Certified old structure point'):
            solve_followed_structure(c,ProjectionState(196,100,95),target(c),record,lambda:None)
    assert c.snapshot()==before and detector._EVALUATIONS.get() is None
    wrong=deepcopy(record);wrong['id']='another-structure'
    with pytest.raises(ValueError,match='absent'):
        solve_followed_structure(c,ProjectionState(196,100,95),target(c),wrong,lambda:None)


def test_pf28_cancel_after_shared_old_step_does_not_publish_or_leak_cache():
    from src.biz.services.wealth.market.index_detail_xxm import forecast_detector as detector
    c,_=run(TN);before=c.snapshot();advance=c._advance_followed_structures
    def fail_after(*args,**kwargs):
        events,records=advance(*args,**kwargs)
        assert events and records[0]['status']=='DISAPPEARED'
        raise TimeoutError('after old step')
    with patch.object(c,'_advance_followed_structures',side_effect=fail_after):
        with pytest.raises(TimeoutError,match='after old step'):
            evaluate_structure_follow_at_price(c,ProjectionState(196,100,95),400,target(c),
                                              c.followed_structures['TOP']['id'],lambda:None)
    assert c.snapshot()==before and detector._EVALUATIONS.get() is None


@pytest.mark.parametrize('boundary',['kernel_result','old_draft'])
def test_pf28_deadline_after_final_construction_still_rejects_and_releases_memory(boundary):
    from src.biz.services.wealth.market.index_detail_xxm import forecast as module,forecast_detector as detector,types
    c,_=run(TN);before=c.snapshot();p=precheck_next_bar(c,lambda:None);finished=[]
    def check():
        if finished: raise TimeoutError('after final construction')
    owner=module if boundary=='kernel_result' else types
    name='replace' if boundary=='kernel_result' else 'StructureFollowConditionDraft'
    constructor=getattr(owner,name)
    def finish_then_expire(*args,**kwargs):
        value=constructor(*args,**kwargs);finished.append(True);return value
    with patch.object(owner,name,finish_then_expire):
        with pytest.raises(TimeoutError,match='final construction'):
            if boundary=='kernel_result':
                forecast(c,ProjectionState(196,100,95),target(c),check,prepared=p)
            else:
                solve_followed_structure(c,ProjectionState(196,100,95),target(c),c.followed_structures['TOP'],check)
    assert c.snapshot()==before and detector._EVALUATIONS.get() is None


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf29_single_segment_ending_still_has_price_break_range(period,sign):
    c,_=run(values(TF+[(102,97,2)],sign),period)
    projection=ProjectionState(197,100,96) if sign==1 else ProjectionState(100,197,-96)
    record=next(r for r in c.followed_structures.values() if r)
    assert record['nextSameColorCount']==1
    out=solve_followed_structure(c,projection,target(c),record,lambda:None)
    C=104 if sign==1 else 96
    assert evaluate_structure_follow_at_price(c,projection,C,target(c),record['id'],lambda:None) is True
    assert any(interval_has(r,C) for r in out.price_ranges)
    assert out.next_same_color_count==1 and len(out.predicates)==1
    boundary='displayLower' if sign==1 else 'displayUpper'
    assert {r[boundary] for r in out.price_ranges}=={C}
    # Same close, count2: opposite bar normally finishes the old tracking.
    effective,_=run(values(TN,sign),period)
    effective_projection=ProjectionState(196,100,95) if sign==1 else ProjectionState(100,196,-95)
    r=next(r for r in effective.followed_structures.values() if r)
    assert evaluate_structure_follow_at_price(effective,effective_projection,C,target(effective),r['id'],lambda:None) is False


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf30_exact_zero_separator_still_checks_price_without_starting_segment(period,sign):
    rows=TF+[(90,98,0)]
    c,_=run(values(rows,sign),period)
    projection=ProjectionState(198,100,98) if sign==1 else ProjectionState(100,198,-98)
    C=289 if sign==1 else 9
    # Independent arithmetic: 212-114=98 or 86-184=-98; DEA unchanged, H exactly0.
    assert projection.advance(C)[1]==(98.*sign,98.*sign,0.)
    record=next(r for r in c.followed_structures.values() if r)
    before=c.snapshot()
    assert evaluate_structure_follow_at_price(c,projection,C,target(c),record['id'],lambda:None) is True
    assert c.snapshot()==before and record['nextSameColorStart'] is None


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf31_effective_bottom_and_top_end_vs_same_color_price_failure(period,sign):
    c,_=run(values(TN,sign),period)
    p=ProjectionState(196,100,95) if sign==1 else ProjectionState(100,196,-95)
    r=next(v for v in c.followed_structures.values() if v)
    out=solve_followed_structure(c,p,target(c),r,lambda:None)
    safe_end=104 if sign==1 else 96
    same_color_break=273 if sign==1 else 23
    assert evaluate_structure_follow_at_price(c,p,safe_end,target(c),r['id'],lambda:None) is False
    assert evaluate_structure_follow_at_price(c,p,same_color_break,target(c),r['id'],lambda:None) is True
    assert out.next_same_color_count==2 and len(out.predicates)==2
    assert any(interval_has(x,same_color_break) for x in out.price_ranges)
    assert not any(interval_has(x,safe_end) for x in out.price_ranges)
    field='displayLower' if sign==1 else 'displayUpper'
    assert {x[field] for x in out.price_ranges if x[field] is not None}=={same_color_break}
    # A proved narrow float interval can have no legal integer; it must stay present.


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('rows,top_ema,bottom_ema',[
    (TF+[(102,97,2),(102,96,-2)],(196,100,97),(100,196,-97)),
    (MULTI_SINGLE[:12],(192,100,93),(100,192,-93)),
])
def test_pf32_skipped_single_restore_has_same_range_and_no_history_pool_requirement(period,sign,rows,top_ema,bottom_ema):
    c,_=run(values(rows,sign),period)
    clone=type(c)(period=period,source_identity=c.source_identity);clone.restore(c.snapshot())
    projection=ProjectionState(*(top_ema if sign==1 else bottom_ema))
    r=next(v for v in c.followed_structures.values() if v)
    assert r['nextSameColorStart'] is None and r['nextSameColorCount']==0
    a=solve_followed_structure(c,projection,target(c),r,lambda:None)
    b=solve_followed_structure(clone,projection,target(clone),clone.followed_structures[r['direction']],lambda:None)
    assert a==b and any(interval_has(x,104 if sign==1 else 96) for x in a.price_ranges)


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('rows,ema,price,safe,expected_safe',[
    (T,(200,100,99),103,101,'STRUCTURE_FORMED_AND_FOLLOWING'),
    (TS,(199,100,98),104,102,'STRUCTURE_FOLLOWING'),
    (values(T,-1),(100,200,-99),97,99,'STRUCTURE_FORMED_AND_FOLLOWING'),
    (values(TS,-1),(100,199,-98),96,98,'STRUCTURE_FOLLOWING'),
])
def test_pf13_first_opposite_current_structure_price_failure_is_not_following(period,rows,ema,price,safe,expected_safe):
    from src.biz.services.wealth.market.index_detail_xxm.forecast_next import solve_active_reference
    c,_=run(rows,period);before=c.snapshot();projection=ProjectionState(*ema)
    actual=evaluate_next_at_price(c,projection,price,target(c),'NEAR',lambda:None)
    assert actual['outcome']=='STRUCTURE_PRICE_DISAPPEARED'
    assert evaluate_next_at_price(c,projection,safe,target(c),'NEAR',lambda:None)['outcome']==expected_safe
    solved=solve_active_reference(c,projection,target(c),c.reference,'NEAR',lambda:None)
    assert any(condition.outcome=='STRUCTURE_PRICE_DISAPPEARED' and any(interval_has(r,price) for r in condition.price_ranges)
               for condition in solved.conditions)
    assert not any(r.contains(price) for r in solved.relationship_ranges)
    assert c.snapshot()==before


def test_pf33_full_computation_keeps_old_cancel_plus_new_activation_and_both_forecast_conditions():
    c,_=run(TN);prepared=precheck_next_bar(c,lambda:None);projection=ProjectionState(196,100,95)
    result=forecast(c,projection,target(c),lambda:None,prepared=prepared)
    assert any(condition.outcome=='DULL_FORMED' and any(interval_has(r,273) for r in condition.price_ranges)
               for condition in result.conditions)
    assert any(interval_has(r,273) for r in result.structure_follow_conditions[0].price_ranges)
    _,(dif,dea,hist)=projection.advance(273)
    child=type(c)(period=c.period,source_identity=c.source_identity);child.restore(c.snapshot())
    step=child.step(type(c.previous)(target(c),273,dif,dea,hist))
    assert [e['route'] for e in step.events]==['structure_price_break','activation']
    assert len(step.events)==2 and step.structures[0]['status']=='DISAPPEARED'


def test_pf34_display_rejects_wrong_or_boolean_count_and_keeps_real_input_unchanged():
    c,_=run(TN);prepared=precheck_next_bar(c,lambda:None)
    result=forecast(c,ProjectionState(196,100,95),target(c),lambda:None,prepared=prepared)
    before=c.snapshot();condition=result.structure_follow_conditions[0]
    for bad_count in (True,-1,0,1,'2'):
        bad=replace(result,structure_follow_conditions=(replace(condition,next_same_color_count=bad_count),))
        with pytest.raises(ValueError,match='prepared'):
            make_display(bad,prepared=prepared,period='day',through=c.previous.time,mode='LATEST',check=lambda:None)
    assert c.snapshot()==before
