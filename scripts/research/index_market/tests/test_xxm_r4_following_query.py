"""RC91–94 internal producer/model/window boundaries, exclusively literal inputs."""
from copy import deepcopy
from datetime import date
from dataclasses import replace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService as Query, SeriesEntry
from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto
from goldenshare_technical_indicators.xxm.calculator import XxmCalculator
from goldenshare_technical_indicators.xxm.types import XxmStep
from scripts.research.index_market.tests.test_xxm_r4_following import DATES, T, TS, TF, TN, DUAL, REACTIVATION_ROWS, bars, run, values
from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response


def entry(rows, period='day', *, ts_code='000001.SH'):
    c=XxmCalculator(ts_code=ts_code,period=period,source_identity='finite-literals')
    inputs=tuple(bars(rows,period))
    result=SeriesEntry(inputs,(),c,inputs,[],[],{},['literal']*len(rows),{})
    for bar in inputs:
        step=c.step(bar)
        Query._merge_structure_updates(result,step,bar=bar)
        result.points.append(step.point)
        result.events.extend(step.events)
    Query._validate_entry(result,check=lambda:None)
    return result


def response(item, count, *, limit=1000, start=None):
    return Query._response(item,ts_code=item.calculator.ts_code,period=item.calculator.period,expected=item.processed[count-1].time,
                          start_date=start,limit=limit,check=lambda:None)


@pytest.mark.parametrize("limit", [1, 11])
def test_r41_triple_events_survive_cropping_and_public_projection(limit):
    item = entry(REACTIVATION_ROWS, "m90")
    assert {s.status for s in response(item, 10).structures} == {"FOLLOWING", "ASSESSING"}
    out = response(item, 11, limit=limit)
    end = item.processed[-1].time
    events = [e for e in out.events if e.time == end]
    assert [e.route for e in events] == ["structure_price_break", "dif_break", "activation"]
    assert len({e.relatedStructureId for e in events[:2]}) == 2
    assert out.points[-1].activeReference == events[-1].eventReference
    assert [s.status for s in out.structures] == ["DISAPPEARED", "DISAPPEARED"]
    public = project_xxm_response(out, debug=False)
    debug = project_xxm_response(out, debug=True)
    assert [e.displayOnChart for e in public.events if e.time == end] == [False, False, True]
    assert public.model_dump() == debug.model_dump(exclude={"debug"})
    assert [e.route for e in debug.debug.events[-3:]] == ["structure_price_break", "dif_break", "activation"]
    invalid = out.model_dump()
    invalid["events"][-2:] = reversed(invalid["events"][-2:])
    with pytest.raises(ValidationError):
        InternalXxmResponseDto.model_validate(invalid)


@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('flip',[False,True])
def test_rc91_93_all_phases_projection_windows_no_future_fields(sign,flip):
    rows=(T+[(90,100,-2),(101,99,2),(102,98,2),(120,97,-2),(121,96,2)] if flip
          else TN+[(120,95,-2),(121,94,2)])
    item=entry(values(rows,sign));original=deepcopy(item.structure_records)
    end=8 if flip else 9
    expected={4:[],5:['FOLLOWING' if flip else 'ASSESSING'],6:['FOLLOWING'],7:['FOLLOWING'],
              end:['FINISHED'],end+1:[]}
    for cut,statuses in expected.items():
        out=response(item,cut,limit=1)
        assert [r.status for r in out.structures]==statuses
        if out.structures:
            record=out.structures[0]
            if cut<end: assert record.trackingEndedAt is None
            if cut==5 and not flip:
                assert record.originWave is None and record.firstOppositeAt is None
            elif cut< (6 if flip else 7):
                assert record.nextSameColorStart is None
            if cut==end:
                assert out.events==[] and record.trackingEndedAt==item.processed[cut-1].time
    # No-event window wholly inside a live interval still contains that structure.
    inside=7 if flip else 8
    out=response(item,inside,limit=1)
    assert out.events==[] and out.structures[0].status=='FOLLOWING'
    assert out.structures[0].nextSameColorStart==item.processed[(6 if flip else 7)-1].time
    assert item.structure_records==original
    # Actual source prefix can exist while the selected window is empty.
    empty=response(item,len(rows),start=date(2024,1,1))
    assert empty.points==empty.events==empty.structures==[] and empty.dataStatus.status=='READY'
    assert empty.source.computedThrough==item.processed[-1].time


