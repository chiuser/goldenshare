"""Read-only M0 probe. Uses frozen prices and the current production detector.
No API, cache, database, Lake, application code, or real event ledger writes.
"""
from pathlib import Path
from datetime import date, datetime, time as daytime, timedelta
from dataclasses import asdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import csv, hashlib, json, math, sys, time
sys.path.insert(0, '/Users/congming/github/goldenshare')
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS, CN_ZONE, assert_continuous

ROOT=Path('/Users/congming/github/goldenshare')
SOURCE=ROOT/'reports/xxm_source_audit_20261013_213852'
OUT=ROOT/'reports/xxm_forecast_precheck_20261014'
PERIODS=['day','m60','m90','m120']
Q=Decimal('0.0001')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def encode(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,default=str)
calendar=json.loads((OUT/'future_sse_calendar.json').read_text())
past=json.loads((SOURCE/'sse_minute_calendar.json').read_text())
days={r['trade_date']:r['is_open'] for r in past+calendar['rows']}
open_days=tuple(date.fromisoformat(k) for k,v in sorted(days.items()) if v)
for i in range(92):
    assert (date(2026,10,1)+timedelta(days=i)).isoformat() in days

def future(period,asof,n=20):
    slots=(daytime(15),) if period=='day' else ENDPOINTS[int(period[1:])]
    result=[]
    for d in open_days:
        if d.isoformat()<asof[:10]: continue
        for t in slots:
            stamp=d.isoformat() if period=='day' else datetime.combine(d,t,CN_ZONE).isoformat()
            if stamp>asof: result.append(stamp)
            if len(result)==n: return result
    raise ValueError('CALENDAR_COVERAGE_INSUFFICIENT')

def load(period):
    name='daily_source.csv' if period=='day' else f'minute_{period[1:]}_source.csv'
    path=SOURCE/name
    manifest=json.loads((SOURCE/'manifest.json').read_text())
    expected=next(v['sha256'] for v in manifest['files'] if v['name']==name)
    assert digest(path)==expected
    bars=[]
    with path.open(newline='') as f:
        for r in csv.DictReader(f):
            assert r['ts_code']=='000001.SH'
            if period=='day':
                bar=XxmBar(r['trade_date'],float(r['close']),float(r['macd_dif_bfq']),float(r['macd_dea_bfq']),float(r['macd_bfq']))
            else:
                assert int(r['freq'])==int(period[1:])
                bar=XxmBar(r['trade_time'].replace(' ','T')+'+08:00',float(r['close']),float(r['macd_dif']),float(r['macd_dea']),float(r['macd']))
            bar.validate(period);bars.append(bar)
    assert_continuous(tuple(bars),period=period,open_dates=open_days)
    return bars, {'path':str(path.relative_to(ROOT)),'sha256':expected,'count':len(bars),'through':bars[-1].time}

def rebuild(bars,period):
    c=XxmCalculator(period=period,source_identity='M0-frozen-prefix')
    e12=e26=bars[0].close;a=0.;errors=[]
    for b in bars:
        e12=e12*11/13+b.close*2/13;e26=e26*25/27+b.close*2/27
        d=e12-e26;a=.8*a+.2*d;h=2*(d-a)
        errors.append([abs(d-b.dif),abs(a-b.dea),abs(h-b.hist)])
        c.step(b)
    assert len(errors)>=250
    maxima=[max(row[j] for row in errors[-250:]) for j in range(3)]
    tol=.0005 if period=='day' else 1e-8
    assert all(x<=tol for x in maxima), (period,maxima)
    return c,(e12,e26,a),maxima

def project(ema,close,stamp,period):
    x,y,a=ema
    x=x*11/13+close*2/13;y=y*25/27+close*2/27
    d=x-y;a=.8*a+.2*d;h=2*(d-a)
    values=[round(v,3) for v in (d,a,h)] if period=='day' else [d,a,h]
    return XxmBar(stamp,close,*values),(x,y,a)

def clone(c):
    new=XxmCalculator(period=c.period,source_identity=c.source_identity);new.restore(c.snapshot());return new

def event_at(c,ema,close,stamp):
    new=clone(c);bar,_=project(ema,close,stamp,c.period);step=new.step(bar)
    sign=c.wave.sign if c.wave else 0
    desired='TOP' if sign==1 else 'BOTTOM'
    return next((e for e in step.events if e['type']=='STRUCTURE' and e['direction']==desired),None)

