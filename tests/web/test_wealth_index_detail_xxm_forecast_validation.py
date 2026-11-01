"""P3 F01-F05: literal bad facts, producer inputs, and independent identity golds.

M1's six source bars/EMA come from LLD §5.4.4. Assigning protocol IDs to a
varied input below is fixture construction only; numeric/time expectations are
literal, and the identity function has separate independently hashed JSON golds.
"""
from copy import deepcopy
import hashlib
import json

import pytest
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import (
    ForecastResponseDto, ForecastDebugResponseDto, InternalForecastResponseDto,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_identity import (
    forecast_result_id, forecast_condition_id,
)
from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_forecast_response
from tests.web.test_wealth_index_detail_xxm_forecast_api import m1, source_db, read
from sqlalchemy.orm import Session


@pytest.fixture
def full_payload(m1, source_db):
    service, _ = m1
    with Session(source_db) as session:
        public = read(service, session)
    assert public['ordinaryState'] == 'DULL' and public['direction'] == 'BOTTOM'
    return next(v[0].model_dump() for k,v in service.source.cache.entries.items() if k[0]=='forecast')


def assign_ids(payload):
    payload['forecastId'] = forecast_result_id(payload)
    for c in payload['conditions']:
        c['id'] = forecast_condition_id(payload['forecastId'],c['outcome'])
    for c in payload['structureFollowConditions']:
        c['id'] = forecast_condition_id(payload['forecastId'],c['outcome'],c['relatedStructureId'])
    return payload


def following_payload(payload):
    # Independent old TOP facts can coexist with a current BOTTOM relation.
    payload=deepcopy(payload)
    payload['structureFollowConditions']=[dict(
        id='0'*64,outcome='SIGNAL_DISAPPEARED',relatedStructureId='old-literal-top',direction='TOP',
        originWave=dict(sign=1,start='2023-01-03',end='2023-01-05',count=1,price=103,dif=100,
                        price_at='2023-01-03',dif_at='2023-01-05'),
        nextSameColorStart=None,nextSameColorCount=0,
        priceRanges=[dict(lower=103,upper=None,lowerInclusive=False,upperInclusive=False,displayLower=104,displayUpper=None)],
        precisionRanges=[],predicates=[dict(left=dict(op='affine',pCoefficient=0,cCoefficient=1,constant=0),
                                            op='gt',right=dict(op='affine',pCoefficient=0,cCoefficient=0,constant=103))])]
    return assign_ids(payload)


@pytest.mark.parametrize('bad',[True,False,1.0,'1',0,2])
def test_f01_bar_count_rejected_before_literal_conversion(full_payload,bad):
    normal=project_forecast_response(InternalForecastResponseDto.model_validate(full_payload),debug=False).model_dump()
    normal['barsAhead']=bad
    with pytest.raises(ValueError):ForecastResponseDto.model_validate(normal)
    assert ForecastResponseDto.model_validate(dict(normal,barsAhead=1)).barsAhead==1


@pytest.mark.parametrize('field,value',[
    ('count',0),('count',-1),('count',True),('count',1.5),('sign',0),('sign',True),
    ('price',0),('price',-1),('dif',float('inf')),('dif',float('nan')),
    ('price_at','2023-01-06'),('dif_at','2023-01-02'),('start','2023-01-06'),
])
def test_f02_bad_native_wave_rejected_before_both_public_modes(full_payload,field,value):
    raw=following_payload(full_payload)
    raw['structureFollowConditions'][0]['originWave'][field]=value
    if type(value) is not float or value==value and abs(value)!=float('inf'):
        assign_ids(raw)  # A matching ID cannot make the bad Wave legal.
    with pytest.raises(ValueError):InternalForecastResponseDto.model_validate(raw)


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_f02_single_colored_bar_and_wire_native_roundtrip_remain_valid(full_payload,period,sign):
    raw=following_payload(full_payload)
    if sign==-1:
        old=raw['structureFollowConditions'][0]
        old.update(direction='BOTTOM',nextSameColorStart='2023-01-09',nextSameColorCount=2)
        old['originWave'].update(sign=-1,price=80,dif=-100)
        old['priceRanges']=[dict(lower=0,upper=80,lowerInclusive=False,upperInclusive=False,displayLower=1,displayUpper=79)]
        old['predicates'][0].update(op='lt',right=dict(op='affine',pCoefficient=0,cCoefficient=0,constant=80))
    raw['period']=period
    if period!='day':
        def stamps(v):
            if isinstance(v,dict):return {k:stamps(x) for k,x in v.items()}
            if isinstance(v,list):return [stamps(x) for x in v]
            if isinstance(v,str) and len(v)==10 and v.startswith('2023-'):return v+'T15:00:00+08:00'
            return v
        raw=stamps(raw);raw['precisionPolicy']='full_float'
    raw=assign_ids(raw)
    internal=InternalForecastResponseDto.model_validate(raw)
    normal=project_forecast_response(internal,debug=False).model_dump()
    debug=project_forecast_response(internal,debug=True).model_dump()
    assert normal=={k:v for k,v in debug.items() if k!='debug'}
    assert debug['debug']['structureFollowConditions'][0]['originWave']['count']==1
    assert ForecastDebugResponseDto.model_validate(debug).forecastId==normal['forecastId']
    assert internal.structureFollowConditions[0].originWave.price==(103 if sign==1 else 80)


@pytest.mark.parametrize('where',['forecast','condition','fact','follow_id','follow_relation'])
def test_f04_wrong_but_well_formed_ids_and_changed_facts_rejected(full_payload,where):
    raw=following_payload(full_payload)
    if where=='forecast':raw['forecastId']='f'*64
    elif where=='condition':raw['conditions'][0]['id']='f'*64
    elif where=='fact':raw['references']['nearest']['price']+=1
    elif where=='follow_id':raw['structureFollowConditions'][0]['id']='f'*64
    else:raw['structureFollowConditions'][0]['relatedStructureId']='wrong-old-top'
    with pytest.raises(ValueError):InternalForecastResponseDto.model_validate(raw)


def test_f03_numeric_and_presentation_changes_do_not_invent_new_facts(full_payload):
    raw=deepcopy(full_payload);expected=raw['forecastId']
    raw['references']['nearest']['price']=90
    assert forecast_result_id(raw)==expected
    raw['references']['nearest']['price']=90.0
    assert forecast_result_id(raw)==expected
    raw['display']['conditionsText']='仅改显示';raw['applicabilityText']='仅改说明'
    raw['conditions'][0]['priceRanges'][0]['displayLower']=12345
    assert forecast_result_id(raw)==expected
    for mutate in [lambda p:p.update(sourceInputId='different source'),
                   lambda p:p['references']['nearest'].update(price=91),
                   lambda p:p.update(computedThrough='2023-01-09')]:
        bad=deepcopy(raw);mutate(bad);assert forecast_result_id(bad)!=expected
    assert InternalForecastResponseDto.model_validate(full_payload).forecastId==expected


def test_f03_condition_hash_uses_independent_literal_json_and_source_is_immutable():
    # Exact sorted JSON fixed independently from LLD §6.8.1; no product helper
    # builds the expected bytes.
    canonical='{"forecastId":"'+'f'*64+'","outcome":"STRUCTURE_FORMED"}'
    expected=hashlib.sha256(canonical.encode()).hexdigest()
    assert forecast_condition_id('f'*64,'STRUCTURE_FORMED')==expected
    canonical='{"forecastId":"'+'f'*64+'","outcome":"SIGNAL_DISAPPEARED","relatedStructureId":"old-top"}'
    assert forecast_condition_id('f'*64,'SIGNAL_DISAPPEARED','old-top')==hashlib.sha256(canonical.encode()).hexdigest()


def test_f03_result_hash_matches_independent_empty_literal():
    canonical='{"barsAhead":null,"calendarInputId":null,"computedThrough":null,"conditions":[],"dataStatus":"EMPTY","detectorSpecHash":"a","direction":null,"farEvaluated":false,"forecastSpecHash":"b","forecastVersion":"v","mode":"LATEST","nearestDecision":{"reason":null,"status":"NOT_EVALUATED"},"ordinaryState":null,"period":"day","precisionPolicy":"rounded3_guarded","precisionRanges":[],"reasonCode":"SOURCE_EMPTY","references":{"farther":null,"nearest":null},"requestedAsOf":null,"selectedReference":null,"sourceInputId":null,"status":"EMPTY","structureFollowConditions":[],"targetEndpoint":null,"tsCode":"000001.SH"}'
    raw=json.loads(canonical);original=deepcopy(raw)
    assert forecast_result_id(raw)==hashlib.sha256(canonical.encode()).hexdigest()
    assert forecast_result_id(dict(reversed(list(raw.items()))))==forecast_result_id(raw)
    assert raw==original


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_forecast_projection_does_not_rebuild_internal(full_payload, debug):
    from unittest.mock import patch

    internal = InternalForecastResponseDto.model_validate(following_payload(full_payload))
    before = internal.model_dump()
    with patch.object(InternalForecastResponseDto, 'model_validate', wraps=InternalForecastResponseDto.model_validate) as validate:
        public = project_forecast_response(internal, debug=debug)
    assert validate.call_count == 0
    assert public.ordinaryState == 'DULL' and public.direction == 'BOTTOM'
    assert public.targetEndpoint == '2023-01-11' and public.barsAhead == 1
    assert internal.model_dump() == before


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('damaged', [False, True])
def test_p4_batch1_f04_cached_nested_model_is_revalidated(full_payload, m1, source_db, monkeypatch, debug, damaged):
    # F04's guard belongs to the real cache -> query boundary, before projection.
    from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as query
    from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmQueryError

    service, _ = m1
    cache = service.source.cache
    key = next(k for k in cache.entries if k[0] == 'forecast')
    value = InternalForecastResponseDto.model_validate(following_payload(full_payload))
    cache.put(key, value)
    if damaged:
        value.structureFollowConditions[0].originWave.count = 0
    old_members = dict(cache.entries)
    monkeypatch.setattr(query, 'forecast', lambda *a, **kw: pytest.fail('cache must not be solved again'))
    monkeypatch.setattr(cache, 'put_forecast', lambda *a, **kw: pytest.fail('cache hit must not publish a substitute'))
    if damaged:
        monkeypatch.setattr(query, 'project_forecast_response', lambda *a, **kw: pytest.fail('bad cache reached projection'))
    with Session(source_db) as session:
        if damaged:
            with pytest.raises(XxmQueryError) as error:
                read(service, session, debug=debug)
            assert error.value.code == 'XXM_SOURCE_CONTRACT_INVALID'
        else:
            public = read(service, session, debug=debug)
            assert public['forecastId'] == value.forecastId and public['ordinaryState'] == 'DULL'
            if debug:
                assert public['debug']['structureFollowConditions'][0]['originWave']['count'] == 1
    assert set(cache.entries) == set(old_members)
    assert all(cache.entries[k][0] is old_members[k][0] and cache.entries[k][1] == old_members[k][1] for k in old_members)
    assert value.structureFollowConditions[0].originWave.count == (0 if damaged else 1)


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_forecast_projection_requires_internal_model_and_strict_debug(full_payload, debug):
    internal = InternalForecastResponseDto.model_validate(full_payload)
    ordinary = project_forecast_response(internal, debug=False)
    detailed = project_forecast_response(internal, debug=True)
    assert ordinary.model_dump() == {k: v for k, v in detailed.model_dump().items() if k != 'debug'}
    for bad in (internal.model_dump(), ordinary, detailed, None, object()):
        with pytest.raises(ValueError, match='InternalForecastResponseDto'):
            project_forecast_response(bad, debug=debug)
    for bad_debug in (0, 1, None, 'true'):
        with pytest.raises(ValueError, match='Debug must be a boolean'):
            project_forecast_response(internal, debug=bad_debug)
        with pytest.raises(ValueError, match='Debug must be a boolean'):
            project_forecast_response({}, debug=bad_debug)


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_forecast_projection_keeps_dynamic_audit_wrapper(full_payload, debug):
    from scripts.research.index_market import xxm_page_request_audit as audit
    from scripts.research.index_market.tests.test_xxm_p4_audit_tools import group
    from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as query

    internal = InternalForecastResponseDto.model_validate(following_payload(full_payload))
    before = internal.model_dump()
    original = query.project_forecast_response
    collector = audit.AuditCollector(group())
    assert audit._REQUEST_ID.get() is None
    with audit._observe(collector):
        assert query.project_forecast_response is not original
        public = query.project_forecast_response(internal, debug=debug)
        assert public.targetEndpoint == '2023-01-11' and public.ordinaryState == 'DULL'
        if debug:
            assert public.debug.structureFollowConditions[0].originWave.count == 1
    assert query.project_forecast_response is original
    assert internal.model_dump() == before and collector.requests == {}


def test_f05_normal_identity_format_is_closed_but_does_not_require_debug(full_payload):
    normal=project_forecast_response(InternalForecastResponseDto.model_validate(full_payload),debug=False).model_dump()
    for value in ['',True,'wrong','G'*64,'f'*63,'f'*64+'\n']:
        with pytest.raises(ValueError):ForecastResponseDto.model_validate(dict(normal,forecastId=value))
    assert ForecastResponseDto.model_validate(normal).status=='READY'


def test_f03_zero_sign_chinese_and_counts_have_explicit_identity_semantics(full_payload):
    raw=deepcopy(full_payload)
    expr=raw['conditions'][0]['predicates'][0]['left']
    expr['dea']=0
    positive=forecast_result_id(raw)
    expr['dea']=-0.0
    assert forecast_result_id(raw)==positive
    raw['nearestDecision']['reason']='近参照有效，尚未计算远参照。'
    assert forecast_result_id(raw)!=positive
    initial=following_payload(full_payload)
    changed=deepcopy(initial);changed['structureFollowConditions'][0]['originWave']['count']=2
    assert forecast_result_id(initial)!=forecast_result_id(changed)
    initial['conditions'][0]['predicates']=[dict(
        left=dict(op='affine',pCoefficient=False,cCoefficient=0,constant=0),op='eq',
        right=dict(op='affine',pCoefficient=0,cCoefficient=0,constant=0))]
    with pytest.raises(ValueError):forecast_result_id(initial)
