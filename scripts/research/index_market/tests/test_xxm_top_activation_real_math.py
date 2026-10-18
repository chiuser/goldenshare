from fractions import Fraction as F

from scripts.research.index_market.xxm.top_activation_real_math import meet, minus, proof, entry_domains
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState


def test_interval_subtraction_preserves_strict_boundary_and_single_point():
    a=(F(0),F(10),False,False);b=(F(3),F(7),False,False)
    assert minus(a,b)==[(F(0),F(3),False,True),(F(7),F(10),True,False)]
    assert meet(a,(F(10),F(11),True,True)) is None
    assert meet((F(3),F(3),True,True),a)==(F(3),F(3),True,True)
    assert minus(a,(F(0),F(10),True,True))==[]


def test_real_math_matches_independent_lld_literal_without_forecast_solver():
    ref=dict(sign=1,start='2020-01-01',end='2020-01-01',count=1,price=100.,dif=10.,price_at='2020-01-01',dif_at='2020-01-01')
    ctx=dict(wave=dict(count=1,price=105.,dif=2.),history={'1':[ref]})
    row=dict(period='m90',gate=1.,through='2026-10-13T15:00:00+08:00',rows=3,originalFile='literal',oldResultSha256='literal',candidateContext=ctx)
    projection=ProjectionState(102,100,-2)
    domains=entry_domains(ctx,projection)
    assert [v['interval'] for v in domains]==[(F(1103,14),F(1429,7),False,False)]
    result=proof(row,projection,['first','second'])
    assert result['classification']=='NONEMPTY_SECOND_ENDPOINT' and result['targetEndpoint']=='second'
    d=result['ranges'][0]
    assert d['colorFlip']['upperC']=={'p':[-1004,1755],'b':[1516499,12285]}
    # Equality to a ref invalidates that ref; a negative-only history has no entry.
    ctx['wave']['dif']=10.
    assert proof(row,None,None)['classification']=='NO_ENTRY'
    ctx['wave']['dif']=-2.;ctx['history']['1'][0]['dif']=-1.
    assert proof(row,None,None)['classification']=='NO_ENTRY'


def test_two_original_refs_keep_strongest_priority_and_exact_price_equality():
    # LLD's literal projection gives D=(28P-2206)/351. The older, stronger
    # ref requires P>120; the recent ref already passes its price gate but
    # requires D<5. At P=120 only the recent ref qualifies, hence closed 120.
    ctx=dict(wave=dict(count=1,price=105.,dif=2.),history={'1':[
        dict(start='older',end='older',price=120.,dif=10.),
        dict(start='recent',end='recent',price=100.,dif=5.)]})
    values=entry_domains(ctx,ProjectionState(102,100,-2))
    assert [(v['reference']['startTime'],v['interval']) for v in values]==[
        ('older',(F(120),F(1429,7),False,False)),
        ('recent',(F(1103,14),F(120),False,True))]
    # A segment that already exceeded 120 does not need the next price to
    # exceed it again. Equal DIF ranks choose the more recent original ref.
    ctx['wave']['price']=121.
    assert len(entry_domains(ctx,ProjectionState(102,100,-2)))==1
    ctx['wave']['price']=105.;ctx['history']['1'][1]['dif']=10.
    assert [v['reference']['startTime'] for v in entry_domains(ctx,ProjectionState(102,100,-2))]==['recent']