@pytest.mark.parametrize('sign',[1,-1])
def test_rc93_full_internal_model_preserves_multiple_events_and_original_refs(sign):
    item=entry(values(DUAL,sign));body=response(item,9).model_dump()
    assert [e['route'] for e in body['events'] if e['time']==DATES[8]]==['structure_price_break','color_flip']
    assert {r['status'] for r in body['structures']}=={'DISAPPEARED','FOLLOWING'}
    old=next(r for r in body['structures'] if r['status']=='DISAPPEARED')
    e=next(e for e in body['events'] if e['route']=='structure_price_break')
    assert e['eventReference']==old['originalReference']
    assert e['direction']!=body['events'][-1]['direction']
    for change in ['reference','id','end','extra']:
        bad=deepcopy(body)
        event=next(e for e in bad['events'] if e['route']=='structure_price_break')
        if change=='reference': event['eventReference']['dif']+=1
        elif change=='id': event['id']='forged'
        elif change=='end': next(r for r in bad['structures'] if r['status']=='DISAPPEARED')['trackingEndedAt']=DATES[7]
        else: next(r for r in bad['structures'] if r['status']=='DISAPPEARED')['lockedAt']=DATES[5]
        with pytest.raises((ValueError,ValidationError)): InternalXxmResponseDto.model_validate(bad)


def test_rc93_window_does_not_hide_invalid_following_or_rebuild_per_record():
    item=entry(TN)
    calls=[]
    original=SeriesEntry.calculator_at
    with patch.object(SeriesEntry,'calculator_at',lambda self,count,check:(calls.append(count),original(self,count,check))[1]):
        out=response(item,8,limit=1)
    assert calls==[8] and len(out.structures)==1
    broken=replace(item,structure_records=deepcopy(item.structure_records))
    next(iter(broken.structure_records.values()))['nextSameColorStart']=DATES[7]
    with pytest.raises(ValueError):
        response(broken,8,start=date(2024,1,1))


@pytest.mark.parametrize('sign',[1,-1])
def test_rc92_source_correction_does_not_change_published_results(sign):
    rows=TS+[(105,98.5,2),(100,98,-2),(104,97,2),(106,96,2)]
    old=entry(values(rows,sign));out=response(old,9);frozen=out.model_dump()
    revised=rows[:5]+[(106,98.5,2)]+rows[6:]
    new=entry(values(revised,sign));body=response(new,9)
    assert all(e.route!='structure_price_break' for e in body.events)
    assert out.model_dump()==frozen
    assert next(iter(new.structure_records.values()))['priceExtreme']==(103 if sign==1 else 97)
    assert next(iter(new.structure_records.values()))['originWave']['price']==(106 if sign==1 else 94)


def test_rc94_handwritten_may_price_mechanism_not_a_real_ema_replay():
    rows=[(3285.6705,41.186,2),(3200,0,-2),(3393.3312,28.215,2),(3380,28.215,2),(3301.2575,22.901,2),
          (3275.413,16.415,-2),(3395.0036,14.006,2),(3357.6707,15.217,2),(3319.1506,12.920,2)]
    item=entry(rows);out=response(item,9)
    assert [(e.time,e.route) for e in out.events][-1]==(DATES[6],'structure_price_break')
    assert item.points[6]['ordinaryState']==item.points[7]['ordinaryState']==item.points[8]['ordinaryState']=='NONE'
    assert len(item.structure_records)==1


@pytest.mark.parametrize('sign',[1,-1])
def test_rc91_origin_final_extreme_becomes_visible_only_at_first_opposite(sign):
    rows=TS+[(105,98.5,2),(100,98,-2),(104,97,2),(106,96,2)]
    item=entry(values(rows,sign));before=response(item,6);frozen=before.model_dump()
    for count in (5,6):
        r=response(item,count).structures[0]
        assert r.priceExtreme==(103 if sign==1 else 97) and r.originWave is None
        assert r.firstOppositeAt is None and r.nextSameColorStart is None
    r=response(item,7).structures[0]
    assert r.originWave.price==(105 if sign==1 else 95) and r.nextSameColorStart is None
    r=response(item,8).structures[0]
    assert r.nextSameColorStart==DATES[7] and r.disappearedAt is None
    assert response(item,9).structures[0].disappearedAt==DATES[8]
    assert before.model_dump()==frozen


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_four_period_internal_no_event_windows_keep_exact_native_wave_facts(period,sign):
    item=entry(values(TN+[(120,95,-2),(121,94,2)],sign),period)
    live=response(item,8,limit=1)
    assert live.events==[] and len(live.structures)==1
    record=live.structures[0]
    assert record.status=='FOLLOWING' and record.nextSameColorStart==item.processed[6].time
    assert record.originWave.model_dump()==dict(sign=sign,start=item.processed[2].time,end=item.processed[4].time,
        count=3,price=103 if sign==1 else 97,dif=100*sign,price_at=item.processed[4].time,dif_at=item.processed[2].time)
    assert response(item,9,limit=1).structures[0].status=='FINISHED'
    assert response(item,10,limit=1).structures==[]


