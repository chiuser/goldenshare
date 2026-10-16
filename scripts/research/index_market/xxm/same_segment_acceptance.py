"""A1 product acceptance against immutable A2 research; no alternate engine.

API and budget modes reuse the existing route/readonly-source acceptance chain.
All outputs require a new directory. Formal data is never written.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import time
from zipfile import ZipFile

from .acceptance import load_source, sha
from . import bottom_history_acceptance as b
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec, MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection, ProjectionPrecisionError

ROOT = b.ROOT
FROZEN = ROOT / 'reports/xxm_same_segment_precheck_20261016_04'
GATES = (.75, 1., 1.2)
MATH_KEYS = ('status', 'reasonCode', 'targetEndpoint', 'barsAhead', 'activation', 'assumption',
             'targetEntryRanges', 'targetEntryExclusions', 'relations', 'commonConditions', 'examples')


def event_key(event):
    return {k:event[k] for k in ('time','direction','type','route','fromState','eventReference')}


def record_key(record, bottom=False):
    ignored = {'id','structureEventId'} if bottom else {'id'}
    return {k:v for k,v in record.items() if k not in ignored}


def new(period, gate=1.):
    return XxmCalculator(period=period, source_identity='a1-acceptance:'+period, spec=XxmSpec(dif_turn_pct=gate))


def frozen_mode(source, out, sources):
    calendar = b.calendar_rows(source)
    summary = dict(periods={}, softwareFormulaProven=False, formalFourSecondBudgetTested=False)
    totals = Counter()
    for period, bars in sources.items():
        frozen_forecasts = json.loads((FROZEN / f'forecasts_{period}.json').read_text())['results']
        wanted = {item['rows'] for item in frozen_forecasts}
        sensitivity = {}
        for gate in GATES:
            calc = new(period, gate)
            steps, events, bottom, top, rearms, snapshots, confirmations = [], [], {}, {}, {}, {}, {}
            last_confirmation = None
            fixed = {1,25,1000,len(bars)//2,len(bars)-1,len(bars)}
            transitions = []
            for n, bar in enumerate(bars, 1):
                step = calc.step(bar); steps.append(step); events.extend(step.events)
                bottom.update({h['id']:h for h in step.bottom_histories})
                top.update({h['id']:h for h in step.histories})
                rearms.update({r['id']:r for r in step.rearm_records})
                last_confirmation = next((e for e in step.events if e['type']=='STRUCTURE'),last_confirmation)
                transition = any(r['disappearedAt']==bar.time or r['endedAt']==bar.time for r in step.rearm_records)
                if transition: transitions.append(n)
                if gate == 1. and (n in wanted | fixed or transition):
                    snapshots[n] = calc.snapshot(); confirmations[n] = last_confirmation
            frozen = json.loads((FROZEN / f'diff_{period}_{gate}.json').read_text())
            count = dict(rows=len(bars), events=len(events), disappeared=sum(e['type']=='STRUCTURE_DISAPPEARED' for e in events),
                         reactivated=sum(e['route']=='reactivation' for e in events), historicalBottom=sum(e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' for e in events))
            for field, key in [('events','candidateEvents'),('disappeared','disappeared'),('reactivated','reactivated'),('historicalBottom','historicalBottom')]:
                assert count[field] == frozen['summary'][key], (period,gate,field)
            assert Counter(r['endReason'] or 'still_waiting' for r in rearms.values()) == frozen['summary']['waitEndReasons']
            actual_waits = [{k:v for k,v in r.items() if k not in ('id','bottomHistoryId','structureEventId','structureConfirmedAt','structureRoute','direction','referenceWave')}
                            | {'reference':r['referenceWave']} for r in rearms.values()]
            assert actual_waits == [{k:v for k,v in r.items() if k not in ('id','structureEventId')} for r in frozen['waits']]
            gone = Counter(r['structureEventId'] for r in rearms.values())
            for e in events:
                if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL':
                    gone[bottom[e['relatedBottomHistoryId']]['structureEventId']] += 1
            assert not any(v>1 for v in gone.values()), 'Duplicate A/B green for one structure'
            # TOP-only synthetic/legacy oracle is retained in calculator tests.
            # At the default gate every signal and history is an exact semantic comparison.
            if gate == 1.:
                expected = json.loads((FROZEN / f'events_{period}.json').read_text())
                assert [event_key(e) for e in events] == [event_key(e) for e in expected['events']]
                assert [record_key(h,True) for h in bottom.values()] == [record_key(h,True) for h in expected['bottomHistories']]
                assert [record_key(h) for h in top.values()] == [record_key(h) for h in expected['topHistories']]
                sampled = transitions[:3]+transitions[len(transitions)//2:len(transitions)//2+2]+transitions[-3:]
                cuts = sorted(n for n in fixed | set(sampled) if n in snapshots)
                for n in cuts:
                    child=new(period)
                    assert [child.step(bar) for bar in bars[:n]] == steps[:n]
                    assert child.snapshot()==snapshots[n]
                    resumed=new(period); resumed.restore(snapshots[n])
                    assert [resumed.step(bar) for bar in bars[n:n+250]] == steps[n:n+250]
                model_rows=[]
                for old in frozen_forecasts:
                    n=old['rows']; child=new(period); child.restore(snapshots[n]); before=child.snapshot()
                    start=time.perf_counter()
                    def check():
                        if time.perf_counter()-start>.2: raise TimeoutError('200ms model budget')
                    if child.state=='STRUCTURE' or confirmations[n] and confirmations[n]['time']==bars[n-1].time:
                        result=inactive_result('CONFIRMED')
                    else:
                        try: result=forecast(child,recover_projection(tuple(bars[:n]),period,check),b.future_slots(calendar,period,bars[n-1].time),check)
                        except ProjectionPrecisionError as exc: result=inactive_result('PRECISION_PENDING',exc.reason)
                    check()
                    assert result==old['result'],(period,old['through'])
                    assert child.snapshot()==before
                    if child.pending_rearm: assert result['status'] not in ('READY','CONFIRMED')
                    model_rows.append(dict(rows=n,through=bars[n-1].time,milliseconds=(time.perf_counter()-start)*1000,result=result))
                stamps=['2024-07-23','2024-08-05','2024-08-22'] if period=='day' else ['2024-08-05T15:00:00+08:00','2024-08-14T15:00:00+08:00'] if period=='m120' else []
                for stamp in stamps:
                    assert sum(e['time']==stamp and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' and e['direction']=='BOTTOM' for e in events)==1
                totals.update(cuts=len(cuts),forecasts=len(model_rows),disappeared=count['disappeared'],reactivated=count['reactivated'],historicalBottom=count['historicalBottom'],softwarePositives=len(stamps))
                b.save(out,f'events_{period}.json',dict(events=events,bottomHistories=list(bottom.values()),topHistories=list(top.values()),rearmRecords=list(rearms.values())))
                b.save(out,f'forecasts_{period}.json',model_rows)
                count.update(prefixRestoreCuts=len(cuts),forecasts=len(model_rows),maxModelMs=max(r['milliseconds'] for r in model_rows),calibrationProtected=sum(r['result']['reasonCode']=='CALIBRATION_FAILED' for r in model_rows))
            sensitivity[str(gate)]=count
            print(period,gate,json.dumps(count),flush=True)
        summary['periods'][period]=sensitivity
        b.save(out,'frozen_summary.json',summary)
    assert totals==dict(cuts=45,forecasts=369,disappeared=14,reactivated=7,historicalBottom=93,softwarePositives=5),totals
    summary['totals']=dict(totals)
    summary['simulations']=simulations(sources,out)
    return summary


def simulations(sources,out):
    cases=[('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3959.16,'DULL','reactivation',True),
           ('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3960.,'NONE',None,False),
           ('m120','2026-07-13T15:00:00+08:00','2026-07-14T11:30:00+08:00',3892.79,'NONE','dif_break',True),
           ('m90','2026-07-13T15:00:00+08:00','2026-07-14T11:00:00+08:00',3944.79,'DULL',None,True)]
    results=[]
    for period,through,stamp,close,state,route,software in cases:
        bars=[v for v in sources[period] if v.time<=through];calc=new(period)
        for bar in bars:calc.step(bar)
        before=calc.snapshot();child=clone(calc)
        bar,_=recover_projection(tuple(bars),period,lambda:None).project(close,stamp,period)
        step=child.step(bar)
        assert child.state==state and (any(e['route']==route for e in step.events) if route else not step.events)
        assert calc.snapshot()==before
        results.append(dict(period=period,through=through,hypothetical=asdict(bar),state=state,events=list(step.events),softwareObservation=software))
    b.save(out,'simulations.json',results)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('frozen','api','budget'),required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--formal-source',action='store_true');args=p.parse_args()
    if args.formal_source != (args.mode=='budget'): p.error('--formal-source is required only for readonly budget mode')
    sources={period:load_source(args.source,period) for period in b.PERIODS}
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((ROOT/'reports/xxm_same_segment_a1_implementation_20261016/baseline.json').read_text())
    archive=ROOT/'reports/xxm_same_segment_a1_implementation_20261016/h1_research_source.zip'
    assert sha(archive)==manifest['archiveSha256']
    with ZipFile(archive) as saved:
        name='src/biz/services/wealth/market/index_detail_xxm/calculator.py'
        old=saved.read(name).decode();current=(ROOT/name).read_text()
    # The unconditional segment/pool/extreme prelude and first-selection body
    # are byte-identical to the sealed h1 source. No archived code is executed.
    assert old[old.index('    def step('):old.index('        if not event_type:')]==current[current.index('    def step('):current.index('        blocked, reactivated, rearm_records')]
    start='            elif sign and wave.count >= self.spec.min_bars and self.history[sign]:'
    end='        events: list[dict[str, Any]] = []'
    assert old[old.index(start):old.index(end)]==current[current.index(start):current.index(end)]
    protected=manifest['protectedEvidence']
    assert all(sha(ROOT/path)==digest for path,digest in protected.items())
    result=dict(mode=args.mode,algorithmVersion=MAIN_SPEC.algorithm_version,specHash=MAIN_SPEC.spec_hash)
    try:
        result['result']={'frozen':frozen_mode,'api':b.api_mode,'budget':b.budget_mode}[args.mode](args.source,args.output,sources)
        result['passed']=True
    except Exception as exc:
        result.update(passed=False,failure=dict(type=type(exc).__name__,code=getattr(exc,'code',None)))
        if args.mode=='budget':
            print(json.dumps(result['failure']),flush=True)
            raise SystemExit(1) from None
        raise
    finally:
        result['protectedUnchanged']=all(sha(ROOT/path)==digest for path,digest in protected.items())
        b.save(args.output,'summary.json',result)
        assert result['protectedUnchanged']


if __name__=='__main__':main()
