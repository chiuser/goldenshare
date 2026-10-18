"""Offline falsification of the 2024-09-24/25 daily TOP ambiguity.

No software NONE label is invented for the two disputed dates. The variants
only test consequences of four explicit reference-eligibility hypotheses.
Never imported by product code; no database, Lake or network access.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from .acceptance import load_source, sha
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'reports/xxm_source_audit_20261013_213852'
DAILY = ROOT/'reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01'
LEGACY = ROOT/'reports/xxm_macd_structure_20261011'
VARIANTS = ('BASE','T2','S2','ZC','ZR')
PERIODS = ('day','m60','m90','m120')
CASES = {'jul_120':'m120','aug_120':'m120','may_120':'m120',
         'daily_2025':'day','bottom_daily':'day','mins60':'m60','mins90':'m90'}


class ReferenceGateCalculator(XxmCalculator):
    """One research-only selector change; original segments/pool stay intact."""

    def __init__(self, *, variant='BASE', **kwargs):
        if variant not in VARIANTS:
            raise ValueError('Unknown isolated hypothesis')
        super().__init__(**kwargs)
        self.variant = variant
        self.incoming = None

    def step(self, bar):
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError('Duplicate or unordered XXM input')
        self.incoming = bar
        return super().step(bar)

    def _select_eligible_reference(self, wave, history):
        original = super()._select_eligible_reference(wave, history)
        if original is None or self.variant == 'BASE':
            return original
        if self.variant == 'T2' and wave.sign != 1:
            return original
        if self.variant in ('ZC','ZR') and wave.sign != 1:
            return original
        if self.variant == 'ZC':
            assert self.incoming is not None
            return original if self.incoming.dif > 0 else None
        # The original nearest-price gate already passed. Do NOT filter the
        # history itself: singleton segments still occupy the two-slot pool.
        pool = sorted(reversed(history),key=lambda item:wave.sign*item.dif,reverse=True)
        return next((item for item in pool
            if wave.sign*(wave.price-item.price)>0 and wave.sign*(wave.dif-item.dif)<0
            and (item.count>=2 if self.variant in ('T2','S2') else item.dif>0)),None)


def new(period,variant):
    return ReferenceGateCalculator(period=period,source_identity='top-daily-ambiguity:'+period,variant=variant)


def labels():
    """Reuse the independently recorded literals, without retiming labels."""
    previous = list(sys.path)
    try:
        sys.path.insert(0,str(LEGACY))
        from audit_turn_filters import labels50
        values = labels50()+[dict(case='mins90',source='holdout_20260105_pair.json',**v)
            for v in json.loads((LEGACY/'holdout_20260105_pair.json').read_text())['labels']]
    finally:
        sys.path[:] = previous
    assert len(values)==52 and Counter(v['confidence'] for v in values)=={'direct':20,'mapped':32}
    for value in values:
        value['period'] = CASES[value['case']]
        value['endpoint'] = (value['time'] if value['period']=='day' else
            datetime.fromisoformat(value['time']).isoformat()+'+08:00')
    return values


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def ordinary(step):
    events = [e for e in step.events if e['type']!='RESEARCH_HISTORICAL_WITHDRAWAL']
    assert len(events)<=1
    return events[0]['type'] if events else 'NONE'


def protected():
    prior=json.loads((ROOT/'reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_code_manifest.json').read_text())
    paths=[ROOT/value['path'] for value in prior['files']]
    paths += list(LEGACY.glob('*.json'))+list(LEGACY.glob('*.py'))+list(LEGACY.glob('*.csv'))
    paths += [SOURCE/'manifest.json',DAILY/'manifest.json',DAILY/'daily_source.csv',
        *[SOURCE/f'minute_{p}_source.csv' for p in (60,90,120)]]
    evidence=ROOT/'reports/xxm_software_indicator_crosscheck_20261015'
    paths += [evidence/'sources'/f'{name}.png' for name in ('20240930_day','20250407_day')]
    paths += [evidence/'event_recognition_review_20261015.json',evidence/'event_recognition_review_20261015.md']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}


def read_inputs():
    for directory in (SOURCE,DAILY):
        manifest=json.loads((directory/'manifest.json').read_text())
        for value in manifest['files']:
            if value['name'].endswith('_source.csv'):
                assert sha(directory/value['name'])==value['sha256']
    data={p:tuple(load_source(DAILY if p=='day' else SOURCE,p)) for p in PERIODS}
    assert len(data['day'])<=2000 and all(len(data[p])<=20000 for p in PERIODS[1:])
    assert sum(map(len,data.values()))<=40500
    for period,bars in data.items():
        assert bars and all(a.time<b.time for a,b in zip(bars,bars[1:]))
        for bar in bars:bar.validate(period)
    actual={v.time:v for v in data['day']}
    overlap=tuple(load_source(SOURCE,'day'))
    assert all(actual.get(value.time)==value for value in overlap)
    return data,len(overlap)


def audit(period,bars,variant,observations,deadline):
    base,candidate=new(period,'BASE'),new(period,variant)
    events=[];differences=[];matches=[];landmarks={};cuts={max(1,len(bars)-3)}
    if period=='day':cuts.update(i for i,v in enumerate(bars,1) if v.time in ('2024-09-24','2024-09-25'))
    needed={v['endpoint'] for v in observations}
    if period=='day':needed.update(('2024-08-30','2024-09-23','2024-09-24','2024-09-25','2024-09-26',
        '2024-07-23','2024-08-05','2024-08-15','2024-08-22','2025-03-17','2025-03-19','2026-05-11','2026-05-14'))
    snapshots={};steps_at_cut={};catalog={}
    for index,bar in enumerate(bars,1):
        if index%100==0 and time.perf_counter()>deadline:raise TimeoutError('Research 60-second limit')
        left,right=base.step(bar),candidate.step(bar)
        assert base.wave==candidate.wave and base.history==candidate.history,'Hypothesis changed segmentation/pool'
        events.extend(right.events)
        if candidate.wave is not None:catalog[candidate.wave.start]=asdict(candidate.wave)
        if left!=right:
            differences.append(dict(time=bar.time,baseEvents=list(left.events),events=list(right.events),
                basePoint=left.point,point=right.point))
        if bar.time in needed:
            selected=right.events[0].get('eventReference') if right.events else right.point['activeReference']
            landmarks[bar.time]=dict(bar=asdict(bar),events=list(right.events),ordinary=ordinary(right),
                point=right.point,wave=asdict(candidate.wave),history={str(k):[asdict(v) for v in pool] for k,pool in candidate.history.items()},
                selectedReferenceBars=catalog.get(selected['startTime'],{}).get('count') if selected else None)
        if index in cuts:snapshots[index]=candidate.snapshot();steps_at_cut[index]=right
        for label in observations:
            if label['endpoint']==bar.time:
                matches.append(dict(**label,baseActual=ordinary(left),actual=ordinary(right),
                    baseMatches=ordinary(left)==label['expected'],matches=ordinary(right)==label['expected']))
    for cut,snapshot in snapshots.items():
        child=new(period,variant)
        for index,bar in enumerate(bars[:cut],1):
            if index%100==0 and time.perf_counter()>deadline:raise TimeoutError('Research 60-second limit')
            last=child.step(bar)
        assert last==steps_at_cut[cut] and child.snapshot()==snapshot
        resumed=new(period,variant);resumed.restore(snapshot)
        for bar in bars[cut:cut+3]:assert child.step(bar)==resumed.step(bar)
    assert len(matches)==len(observations)
    return dict(period=period,variant=variant,rows=len(bars),events=events,differences=differences,
        landmarks=landmarks,labels=matches,restores=len(snapshots),segmentationAndPoolUnchanged=True,
        eventsCount=len(events),changedEndpoints=len(differences),
        newlyLostLabels=[v for v in matches if v['baseMatches'] and not v['matches']],
        newlyMatchedLabels=[v for v in matches if not v['baseMatches'] and v['matches']],
        baselineUnmatchedLabels=[v for v in matches if not v['baseMatches']])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();before=protected();save(args.output/'protected_before.json',before)
    run=dict(status='RUNNING',scope='OFFLINE_TOP_DAILY_20240924_25',productCodeChanged=False,
        formalWrites=False,specHash=MAIN_SPEC.spec_hash,variants=VARIANTS)
    save(args.output/'run.json',run)
    try:
        data,overlap=read_inputs();observations=labels();save(args.output/'observations.json',observations)
        rows=[]
        for period in PERIODS:
            for variant in VARIANTS:
                result=audit(period,data[period],variant,[v for v in observations if v['period']==period],start+60)
                if time.perf_counter()>start+60:raise TimeoutError('Research 60-second limit')
                save(args.output/f'{period}_{variant}.json',result)
                rows.append({k:result[k] for k in ('period','variant','rows','eventsCount','changedEndpoints','restores',
                    'newlyLostLabels','newlyMatchedLabels','baselineUnmatchedLabels')})
                save(args.output/'progress.json',dict(completed=len(rows),total=20,rows=rows))
                print(json.dumps(dict(period=period,variant=variant,completed=len(rows),total=20,
                    changedEndpoints=result['changedEndpoints'],newlyLostLabels=len(result['newlyLostLabels']))),flush=True)
        run.update(status='COMPLETE',passed=True,sourceRows={p:len(v) for p,v in data.items()},
            frozenDailyOverlap=overlap,labels=52,direct=20,mapped=32,units=rows)
    except Exception as exc:
        run.update(status='FAILED',passed=False,failure=dict(type=type(exc).__name__,message=str(exc)))
        raise
    finally:
        after={p:sha(ROOT/p) for p in before}
        run.update(protectedFiles=len(before),protectedUnchanged=before==after,seconds=time.perf_counter()-start)
        save(args.output/'run.json',run)
        if before!=after:raise AssertionError('Protected input/product/old evidence changed')


if __name__=='__main__':main()
