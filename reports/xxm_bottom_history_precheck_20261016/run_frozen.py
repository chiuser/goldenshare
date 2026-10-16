from pathlib import Path
import csv, hashlib, json, sys, time
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from candidate import CandidateCalculator, OriginalCalculator, SPEC
from scripts.research.index_market.xxm.acceptance import load_source
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

ROOT=Path('/Users/congming/github/goldenshare')
OUT=ROOT/'reports/xxm_bottom_history_precheck_20261016'
SOURCE=ROOT/'reports/xxm_source_audit_20261013_213852'
OLD=ROOT/'reports/xxm_software_indicator_crosscheck_20261015'
IDENTITY_KEYS={'id','relatedTopHistoryId','pendingTopHistoryId','structureEventId','relatedBottomHistoryId','pendingBottomHistoryId','specHash'}
def clean(x):
    if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k not in IDENTITY_KEYS}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    return x

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def new(period,cls=CandidateCalculator):return cls(period=period,source_identity=f'frozen:{period}:{SOURCE.name}')
def run(period,bars,cls=CandidateCalculator):
    c=new(period,cls);steps=[c.step(b) for b in bars];return c,steps

def ledger(steps):return {h['id']:h for s in steps for h in s.bottomHistories}

def asof(records,bars,through):
    times=[b.time for b in bars if b.time<=through]
    out={}
    for key,h in records.items():
        if h['confirmedAt']>through:continue
        h=deepcopy(h)
        if h['leftOriginAt'] and h['leftOriginAt']>through:h['leftOriginAt']=None
        if h['endedAt'] and h['endedAt']>through:h.update(status='PENDING',endedAt=None,endReason=None)
        h['observedThrough']=min(through,h['endedAt']) if h['endedAt'] else through
        h['ageBars']=times.index(h['observedThrough'])-times.index(h['confirmedAt'])
        out[key]=h
    return out