def grid_inside(v,lower):
    if v is None: return None
    # Move away from floating / daily rounding ties before conservative display.
    x=Decimal(str(v))+ (Decimal('0.0000001') if lower else -Decimal('0.0000001'))
    return float(x.quantize(Q,rounding=ROUND_CEILING if lower else ROUND_FLOOR))

def solve(c,ema,stamp):
    if c.state!='DULL' or c.reference is None or not c.wave: return [],[]
    x,y,a=ema;k=2/13-2/27;b=x*11/13-y*25/27
    prev=c.previous.dif;gate=abs(prev)*MAIN_SPEC.dif_turn_pct/100
    d_targets=[c.reference.dif,prev,prev-c.wave.sign*gate,c.wave.dif,0.]
    cuts=[0.]
    if c.period=='day':
        for target in d_targets:
            base=math.floor(target*1000)
            cuts.extend(((i+.5)/1000-b)/k for i in range(base-2,base+3))
        cuts.extend(((a+h/1.6)-b)/k for h in [-.0005,0.,.0005])
    else:
        cuts.extend((v-b)/k for v in d_targets)
        cuts.append((a-b)/k)
    cuts=sorted(set(v for v in cuts if v>=0 and math.isfinite(v)))
    probes=[];intervals=[]
    for pos,lo in enumerate(cuts):
        hi=cuts[pos+1] if pos+1<len(cuts) else None
        mid=(lo+hi)/2 if hi is not None else lo+max(1.,abs(lo)*.1)
        if mid<=0: continue
        ev=event_at(c,ema,mid,stamp)
        if not ev: continue
        low=grid_inside(lo,True);high=grid_inside(hi,False)
        if high is not None and low>high: continue
        candidate={'rawLower':lo,'rawUpper':hi,'displayLower':low,'displayUpper':high,'route':ev['route']}
        points=[low,mid,lo+(mid-lo)*.25,mid+( (hi if hi is not None else mid*1.2)-mid)*.75]
        if high is not None: points.append(high)
        for price in points:
            got=event_at(c,ema,price,stamp)
            assert got is not None,(c.period,candidate,price)
            probes.append({'close':price,'structure':True,'route':got['route']})
        # Adjacent successful branch cells may be joined only if the separating
        # exact float input also passes. Zero-histogram holes must stay separate.
        if intervals and intervals[-1]['rawUpper']==lo and intervals[-1]['route']==ev['route'] and event_at(c,ema,lo,stamp):
            intervals[-1].update(rawUpper=hi,displayUpper=high)
        else: intervals.append(candidate)
    boundaries=[]
    for cut in cuts[1:]:
        eps=max(1e-6,abs(cut)*1e-10)
        values=[]
        for v in [cut-eps,cut,cut+eps]:
            ev=event_at(c,ema,v,stamp)
            values.append({'close':v,'structure':bool(ev),'route':ev['route'] if ev else None})
        boundaries.append({'boundary':cut,'tests':values})
    return intervals, {'successfulSamples':probes,'boundarySamples':boundaries}

def scenarios(c):
    if c.state=='STRUCTURE': return [],'ALREADY_CONFIRMED'
    if not c.wave or not c.wave.sign: return [],'ZERO_WAVE'
    if c.state=='DULL': return [{'c':clone(c),'price':c.previous.close,'entry':None,'path':[],'activation':c.previous.time}],'DULL'
    pool=list(reversed(c.history[c.wave.sign]))
    if not pool: return [],'NO_REFERENCE'
    sign=c.wave.sign;results=[]
    for ref in sorted(pool,key=lambda w:sign*w.dif,reverse=True):
        bound=max(pool[0].price,ref.price) if sign==1 else min(pool[0].price,ref.price)
        if sign*(c.wave.price-bound)>0:
            price=c.previous.close
        else:
            v=Decimal(str(bound));price=float(v.quantize(Q,rounding=ROUND_FLOOR if sign==1 else ROUND_CEILING)+ (Q if sign==1 else -Q))
        if not any(v['price']==price for v in results):results.append({'c':clone(c),'price':price,'entry':{'historicalPriceBoundary':bound,'referencePrice':price,'strictDirection':'above' if sign==1 else 'below'},'path':[],'activation':None})
    return results,'NONE'

