"""R2 product checks against pre-development, independent literals/files."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
from fractions import Fraction as F
import json
import math

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec, MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import solve_entry_ranges, stable_reference_on_band
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import activation_signature
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from scripts.research.index_market.xxm.frozen_inputs import expected_unit, assert_expected_recognition
from scripts.research.index_market.xxm.acceptance import load_source
from scripts.research.index_market.xxm.top_daily_ambiguity import DAILY


def literal(values,period='day',gate=1.):
    c=XxmCalculator(period=period,source_identity='r2-literal',spec=XxmSpec(dif_turn_pct=gate))
    for n,(p,d,h) in enumerate(values):
        t=(date(2020,1,2)+timedelta(days=n)).isoformat()
        if period!='day':t+='T15:00:00+08:00'
        c.step(XxmBar(t,p,d,d-h/2,h))
    return c


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('dif',[0.,-0.,-.001,-1.,1e-12,.001,1.])
def test_first_top_uses_current_value_and_rejects_zero_without_epsilon(period,dif):
    c=literal([(100,10,2),(99,0,-2),(105,2,8)],period)
    stamp='2020-01-05' if period=='day' else '2020-01-05T15:00:00+08:00'
    step=c.step(XxmBar(stamp,106,dif,dif-4,8))
    assert c.state==('DULL' if dif>0 else 'NONE')
    assert bool(step.events)==(dif>0)
    assert c.processed==4 and c.previous.dif==dif and c.wave.dif==2
    if dif<=0:
        stamp='2020-01-06' if period=='day' else '2020-01-06T15:00:00+08:00'
        assert c.step(XxmBar(stamp,106,.1,-3.9,8)).events[0]['route']=='activation'


@pytest.mark.parametrize('gate',[.75,1.,1.2])
def test_daily_2020_complete_frozen_steps_and_hashes(gate):
    assert_expected_recognition(load_source(DAILY,'day'),'daily2020','day',gate)
    hashes={.75:'ddc241ad701a483a0e1659ed1a70ef46e695499199776c13694a29ddda3c1a04',
            1.:'6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d',
            1.2:'81992335d6bd197e56cc2ff6d02b35fe46ddc61cfbeb282fb3e5e375bd3d2021'}
    assert XxmSpec(dif_turn_pct=gate).spec_hash==hashes[gate]
    assert FORECAST_SPEC.spec_hash=='add5e3636e6972e267bdda81c05e0e864f600f9e67d658b6a560445e39dda6d8'
    with pytest.raises(ValueError):XxmSpec(algorithm_version='xxm-direction-v0.1-r1')


def test_old_snapshot_rejected_atomically_and_bottom_with_positive_dif_still_activates():
    c=literal([(100,10,2),(99,0,-2),(105,2,8)]);before=c.snapshot();old=deepcopy(before)
    old['specHash']='533a9b441e49c1b2c076482ad6815f61e49494f63ec2c8c922a03d868e4ce730'
    with pytest.raises(ValueError):c.restore(old)
    assert c.snapshot()==before
    bottom=literal([(100,1,-2),(110,5,2),(95,2,-2),(94,2,-2)])
    assert bottom.state=='DULL' and bottom.reference.dif==1 and bottom.previous.dif>0


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_independent_first_entry_prices_and_existing_negative_dif_structure(period):
    spec=expected_unit('independent_math');c=literal(spec['prefix'],period);projection=ProjectionState(**spec['projection']);before=c.snapshot()
    stamp='2020-01-05' if period=='day' else '2020-01-05T15:00:00+08:00'
    result=solve_entry_ranges(c,projection,stamp)
    for price,active in [(60,False),(100,True),(210,False)]:
        assert isinstance(activation_signature(c,projection,price,stamp),dict)==active
        owns=[v for v in result['ranges']+result['exclusions'] if Interval(v['priceRange']['lower'] or 0,v['priceRange']['upper'],v['priceRange']['lowerInclusive'],v['priceRange']['upperInclusive']).contains(price)]
        assert len(owns)==1
        if price==60:assert owns[0]['reason']=='CURRENT_DIF_NOT_POSITIVE'
    assert c.snapshot()==before
    c=literal(spec['existingDull']['prefix'],period);p=ProjectionState(**spec['existingDull']['projection'])
    bar,_=p.project(40,'2020-01-09' if period=='day' else '2020-01-09T15:00:00+08:00',period)
    step=c.step(bar)
    assert any(e['type']=='STRUCTURE' and e['route']=='color_flip' and e['direction']=='TOP' for e in step.events)


def test_daily_positive_source_rounding_not_conservative_floor_and_zero_boundary():
    c=literal([(100,10,2),(99,0,-2),(105,2,8)])
    # E12=E26=100, DEA=-2 gives D(P)=28/351*(P-100).
    # Raw .0006 rounds to source .001. The old floor-to-.001 is zero.
    p=ProjectionState(100,100,-2);at=lambda d:100+float(F(351,28))*d
    ref=c.history[1][0].reference()
    assert stable_reference_on_band(c,p,Interval(at(.0006),at(.00061),True,True),ref)
    stamp='2020-01-05'
    assert activation_signature(c,p,at(.0004),stamp) is None
    assert isinstance(activation_signature(c,p,at(.0006),stamp),dict)
    assert activation_signature(c,p,at(.0005),stamp)=='PRECISION_UNRESOLVED'


def test_minute_zero_root_neighbors_are_never_certain_wrong_side_ranges():
    c=literal([(100,10,2),(99,0,-2),(105,2,8)],'m90');p=ProjectionState(102,100,-2)
    r=solve_entry_ranges(c,p,'2020-01-05T15:00:00+08:00');root=float(F(1103,14))
    for price in (math.nextafter(root,0),root,math.nextafter(root,math.inf),root-.001,root+.001):
        owner=[v for v in r['ranges']+r['exclusions'] if Interval(v['priceRange']['lower'] or 0,v['priceRange']['upper'],v['priceRange']['lowerInclusive'],v['priceRange']['upperInclusive']).contains(price)]
        assert len(owner)==1
        hit=activation_signature(c,p,price,'2020-01-05T15:00:00+08:00')
        if 'reference' in owner[0]:assert isinstance(hit,dict)
        elif owner[0]['reason']!='PRECISION_UNRESOLVED':assert hit is None


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_rejected_first_top_still_emits_original_historical_price_break(period):
    # LLD26.5(6), written before development: structure at fifth bar locks102.5.
    c=literal([(100,10,2),(99,0,-2),(101,2,2),(102,1,2),(102.5,-2,2),
               (101,-3,-2),(102,-2,2)],period)
    stamp='2020-01-09' if period=='day' else '2020-01-09T15:00:00+08:00'
    step=c.step(XxmBar(stamp,103,-1,-2,2))
    assert c.state=='NONE' and c.reference is None and c.processed==8
    assert c.previous.time==stamp and c.wave.count==2
    assert [(e['type'],e['direction'],e['route']) for e in step.events]==[
        ('RESEARCH_HISTORICAL_WITHDRAWAL','TOP','historical_price_break')]
    assert step.histories[0]['confirmedAt'].startswith('2020-01-06')
    assert step.events[0]['relatedTopHistoryId']==step.histories[0]['id']