all_data={};summary={'scope':'B1 scratch precheck; unchanged product calculator; source snapshot through 2026-10-13','candidateSpec':asdict(SPEC),'candidateSpecHash':SPEC.spec_hash,'periods':{},'checks':[]}
oldmatrix=next(x for x in json.loads((OLD/'case_20240723_candidate_matrix_results_20261016.json').read_text())['candidates'] if x['id']=='H1-S2-E1')
for period in ('day','m60','m90','m120'):
    bars=load_source(SOURCE,period)
    t=time.perf_counter();base,bs=run(period,bars,OriginalCalculator);base_ms=(time.perf_counter()-t)*1000
    t=time.perf_counter();c,ss=run(period,bars);candidate_ms=(time.perf_counter()-t)*1000
    recs=ledger(ss);events=[e for s in ss for e in s.events]
    additions=[e for e in events if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL']
    for i,(b,s) in enumerate(zip(bs,ss)):
        assert clean(b.point)==clean(s.point),(period,i,'point')
        retained=[e for e in s.events if not(e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL')]
        assert clean(b.events)==clean(retained),(period,i,'event')
        assert clean(b.histories)==clean(s.histories),(period,i,'top_history')
        # Check the identity graph, not only payload after stripping identity.
        for be,ce in zip(b.events,retained):
            assert bool(be['relatedTopHistoryId'])==bool(ce['relatedTopHistoryId'])
        assert bool(b.point['pendingTopHistoryId'])==bool(s.point['pendingTopHistoryId'])
    bstate=clean(base.snapshot());cstate=clean(c.snapshot());cstate.pop('pendingBottomHistory',None)
    assert bstate==cstate
    for e in additions:
        h=recs[e['relatedBottomHistoryId']]
        assert h['status']=='ENDED' and h['endReason']=='historical_price_break' and h['endedAt']==e['time']
        assert e['relatedTopHistoryId'] is None and h['leftOriginAt'] and e['time']>h['confirmedAt']
        assert e['eventReference']==h['originalReference']
    assert len({e['relatedBottomHistoryId'] for e in additions})==len(additions)
    # Compare independently implemented prior hypothesis only within its registered research window.
    old_window=oldmatrix['periods'][period]['researchWindowTriggers']
    current_window=[dict(anchor=recs[e['relatedBottomHistoryId']]['confirmedAt'],time=e['time']) for e in additions if '2024-07-01'<=e['time'][:10]<='2024-09-04']
    expected_window=[{k:x[k] for k in ('anchor','time')} for x in old_window]
    assert current_window==expected_window,(period,current_window,expected_window)
    # Prefix/as-of/restore checks cover starts, exits, endings and evenly spaced source history.
    cuts={1,25,1000,len(bars)//2,len(bars)-1,len(bars)}
    for h in recs.values():
        if '2024-07-01'<=h['confirmedAt'][:10]<='2024-09-04':
            for stamp in (h['confirmedAt'],h['leftOriginAt'],h['endedAt']):
                if stamp:cuts.add(next(i+1 for i,b in enumerate(bars) if b.time==stamp))
    cuts=sorted(n for n in cuts if 0<n<=len(bars))
    for n in cuts:
        pc,ps=run(period,bars[:n]);assert ps==ss[:n]
        assert ledger(ps)==asof(recs,bars,bars[n-1].time),(period,'asof',bars[n-1].time)
        restored=new(period);restored.restore(pc.snapshot())
        stop=min(len(bars),n+250)
        assert [restored.step(b) for b in bars[n:stop]]==ss[n:stop]
        assert pc.snapshot()==(run(period,bars[:n])[0].snapshot())
    invalid=new(period);snap=c.snapshot();snap['sourceIdentity']='other'
    try:invalid.restore(snap)
    except ValueError:pass
    else:raise AssertionError('source identity was accepted')
    snap=c.snapshot();snap['specHash']='old'
    try:invalid.restore(snap)
    except ValueError:pass
    else:raise AssertionError('old spec was accepted')
    new_rows=[]
    for e in additions:
        h=recs[e['relatedBottomHistoryId']];idx=next(i for i,b in enumerate(bars) if b.time==e['time'])
        new_rows.append(dict(period=period,time=e['time'],confirmedAt=h['confirmedAt'],priceLow=h['priceLow'],priceLowAt=h['priceLowAt'],leftOriginAt=h['leftOriginAt'],close=bars[idx].close,dif=bars[idx].dif,previousDif=bars[idx-1].dif,hist=bars[idx].hist,ageBars=h['ageBars'],softwareOracle='known_five' if (period,e['time']) in {('day','2024-07-23'),('day','2024-08-05'),('day','2024-08-22'),('m120','2024-08-05T15:00:00+08:00'),('m120','2024-08-14T15:00:00+08:00')} else 'not_established'))
    with (OUT/f'new_bottom_events_{period}.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(new_rows[0]) if new_rows else ['period','time']);w.writeheader();w.writerows(new_rows)
    save(f'replay_{period}.json',dict(events=additions,bottomHistories=list(recs.values()),newEventInventory=new_rows))
    summary['periods'][period]=dict(rows=len(bars),start=bars[0].time,end=bars[-1].time,ordinaryAndTopIdentical=True,newBottomEvents=len(additions),historyRecords=len(recs),endReasons=dict(Counter(h['endReason'] for h in recs.values())),independentPrefixAndAsOfCuts=len(cuts),restoreCuts=len(cuts),maxPendingAge=max((h['ageBars'] for h in recs.values()),default=0),snapshotBytes=len(json.dumps(c.snapshot()).encode()),baseReplayMs=base_ms,candidateReplayMs=candidate_ms,priorHypothesisWindowIdentical=True)
    all_data[period]=(bars,ss,recs)
    save('frozen_summary.json',summary)
    print(period,json.dumps(summary['periods'][period]),flush=True)

# Literal known label mappings are not a software formula oracle.
for period,stamp,anchor in [('day','2024-07-23','2024-07-09'),('day','2024-08-05','2024-07-31'),('day','2024-08-22','2024-08-15'),('m120','2024-08-05T15:00:00+08:00','2024-07-31T11:30:00+08:00'),('m120','2024-08-14T15:00:00+08:00','2024-08-13T15:00:00+08:00')]:
    bars,ss,recs=all_data[period];s=next(s for s in ss if s.point['time']==stamp)
    e=next(e for e in s.events if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL')
    h=recs[e['relatedBottomHistoryId']];assert h['confirmedAt']==anchor
    summary['checks'].append(dict(name='known_label',period=period,time=stamp,anchor=anchor,passed=True))

bars,ss,recs=all_data['m120']
h=next(h for h in recs.values() if h['confirmedAt']=='2024-08-30T11:30:00+08:00')
assert h['endedAt']=='2024-09-02T15:00:00+08:00' and h['endReason']=='new_bottom_DULL'
for stamp in ('2024-09-02T11:30:00+08:00','2024-09-02T15:00:00+08:00'):
    s=next(s for s in ss if s.point['time']==stamp);assert not any(e['relatedBottomHistoryId']==h['id'] and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' for e in s.events)
summary['checks'].append(dict(name='Sep02_new_DULL_precedes_history',passed=True))
s=next(s for s in ss if s.point['time']=='2024-09-04T11:30:00+08:00');assert any(e['type']=='CANCEL' and e['route']=='dif_break' for e in s.events)
summary['checks'].append(dict(name='Sep04_real_CANCEL_retained',passed=True))
s=next(s for s in ss if s.point['time']=='2026-07-10T15:00:00+08:00');assert any(e['type']=='DULL' and e['route']=='dif_return' for e in s.events)
summary['checks'].append(dict(name='known_A_issue_explicitly_unchanged',passed=True))

# Controlled boundary probes isolate B; these are hypothetical detector inputs, not MACD projections/software observations.
bars,ss,recs=all_data['day'];n=next(i+1 for i,b in enumerate(bars) if b.time=='2024-07-22');parent,_=run('day',bars[:n]);saved=parent.snapshot();r=parent.pendingBottomHistory
assert r and r['leftOriginAt'];low=r['priceLow'];ref=r['originalReference']['dif']
for name,close,dif,expected in [('equal_price',low,-17.,None),('above_price',low+.01,-17.,None),('below_price_improving_DIF',low-.01,-14.,'historical_price_break'),('reference_equal',low-.01,ref,'historical_price_break'),('reference_breached',low-.01,ref-.001,'original_reference_break')]:
    child=new('day');child.restore(saved);events=[];changes=child.advance_bottom(XxmBar('2024-07-23',close,dif,-20.,4.),None,None,events)
    assert changes[-1]['endReason']==expected,(name,changes)
    assert bool(events)==(expected=='historical_price_break')
    summary['checks'].append(dict(name=name,passed=True))
for kind in ('DULL','STRUCTURE'):
    child=new('day');child.restore(saved);events=[]
    ordinary={'direction':'BOTTOM','type':kind,'route':'probe','id':'probe','eventReference':r['originalReference']}
    # Isolate close/priority; STRUCTURE creates the next record from an actual negative segment.
    child.wave.sign=-1
    changes=child.advance_bottom(XxmBar('2024-07-23',low-.01,-17.,-20.,4.),ordinary,child.wave,events)
    assert changes[0]['endReason']=='new_bottom_'+kind and not events
    summary['checks'].append(dict(name='priority_new_BOTTOM_'+kind,passed=True))
child=new('day');child.restore(saved);events=[]
child.advance_bottom(XxmBar('2024-07-23',low-.01,-17.,-20.,4.),{'direction':'TOP','type':'DULL'},None,events)
assert len(events)==1
summary['checks'].append(dict(name='TOP_not_bottom_successor',passed=True))
# Before origin exit, no historical price break; zero itself does not end the record.
n=next(i+1 for i,b in enumerate(bars) if b.time=='2024-07-09');pc,_=run('day',bars[:n]);ps=pc.snapshot();r=pc.pendingBottomHistory;assert not r['leftOriginAt']
child=new('day');child.restore(ps);events=[]
child.advance_bottom(XxmBar('2024-07-10',r['priceLow']-.01,-20.,-15.,-10.),None,None,events)
assert not events and child.pendingBottomHistory['priceLow']==r['priceLow'] and child.pendingBottomHistory['leftOriginAt'] is None
child=new('day');child.restore(ps);events=[]
child.advance_bottom(XxmBar('2024-07-10',r['priceLow']+.01,-20.,-20.,0.),None,None,events)
assert not events and child.pendingBottomHistory['leftOriginAt']=='2024-07-10'
child.advance_bottom(XxmBar('2024-07-11',r['priceLow']-.01,-20.,-19.,-2.),None,None,events)
assert len(events)==1
summary['checks'].append(dict(name='origin_exit_zero_and_later_negative',passed=True))
# More than 24 completed bars without an ending condition does not expire.
child=new('day');child.restore(saved)
from datetime import date,timedelta
for j in range(40):
    stamp=(date(2024,7,23)+timedelta(days=j)).isoformat();events=[]
    child.advance_bottom(XxmBar(stamp,low+.01,-17.,-20.,4.),None,None,events)
    assert child.pendingBottomHistory and not events
summary['checks'].append(dict(name='no_fixed_10_or_24_bar_TTL',passed=True,controlledBars=40))
summary['productImplemented']=False;summary['softwareUniqueFormulaProven']=False
save('frozen_summary.json',summary)
print('ALL FROZEN CHECKS PASSED',len(summary['checks']),flush=True)