def forecast(c,ema):
    before=encode(c.snapshot());slots=future(c.period,c.previous.time);scs,base=scenarios(c)
    if not scs:return {'status':base,'target':None,'asOf':c.previous.time,'state':c.state,'attempted':0}
    for sc in scs:sc['ema']=ema;sc['ended']=None
    tried=[]
    for j,stamp in enumerate(slots,1):
        hits=[]
        for sc in scs:
            if sc['ended']:continue
            child=sc['c'];ranges,samples=solve(child,sc['ema'],stamp)
            tried.append({'j':j,'stamp':stamp,'referencePrice':sc['price'],'stateBefore':child.state,'hasSolution':bool(ranges)})
            if ranges:hits.append({'referencePrice':sc['price'],'entry':sc['entry'],'activation':sc['activation'],'path':sc['path'].copy(),'intervals':ranges,'verification':samples})
        if hits:
            assert before==encode(c.snapshot())
            identity=hashlib.sha256(encode({'snapshot':c.snapshot(),'ema':ema,'target':stamp,'hits':hits}).encode()).hexdigest()
            return {'status':'READY' if base=='DULL' else 'CONDITIONAL_ENTRY','target':stamp,'barsAhead':j,'asOf':c.previous.time,'state':c.state,'cases':hits,'id':identity,'attempted':tried,'realSnapshotUnchanged':True}
        for sc in scs:
            if sc['ended']:continue
            child=sc['c'];old_sign=child.wave.sign;old_ref=child.reference.start if child.reference else None
            bar,sc['ema']=project(sc['ema'],sc['price'],stamp,c.period);step=child.step(bar)
            sc['path'].append({'time':stamp,'close':sc['price']})
            dull=next((e for e in step.events if e['type']=='DULL'),None)
            if not sc['activation'] and dull:sc['activation']=stamp
            if child.wave.sign!=old_sign:sc['ended']='COLOR_CHANGED'
            elif any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):sc['ended']='REFERENCE_TERMINATED'
            elif old_ref and (child.reference is None or child.reference.start!=old_ref):sc['ended']='REFERENCE_CHANGED'
        if all(sc['ended'] for sc in scs):break
    assert before==encode(c.snapshot())
    return {'status':'NO_FEASIBLE_TARGET','target':None,'asOf':c.previous.time,'state':c.state,'attempted':tried,'scenarios':[{'referencePrice':s['price'],'entry':s['entry'],'ended':s['ended'],'path':s['path']} for s in scs],'realSnapshotUnchanged':True}

def compact(res):
    v=json.loads(encode(res))
    for case in v.get('cases',[]):case.pop('verification',None)
    v.pop('attempted',None)
    return v

def p95(values):return sorted(values)[math.ceil(len(values)*.95)-1]

all_results={};timings={};sources={};examples=[]
for period in PERIODS:
    bars,source=load(period);sources[period]=source
    start=time.perf_counter();c,ema,errors=rebuild(bars,period);preparation=(time.perf_counter()-start)*1000
    result=forecast(c,ema)
    warm=[]
    for i in range(20):
        start=time.perf_counter();again=forecast(c,ema);warm.append((time.perf_counter()-start)*1000)
        assert compact(again)==compact(result)
    cold=[]
    for i in range(20):
        start=time.perf_counter();b,_=load(period);cc,ee,_=rebuild(b,period);forecast(cc,ee);cold.append((time.perf_counter()-start)*1000)
    previous,prior_ema,_=rebuild(bars[:-1],period);prior=forecast(previous,prior_ema)
    all_results[period]={'latest':result,'previousAsOf':compact(prior),'sourceCalibrationMaxAbsError':errors}
    timings[period]={'warmProjectionP95Ms':p95(warm),'warmProjection20Ms':warm,'offlineColdLoadReplayForecastP95Ms':p95(cold),'offlineCold20Ms':cold,'initialReplayMs':preparation,'compactResponseBytes':len(encode(compact(result)).encode()),'notHttpOrDbLakeLatency':True}
    print(period,result['status'],result['target'],'warmP95',round(p95(warm),3),flush=True)
    # Recent historical examples, independent prefix rebuilds only.
    replay=XxmCalculator(period=period,source_identity='M0-frozen-prefix');last_by_state={}
    x=y=bars[0].close;a=0.
    for idx,bar in enumerate(bars):
        x=x*11/13+bar.close*2/13;y=y*25/27+bar.close*2/27;a=.8*a+.2*(x-y);replay.step(bar)
        if idx>=250:last_by_state[replay.state]=(idx,replay.snapshot(),(x,y,a))
    for state,(idx,snapshot,e) in last_by_state.items():
        cc=XxmCalculator(period=period,source_identity='M0-frozen-prefix');cc.restore(snapshot)
        r=forecast(cc,e);same,_e,_err=rebuild(bars[:idx+1],period)
        assert compact(forecast(same,_e))==compact(r)
        examples.append({'period':period,'state':state,'prefixRows':idx+1,'result':r,'prefixOnlyReproducible':True})

