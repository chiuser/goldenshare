"""Independent inequalities for sealed real TOP prefixes; no forecast imports.

EMA recovery is an audited input producer, not the expected-domain solver.
Fractions below derive the conditions directly from LLD 29.4.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction as F
import json
from pathlib import Path
import time

from .acceptance import load_source, sha
from .cross_index_daily import read_unit, seal
from .top_activation_math import pair
from .top_activation_expectations import OUT, ROOT, SOURCE
from .bottom_history_acceptance import calendar_rows, future_slots
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection

K = F(28,351)
AP = F(7588,123201)


def meet(a,b):
    lo=max(a[0],b[0]);hi=min(a[1],b[1])
    lc=(a[2] if lo==a[0] else True) and (b[2] if lo==b[0] else True)
    hc=(a[3] if hi==a[1] else True) and (b[3] if hi==b[1] else True)
    return (lo,hi,lc,hc) if lo<hi or lo==hi and lc and hc else None


def minus(a,b):
    overlap=meet(a,b)
    if overlap is None:return [a]
    lo,hi,lc,hc=overlap
    result=[]
    for part in ((a[0],lo,a[2],not lc),(hi,a[1],not hc,a[3])):
        if part[0]<part[1] or part[0]==part[1] and part[2] and part[3]:result.append(part)
    return result


def interval(a):
    return dict(lower=pair(a[0]),upper=pair(a[1]),lowerInclusive=a[2],upperInclusive=a[3])


def entry_domains(context, projection):
    """All TOP first-entry inequalities; at most the original two refs."""
    w=context['wave'];refs=context['history']['1']
    if not refs or w['count']+1<2:return []
    b=F(projection.e12)*F(11,13)-F(projection.e26)*F(25,27)
    a0=F(projection.dea)
    lower=max(F(0),(max(F(0),a0)-b)/K)
    ranked=sorted(reversed(refs),key=lambda r:r['dif'],reverse=True)
    assigned=[]
    for ref in ranked:
        if F(ref['dif'])<=max(F(0),F(w['dif'])):continue
        price=max(F(refs[-1]['price']),F(ref['price']))
        lo=max(lower,price) if F(w['price'])<=price else lower
        hi=(F(ref['dif'])-b)/K
        if lo>=hi:continue
        pending=[(lo,hi,False,False)]
        for earlier in assigned:
            pending=[piece for part in pending for piece in minus(part,earlier['interval'])]
        assigned.extend(dict(interval=part,reference={k:ref[v] for k,v in
            [('startTime','start'),('endTime','end'),('price','price'),('dif','dif')]}) for part in pending)
    return assigned


def proof(row, projection, slots):
    ctx=row['candidateContext'];refs=ctx['history']['1'];w=ctx['wave']
    eligible=[r for r in refs if F(r['dif'])>max(F(0),F(w['dif']))]
    base=dict(period=row['period'],gate=row['gate'],through=row['through'],rows=row['rows'],
        originalFile=row['originalFile'],oldResultSha256=row['oldResultSha256'])
    if not eligible:
        return dict(base,classification='NO_ENTRY',activationRanges=[],status='NO_CANDIDATE',reasonCode='NO_ENTRY_RANGE',
            targetEndpoint=None,proof='D1>0 and max(current wave DIF,D1)<any available ref DIF cannot both hold',
            history=refs,currentWaveDif=w['dif'])
    assert row['period']!='day','Nonempty daily proof is outside the approved real sample scope'
    b=F(projection.e12)*F(11,13)-F(projection.e26)*F(25,27)
    b2=F(projection.e12)*F(121,169)-F(projection.e26)*F(625,729)
    a0=F(projection.dea);a1p=K/5;a1b=F(4,5)*a0+b/5
    domains=entry_domains(ctx,projection)
    if not domains:
        return dict(base,classification='NO_ENTRY',activationRanges=[],status='NO_CANDIDATE',reasonCode='NO_ENTRY_RANGE',
            targetEndpoint=None,projection=dict(e12=projection.e12,e26=projection.e26,dea=projection.dea),
            proof='Strict price, source color, positive current DIF and reference inequalities have empty intersection')
    routes=[]
    for domain in domains:
        lo,hi,lc,hc=domain['interval']
        maximum=AP*hi+b2
        # AP is positive; this proves D2(P,0)<0 at every P in the interval.
        # If equality at an excluded upper endpoint, all actual P remain <0.
        if maximum>0 or maximum==0 and hc:
            return dict(base,classification='PENDING',reason='Could not prove positive-C feasibility for the entire entry interval')
        ratio=F(str(row['gate']))/100
        routes.append(dict(entryDomain=interval(domain['interval']),reference=domain['reference'],
            secondAtZeroUpperBound=pair(maximum),
            colorFlip=dict(lowerC=[0,1],lowerInclusive=False,upperC=dict(p=pair((a1p-AP)/K),b=pair((a1b-b2)/K)),upperInclusive=False),
            difTurn=dict(lowerC=dict(op='max',values=[[0,1],dict(p=pair((a1p-AP)/K),b=pair((a1b-b2)/K))]),lowerInclusive=False,
                upperC=dict(p=pair(((1-ratio)*K-AP)/K),b=pair(((1-ratio)*b-b2)/K)),upperInclusive=True)))
    return dict(base,classification='NONEMPTY_SECOND_ENDPOINT',status='CONDITIONAL_ENTRY',reasonCode=None,
        activationEndpoint=slots[0],targetEndpoint=slots[1],barsAhead=2,
        projection=dict(e12=projection.e12,e26=projection.e26,dea=projection.dea),
        firstDif=dict(p=pair(K),b=pair(b)),secondDif=dict(p=pair(AP),c=pair(K),b=pair(b2)),
        ranges=routes,proof='First endpoint only activates; D2(P,0)<0 for every allowed P and D1>0, so a positive C exists at endpoint two')


def main():
    start=time.perf_counter();manifest=read_unit(OUT,'manifest');inventory=read_unit(OUT,'forecast_inventory')
    assert all(sha(ROOT/p)==value for p,value in {**manifest['sources'],**manifest['protected']}.items())
    before={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}
    calendars=[SOURCE/'sse_minute_calendar.json',ROOT/'reports/xxm_forecast_precheck_20261014/future_sse_calendar.json']
    identity=dict(tool=sha(Path(__file__)),contract='LLD29.4 independent Fraction inequalities',
        preparationManifestSha256=sha(OUT/'manifest.json'),inventorySha256=sha(OUT/'forecast_inventory.json'),
        calendars={str(p.relative_to(ROOT)):sha(p) for p in calendars},
        projectionProducerSha256=sha(ROOT/'src/biz/services/wealth/market/index_detail_xxm/projection.py'),
        inputRows=522,productChanged=False,forecastSolverUsed=False)
    old=read_unit(OUT,'real_math_manifest')
    if old is None:seal(OUT,'real_math_manifest',identity)
    else:assert old==identity
    calendar=calendar_rows(SOURCE);sources={};projections={};records=[];reused=0
    for period in ('day','m60','m90','m120'):
        rows=[r for r in inventory if r['period']==period and r['category']=='FIRST_TOP_DOMAIN']
        for gate in (.75,1.,1.2):
            name=f'independent_real_{period}_{gate}';old=read_unit(OUT,name)
            if old is not None:records.extend(old);reused+=1;continue
            values=[]
            for row in rows:
                if row['gate']!=gate:continue
                if time.perf_counter()-start>60:raise TimeoutError('Independent proof 60-second phase')
                ctx=row['candidateContext'];refs=ctx['history']['1'];w=ctx['wave']
                eligible=any(F(r['dif'])>max(F(0),F(w['dif'])) for r in refs)
                projection=None;slots=None
                if eligible:
                    if period not in sources:sources[period]=tuple(load_source(SOURCE,period))
                    key=(period,row['rows'])
                    if key not in projections:
                        bars=sources[period][:row['rows']];assert bars[-1].time==row['through']
                        projections[key]=recover_projection(bars,period,lambda:None)
                    projection=projections[key];slots=future_slots(calendar,period,row['through'])
                values.append(proof(row,projection,slots))
            seal(OUT,name,values);records.extend(values)
    assert len(records)==522 and len(projections)<=200
    unchanged=all(sha(OUT/name)==value for name,value in before.items())
    assert unchanged
    result=dict(status='INDEPENDENT_REAL_MATH_FROZEN',cases=len(records),reusedUnits=reused,
        classifications=dict(Counter(r['classification'] for r in records)),
        independentPrefixesRecovered=len(projections),allCasesProven=not any(r['classification']=='PENDING' for r in records),
        perPeriod={p:dict(Counter(r['classification'] for r in records if r['period']==p)) for p in ('day','m60','m90','m120')},
        originalFreezeUnchanged=unchanged,seconds=time.perf_counter()-start,
        limitations=['Analytical domains on recovered projection constants; actual float-root guard and DTO/display still need product validation',
            '693 retained forecasts remain original full response expectations; 522 changed forecasts use independent complete inequalities, not fabricated new response JSON',
            'New product, formal API, performance, daily nonempty P-C validation have not run'])
    old=read_unit(OUT,'real_math_summary')
    if old is None:seal(OUT,'real_math_summary',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
