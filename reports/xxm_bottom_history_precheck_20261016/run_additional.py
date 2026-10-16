"""Independent B-only boundary, identity graph and past-window research checks."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timedelta,date
from dataclasses import replace
import json
from candidate import CandidateCalculator,OriginalCalculator
from scripts.research.index_market.xxm.acceptance import load_source
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
ROOT=Path('/Users/congming/github/goldenshare');OUT=ROOT/'reports/xxm_bottom_history_precheck_20261016';SOURCE=ROOT/'reports/xxm_source_audit_20261013_213852'
checks=[]
def ok(period,name):checks.append(dict(period=period,name=name,passed=True))
def instance(period):return CandidateCalculator(period=period,source_identity='additional:'+period)

def project(histories,bars,through):
    times=[b.time for b in bars];out={}
    for k,record in histories.items():
        if record['confirmedAt']>through:continue
        h=deepcopy(record)
        if h['leftOriginAt'] and h['leftOriginAt']>through:h['leftOriginAt']=None
        if h['endedAt'] and h['endedAt']>through:h.update(status='PENDING',endedAt=None,endReason=None)
        h['observedThrough']=h['endedAt'] or through
        h['ageBars']=times.index(h['observedThrough'])-times.index(h['confirmedAt']);out[k]=h
    return out

for period in ('day','m60','m90','m120'):
    bars=load_source(SOURCE,period);c=instance(period);base=OriginalCalculator(period=period,source_identity='additional:'+period)
    hmap={};baseline_top={};candidate_top={};ordinary_idmap={};pending=None;states={};ledger={};steps=[]
    for i,b in enumerate(bars):
        bs=base.step(b);cs=c.step(b);steps.append(cs)
        retained=[e for e in cs.events if not(e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' and e['direction']=='BOTTOM')]
        for be,ce in zip(bs.events,retained):
            ordinary_idmap[be['id']]=ce['id']
            if be['type']=='STRUCTURE' and be['direction']=='TOP':hmap[be['relatedTopHistoryId']]=ce['relatedTopHistoryId']
            if be['relatedTopHistoryId']:assert hmap[be['relatedTopHistoryId']]==ce['relatedTopHistoryId']
        if bs.point['pendingTopHistoryId']:assert hmap[bs.point['pendingTopHistoryId']]==cs.point['pendingTopHistoryId']
        for h in cs.bottomHistories:
            assert h['structureEventId'] in {e['id'] for s in steps for e in s.events if e['type']=='STRUCTURE' and e['direction']=='BOTTOM'}
            assert h['originSegmentStart']<=h['priceLowAt']<=h['confirmedAt']<=h['observedThrough']
            ledger[h['id']]=h
        if c.pendingBottomHistory and c.pendingBottomHistory['leftOriginAt'] and i+1<len(bars) and pending is None:
            pending=(c.snapshot(),bars[i+1].time)
        if i+1 in {len(bars)//2,len(bars)-5}:states[i+1]=deepcopy(steps)
    ok(period,'top_identity_graph_and_bottom_structure_associations')
    assert pending
    snap,stamp=pending;r=snap['pendingBottomHistory'];low=r['priceLow'];ref=r['originalReference']['dif']
    for name,close,dif,hist,reason in [('equal',low,ref+1,1.,None),('above',low+.01,ref+1,1.,None),('below',low-.01,ref+1,1.,'historical_price_break'),('reference_equal',low-.01,ref,1.,'historical_price_break'),('reference_break',low-.01,ref-.01,1.,'original_reference_break')]:
        child=instance(period);child.restore(snap);ev=[]
        change=child.advance_bottom(XxmBar(stamp,close,dif,dif-hist/2,hist),None,None,ev)
        assert change[0]['endReason']==reason and bool(ev)==(reason=='historical_price_break')
        ok(period,'controlled_'+name)
    # Explicitly mutate later prices; a requested earlier prefix and its history projection remain identical.
    for n,expected in states.items():
        altered=bars[:n]+[replace(b,close=b.close+100) for b in bars[n:]]
        pc=instance(period);ps=[pc.step(b) for b in altered if b.time<=bars[n-1].time]
        assert ps==expected
        actual={h['id']:h for s in ps for h in s.bottomHistories}
        assert actual==project(ledger,bars,bars[n-1].time)
    ok(period,'two_suffix_perturbation_prefixes_no_future_leak')
    # Event-only 1-bar window resolves to a record even when its structure lies outside it.
    addition=next(e for s in steps for e in s.events if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL')
    h=ledger[addition['relatedBottomHistoryId']];assert h['confirmedAt']<addition['time']
    lookup=project(ledger,bars,addition['time']);assert addition['relatedBottomHistoryId'] in lookup
    assert lookup[addition['relatedBottomHistoryId']]['endedAt']==addition['time']
    ok(period,'one_bar_window_keeps_outside_origin_record')

(OUT/'additional_checks.json').write_text(json.dumps(dict(scope='research invariants and controlled inputs; not implemented strict API DTO acceptance',checks=checks,total=len(checks)),ensure_ascii=False,indent=2)+'\n')
print('ADDITIONAL CHECKS PASSED',len(checks))