# Actual calendar edge cases: weekend and the SSE National Day closure.
calendar_checks={p:{a:future(p,a,4) for a in ['2026-09-30' if p=='day' else '2026-09-30T15:00:00+08:00','2026-10-09' if p=='day' else '2026-10-09T15:00:00+08:00']} for p in PERIODS}
assert all(v[0].startswith('2026-10-08') for p,vv in calendar_checks.items() for k,v in vv.items() if k.startswith('2026-09-30'))
assert all(v[0].startswith('2026-10-12') for p,vv in calendar_checks.items() for k,v in vv.items() if k.startswith('2026-10-09'))
report={'createdAt':datetime.now(CN_ZONE).isoformat(),'scope':'M0 read-only frozen-prefix arithmetic and design preparation; no forecast API or feature implementation','specHash':MAIN_SPEC.spec_hash,'sources':sources,'sourceAsOf':'2026-10-13','calendar':{'path':'future_sse_calendar.json','sha256':digest(OUT/'future_sse_calendar.json'),'rows':len(calendar['rows']),'edgeChecks':calendar_checks},'results':all_results,'historicalExamples':examples,'timings':timings,'limits':['Daily source is independently rounded to 3 decimals; tie convention not proved from raw source. Displayed bounds move inside successful cells; exact unrounded tie ownership remains M1 gate.','Finite branch-cell probe with current detector is a precheck, not exhaustive formal interval proof.','20 offline cold repetitions are frozen CSV + full replay, not 20 real HTTP/DB/DuckDB requests. Total 4-second endpoint gate remains M1.','Current-market prices are not freshly fetched; results refer to frozen 2026-10-13 prefixes.','Future calendar read on 2026-10-14 may reflect revisions after historical asOf; archived past forecasts require as-of calendar evidence.'],'changedFormalData':False,'changedApplicationCode':False,'sourceHashesAfter':{p:digest(ROOT/v['path']) for p,v in sources.items()}}
additional=[]
for item in examples:
    if item['state']!='DULL': continue
    period=item['period'];bars,_=load(period);c,ema,_=rebuild(bars[:item['prefixRows']],period)
    stamp=future(period,c.previous.time,1)[0]
    sign=c.wave.sign
    # Explicit original-kernel negative cases; synthetic bars are not market facts.
    zero=XxmBar(stamp,c.previous.close,c.previous.dif,c.previous.dif,0.)
    z=clone(c).step(zero)
    assert not any(e['type']=='STRUCTURE' for e in z.events)
    breach=c.reference.dif+sign*max(1.,abs(c.reference.dif)*.02)
    canceled=clone(c).step(XxmBar(stamp,c.previous.close,breach,breach-sign,sign*2.))
    assert any(e['type']=='CANCEL' for e in canceled.events)
    assert not any(e['type']=='STRUCTURE' for e in canceled.events)
    additional.append({'period':period,'asOf':c.previous.time,'zeroHistogramDoesNotConfirm':True,'referenceBreakCancelsBeforeStructure':True,'syntheticKernelProbe':True})
day=all_results['day']['latest'];c,ema,_=rebuild(load('day')[0],'day')
for step in day['cases'][0]['path']:
    b,ema=project(ema,step['close'],step['time'],'day');c.step(b)
ranges=day['cases'][0]['intervals'];gap=(ranges[0]['rawUpper']+ranges[1]['rawLower'])/2
assert event_at(c,ema,gap,day['target']) is None
additional.append({'period':'day','target':day['target'],'gapProbeClose':gap,'gapDoesNotConfirm':True})
report['additionalChecks']=additional
report['originalKernelFiles']={str(p.relative_to(ROOT)):digest(p) for p in [ROOT/'src/biz/services/wealth/market/index_detail_xxm/calculator.py',ROOT/'src/biz/services/wealth/market/index_detail_xxm/spec.py',ROOT/'src/biz/services/wealth/market/index_detail_xxm/types.py']}

for p,v in sources.items():assert report['sourceHashesAfter'][p]==v['sha256']
OUT.mkdir(parents=True,exist_ok=True);(OUT/'precheck.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
(OUT/'precheck.py').write_text(Path(__file__).read_text())
print('DONE',OUT,flush=True)
