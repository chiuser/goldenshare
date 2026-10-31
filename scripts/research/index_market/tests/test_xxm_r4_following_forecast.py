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
from scripts.research.index_market.tests.test_xxm_r4_following import TS, TF, TN, bars, run, values


def target(c):
    return '2023-01-19' if c.period=='day' else '2023-01-19T15:00:00+08:00'


def interval_has(r,C):
    return ((C>r['lower'] or C==r['lower'] and r['lowerInclusive'])
            and (r['upper'] is None or C<r['upper'] or C==r['upper'] and r['upperInclusive']))


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf21_22_23_literal_old_structure_color_and_strict_price_boundaries(period,sign):
    # Hand equations: D=(28C+26306)/351, H=0 at 8443/28 for top.
    # Bottom: D=(28C-37450)/351, H=0 at 2701/28.
    c,_=run(values(TF,sign),period)
    projection=ProjectionState(198,100,99) if sign==1 else ProjectionState(200,298,-99)
    record=next(r for r in c.followed_structures.values() if r)
    out=solve_followed_structure(c,projection,target(c),record,lambda:None)
    for C,wanted in ([(301,False),(302,True),(103,False)] if sign==1 else [(97,False),(96,True),(98,False)]):
        assert evaluate_structure_follow_at_price(c,projection,C,target(c),record['id'],lambda:None) is wanted
        assert any(interval_has(r,C) for r in out.price_ranges) is wanted
    if sign==1:
        assert min(r['displayLower'] for r in out.price_ranges if r['displayLower'] is not None)==302
        c,_=run(TN,period);record=c.followed_structures['TOP'];projection=ProjectionState(196,100,95)
        # H=0 at 7633/28. 104 ends the segment normally, 273 can cancel.
        assert evaluate_structure_follow_at_price(c,projection,104,target(c),record['id'],lambda:None) is False
        assert evaluate_structure_follow_at_price(c,projection,273,target(c),record['id'],lambda:None) is True


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
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


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_pf26_static_ordinary_no_candidate_does_not_suppress_old_conditions(sign,period):
    rows=TS+[(90,-1,-2)]
    c,_=run(values(rows,sign),period);p=precheck_next_bar(c,lambda:None)
    assert p.stop_reason is not None and len(p.following_structures)==1
    projection=ProjectionState(100,101,0) if sign==1 else ProjectionState(101,100,0)
    result=forecast(c,projection,target(c),lambda:None,prepared=p)
    assert result.status=='READY' and result.selected_reference is None
    assert result.conditions==() and result.structure_follow_conditions
    C=112 if sign==1 else 89
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


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_pf23_exact_zero_keeps_begun_following_but_does_not_start_it(period):
    # C351: EMA12=11+54=65, EMA26=34+26=60, D=5,
    # DEA=.8*5+.2*5=5 and H=0, using exact original operations.
    projection=ProjectionState(13,36.72,5)
    assert projection.advance(351)[1]==(5.,5.,0.)
    for rows,wanted in [(TF,False),(TN,True)]:
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
        deepcopy(record['originWave']),record['nextSameColorStart'],(),(pending,),())
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