def test_internal_model_rejects_reordered_old_and_new_events():
    item=entry(DUAL);body=response(item,9).model_dump()
    body['events'][-2:]=reversed(body['events'][-2:])
    with pytest.raises(ValidationError,match='order'):
        InternalXxmResponseDto.model_validate(body)


@pytest.mark.parametrize('rows',[TF+[(104,97,2)],TN+[(120,95,-2)]])
def test_terminal_records_neither_reopen_nor_accept_repeated_updates(rows):
    item=entry(rows);old=deepcopy(item.structure_records);record=next(iter(old.values()))
    assert record['status'] in ('DISAPPEARED','FINISHED')
    for reopen in (False,True):
        incoming=deepcopy(record)
        if reopen:
            incoming.update(status='ASSESSING',originWave=None,firstOppositeAt=None,nextSameColorStart=None,
                            nextSameColorCount=0,trackingPriceExtreme=None,trackingPriceExtremeAt=None,
                            trackingEndedAt=None,disappearedAt=None,disappearanceReason=None)
        with pytest.raises(ValueError,match='terminal'):
            Query._merge_structure_updates(item,XxmStep({},tuple(e for e in item.events if e['time']==item.processed[-1].time),(incoming,)),bar=item.processed[-1])
        assert item.structure_records==old


@pytest.mark.parametrize('sign',[1,-1])
def test_rc103_single_resets_asof_uses_one_real_prefix_and_no_future_fields(sign):
    from scripts.research.index_market.tests.test_xxm_r4_following import MULTI_SINGLE
    item=entry(values(MULTI_SINGLE,sign));frozen=deepcopy(item.structure_records)
    expected={6:(None,0,90,6),7:(7,1,102,7),8:(None,0,102,7),9:(9,1,102,7),
              12:(None,0,102,7),13:(13,1,102,7),14:(13,2,102,7),15:(13,2,102,7)}
    calls=[];original=SeriesEntry.calculator_at
    with patch.object(SeriesEntry,'calculator_at',lambda self,n,check:(calls.append(n),original(self,n,check))[1]):
        for cut,(start,count,price,at) in expected.items():
            out=response(item,cut,limit=1)
            r=out.structures[0]
            assert (r.nextSameColorStart,r.nextSameColorCount,r.trackingPriceExtreme,r.trackingPriceExtremeAt)==(
                DATES[start-1] if start else None,count,price if sign==1 else 200-price,DATES[at-1])
            assert r.status==('FINISHED' if cut==15 else 'FOLLOWING')
    assert calls==list(expected) and item.structure_records==frozen
    assert response(item,16,limit=1).structures==[]


@pytest.mark.parametrize('sign',[1,-1])
def test_rc105_current_color_flip_then_price_cancel_complete_internal_contract(sign):
    item=entry(values(T+[(103,100,-2)],sign));body=response(item,5).model_dump()
    assert [e['route'] for e in body['events'][-2:]]==['color_flip','structure_price_break']
    assert len(body['structures'])==1 and body['structures'][0]['status']=='DISAPPEARED'
    assert body['structures'][0]['formedAt']==body['structures'][0]['disappearedAt']==DATES[4]
    for fault in ('omit','order','duplicate','association','price'):
        bad=deepcopy(body)
        if fault=='omit':bad['events'].pop()
        elif fault=='order':bad['events'][-2:]=reversed(bad['events'][-2:])
        elif fault=='duplicate':bad['structures'].append(deepcopy(bad['structures'][0]))
        elif fault=='association':bad['events'][-1]['relatedStructureId']='wrong'
        else:bad['structures'][0]['trackingPriceExtreme']=102 if sign==1 else 98
        with pytest.raises((ValueError,ValidationError)):InternalXxmResponseDto.model_validate(bad)
