"""Literal/Fraction oracle for R1 forecast. No original software claim."""
from fractions import Fraction as F
import math

import pytest

from scripts.research.index_market.tests.test_xxm_reference_rescue import prepared
from src.biz.services.wealth.market.index_detail_xxm.forecast_paths import (
    cells, solve_next_bar_outcomes, partition_prefix_paths, validate_path_options,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval, as_interval
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState


def at(result,p):
    owners=[v for v in result['branches'] if as_interval(v['priceRange']).contains(p)]
    assert len(owners)==1
    return owners[0]


def test_disjoint_cells_include_singletons_unbounded_tail_and_open_ends():
    parts=list(cells(Interval(),[0,1,2]))
    for p in (math.nextafter(0,1),.5,1,math.nextafter(1,0),math.nextafter(1,2),2,100):
        assert sum(v.contains(p) for v in parts)==1
    assert not any(v.contains(0) for v in parts)
    assert list(cells(Interval(1,1,True,True),[1]))==[Interval(1,1,True,True)]


@pytest.mark.parametrize('period', ['day','m60','m90','m120'])
def test_next_bar_non_monotone_cancel_and_switch_ranges_with_fraction_oracle(period):
    c=prepared();c.period=period
    # Date-only bars are deliberately kept on the day object. Minute identities
    # use actual period endpoints, independently of hypothetical indicator math.
    if period!='day':
        from datetime import datetime,timedelta
        from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
        from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
        from scripts.research.index_market.tests.test_xxm_reference_rescue import VALUES
        c=XxmCalculator(period=period,source_identity='literal')
        for i,(price,dif,hist) in enumerate(VALUES):
            stamp=f'2020-01-{i+1:02}T15:00:00+08:00'
            c.step(XxmBar(stamp,price,dif,dif-hist/2,hist))
    stamp='2020-01-07' if period=='day' else '2020-01-07T15:00:00+08:00'
    projection=ProjectionState(229,232,-2)
    saved=c.snapshot();result=solve_next_bar_outcomes(c,projection,stamp)
    # Independent exact recurrence and strict price qualification, not helper
    # output. -20 is older ref, -5 current; older price90, current low98.
    for p,expected in [(10,'CANCELLED'),(89,'REFERENCE_SWITCHED'),(95,'CANCELLED'),(210,'PRESERVED'),(230,'STRUCTURE_CONFIRMED'),(300,'STRUCTURE_CONFIRMED')]:
        d=F(229)*F(11,13)-F(232)*F(25,27)+F(p)*(F(2,13)-F(2,27))
        if expected=='REFERENCE_SWITCHED':assert -20<d<-5 and p<90
        if p==10:assert d<-20
        if p==95:assert d<-5 and p>=90
        assert at(result,p)['outcome']==expected,(period,p,float(d))
    for branch in result['branches']:
        r=as_interval(branch['priceRange'])
        for edge in (r.lo,r.hi):
            if edge is None or edge<=0:continue
            for p in (math.nextafter(edge,0),edge,math.nextafter(edge,math.inf)):
                at(result,p)
    assert c.snapshot()==saved
    assert at(result,89)['reference']['dif']==-20


def test_fixed_flat_path_reselects_without_confirmation_on_switch_bar():
    c=prepared()
    # Earlier price was already below older ref; current close now95. The
    # literal saved previous DIF is kept -3; flat95 can now break the weak ref.
    c.wave.price=89
    projection=ProjectionState(229,232,-2)
    p=95
    parts,exclusions,coeffs=partition_prefix_paths(c,projection,Interval(p,p,True,True),c.reference.reference(),['2020-01-07'])
    # The complete path may not have a target solution under some projections;
    # when it has one, its only switch is the intermediate completed bar.
    assert parts
    assert all(len(v.path.transitions)==1 and v.path.final['dif']==-20 for v in parts)
    assert all(v.path.transitions[0]['endpoint']=='2020-01-07' for v in parts)


def test_waiting_activation_is_fixed_then_variable_flat_path_can_switch_later():
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    from scripts.research.index_market.tests.test_xxm_reference_rescue import VALUES
    from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
    c=XxmCalculator(period='m60',source_identity='literal-wait')
    for i,(price,dif,hist) in enumerate([*VALUES,(101,-2.95,-2),(101,-3.1,-2)],1):
        c.step(XxmBar(f'2020-01-{i:02}T15:00:00+08:00',price,dif,dif-hist/2,hist))
    assert c.pending_rearm and c.state=='NONE'
    projection=ProjectionState(106.9,110,-2.1)
    stamps=['2020-01-09T10:30:00+08:00','2020-01-09T11:30:00+08:00','2020-01-09T14:00:00+08:00']
    saved=c.snapshot()
    initial=c.pending_rearm['referenceWave']
    ref=dict(startTime=initial['start'],endTime=initial['end'],price=initial['price'],dif=initial['dif'])
    parts,excluded,coeffs=partition_prefix_paths(c,projection,Interval(88.5,89.5,True,True),ref,stamps[:2])
    assert parts and all(v.path.initial['dif']==-5 and v.path.final['dif']==-20 for v in parts)
    assert all(v.path.transitions[0]['endpoint']==stamps[1] for v in parts)
    # Independent rational recurrences for P=89: saved weak ref is valid on
    # first activation, broken on the second; C110 then turns DIF upward.
    e12,e26=F(1069,10),F(110)
    ds=[]
    for price in (89,89,110):
        e12=e12*F(11,13)+F(price)*F(2,13)
        e26=e26*F(25,27)+F(price)*F(2,27)
        ds.append(e12-e26)
    assert -5<ds[0] and -20<ds[1]<-5 and ds[2]-ds[1]>=abs(ds[1])/100
    part=next(v for v in parts if v.domain.contains(89))
    assert validate_path_options(c,projection,stamps,89,110,'dif_turn',part.path)
    for p in (88.5,88.75,89,89.25,89.5):
        owners=[v for v in parts if v.domain.contains(p)]+[v for v in excluded if v['interval'].contains(p)]
        assert len(owners)==1
    assert c.snapshot()==saved
