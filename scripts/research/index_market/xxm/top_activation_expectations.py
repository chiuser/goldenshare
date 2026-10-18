"""Freeze pre-development ZC outputs; never imported by product or acceptance.

Uses the unchanged r1 parent. Expected rows must be consumed as files after
product migration, never regenerated through this subclass after that change.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

from .acceptance import load_source, sha
from .cross_index_daily import seal, read_unit
from .frozen_inputs import load_frozen_inputs
from .top_daily_ambiguity import ReferenceGateCalculator, ROOT, SOURCE, DAILY, LEGACY
from .top_activation_math import expectations
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec, MAIN_SPEC

OUT = ROOT/'reports/xxm_top_activation_expectations_20261018_01'
PRECHECK = ROOT/'reports/xxm_reference_rescue_forecast_precheck_20261017_01/run_02'
OLD_RECHECK = ROOT/'reports/xxm_top_current_dif_recheck_20261018_01'
R2_HASH = {0.75:'ddc241ad701a483a0e1659ed1a70ef46e695499199776c13694a29ddda3c1a04',
    1.0:'6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d',
    1.2:'81992335d6bd197e56cc2ff6d02b35fe46ddc61cfbeb282fb3e5e375bd3d2021'}


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class IdMap:
    """Literal public identity formula, independent of calculator._id."""
    def __init__(self, period, spec):
        self.period, self.old = period, spec
        proposed = asdict(spec);proposed['algorithm_version']='xxm-direction-v0.1-r2'
        self.new_hash = digest(proposed)
        assert self.new_hash == R2_HASH[spec.dif_turn_pct]
        self.records = {}

    def register(self, old_id, kind, parts, dependencies=()):
        def compute(version, spec_hash, values):
            text='|'.join(map(str,[version,spec_hash,'000001.SH',self.period,*values]))
            return hashlib.sha256(text.encode()).hexdigest()[:24]
        assert old_id == compute(self.old.algorithm_version,self.old.spec_hash,parts),(kind,parts)
        new_parts=[self.records[v]['new'] if i in dependencies else v for i,v in enumerate(parts)]
        record=dict(kind=kind,parts=list(parts),dependencies=list(dependencies),new=compute('xxm-direction-v0.1-r2',self.new_hash,new_parts))
        if old_id in self.records:assert self.records[old_id]==record
        else:self.records[old_id]=record

    def step(self, step):
        for e in step.events:
            if e['type']!='RESEARCH_HISTORICAL_WITHDRAWAL':
                self.register(e['id'],'event',[e['time'],e['type'],1 if e['direction']=='TOP' else -1,e['eventReference']['startTime']])
        for h in step.histories:
            self.register(h['id'],'top-history',['history',h['confirmedAt'],h['confirmationRoute'],h['originalReference']['startTime']])
        for h in step.bottom_histories:
            self.register(h['id'],'bottom-history',['bottom-history',h['structureEventId']],(1,))
        for r in step.rearm_records:
            self.register(r['id'],'rearm',['rearm',r['structureEventId'],r['disappearedAt']],(1,))
        for e in step.events:
            if e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL':
                linked=e['relatedTopHistoryId'] or e['relatedBottomHistoryId']
                self.register(e['id'],'withdrawal',[e['time'],e['type'],linked],(2,))
        return self.convert(asdict(step))

    def convert(self, value):
        if isinstance(value,dict):
            for key,item in value.items():
                if (key=='id' or key.endswith('Id')) and item is not None:
                    assert item in self.records,('Unknown identity link',key,item)
            return {k:self.convert(v) for k,v in value.items()}
        if isinstance(value,(tuple,list)):return [self.convert(v) for v in value]
        if isinstance(value,str) and value in self.records:return self.records[value]['new']
        return value


def inputs():
    old, manifest=load_frozen_inputs(LEGACY)
    source={p:tuple(load_source(SOURCE,p)) for p in ('day','m60','m90','m120')}
    daily=tuple(load_source(DAILY,'day'))
    assert {p:len(v) for p,v in old.items()}=={60:1316,90:1107,120:738}
    assert {p:len(v) for p,v in source.items()}=={'day':912,'m60':17260,'m90':12945,'m120':8630}
    assert len(daily)==1643 and all({b.time:b for b in daily}[b.time]==b for b in source['day'])
    data={'legacy':{'m'+str(p):tuple(v) for p,v in old.items()},'source':source,'daily2020':{'day':daily}}
    paths=[LEGACY/'historical_withdrawal_full_timeline_20261013.json',*[LEGACY/p for p in manifest['frozen_definitions']['inputs']],
        SOURCE/'manifest.json',DAILY/'manifest.json',DAILY/'daily_source.csv',
        *[SOURCE/('daily_source.csv' if p=='day' else f'minute_{p[1:]}_source.csv') for p in source],
        PRECHECK/'summary.json',*sorted(PRECHECK.glob('forecasts_*.json')),
        *[OLD_RECHECK/f'{p}_ZC.json' for p in source]]
    return data,{str(p.relative_to(ROOT)):sha(p) for p in paths}


def protected_files():
    paths=[]
    for directory in ('src/biz/services/wealth/market/index_detail_xxm','src/biz/queries/wealth/market/index_detail_xxm',
                      'wealth/src/features/index-detail/xxm','wealth/src/features/index-detail/xxm-forecast'):
        paths.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend((ROOT/'scripts/research/index_market/tests').glob('test_xxm*.py'))
    paths.extend((ROOT/'tests/web').glob('*xxm*.py'))
    paths.extend([ROOT/'scripts/research/index_market/xxm/top_daily_ambiguity.py',ROOT/'src/biz/schemas/wealth/market/index_detail_xxm_forecast.py'])
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}


def context(c, step):
    s=c.snapshot()
    return {**{k:s[k] for k in ('state','wave','history','reference','previous','pendingRearm')},
        'confirmedNow':next((e for e in step.events if e['type']=='STRUCTURE'),None)}


def verify_stream(out, name, info):
    path=out/info['file']
    assert path.stat().st_size<=20*1024**2 and sha(path)==info['sha256']
    count=raw=0;stream_hash=hashlib.sha256();last=None
    with gzip.open(path,'rb') as stream:
        for line in stream:
            raw+=len(line);assert raw<=128*1024**2
            row=json.loads(line);count+=1;stream_hash.update(line);last=row
            assert row['expected']['point']['time']==row['time']
    assert count==info['rows'] and raw==info['rawBytes'] and last['time']==info['through']
    assert stream_hash.hexdigest()==info['contentSha256']


def run_unit(out, group, period, bars, gate, deadline):
    name=f'{group}_{period}_{gate}'
    completed=read_unit(out,name)
    if completed is not None:
        verify_stream(out,name,completed);return completed,True
    path=out/(name+'.ndjson.gz');partial=out/(name+'.ndjson.gz.partial')
    if path.exists() or partial.exists():raise ValueError('Unsealed unit exists; preserve it and investigate: '+name)
    spec=XxmSpec(dif_turn_pct=gate);origin='top-activation-freeze:'+group+':'+period
    left=XxmCalculator(period=period,source_identity=origin,spec=spec)
    right=ReferenceGateCalculator(period=period,source_identity=origin,spec=spec,variant='ZC')
    ids=IdMap(period,spec);events=[];changes=[];forecasts=[];counts=Counter();bottom=Counter()
    old_forecasts=json.loads((PRECHECK/f'forecasts_{period}_{gate}.json').read_text()) if group=='source' else []
    by_n={v['rows']:v for v in old_forecasts};tail=deque(maxlen=100);cut_snapshot=None
    stream_hash=hashlib.sha256();raw=0
    with partial.open('xb') as binary, gzip.GzipFile(fileobj=binary,mode='wb',mtime=0) as stream:
        for n,bar in enumerate(bars,1):
            if n%100==0 and time.perf_counter()>deadline:raise TimeoutError('Unit exceeds budget')
            if n==len(bars)-99:cut_snapshot=right.snapshot()
            a,b=left.step(bar),right.step(bar)
            assert left.wave==right.wave and left.history==right.history
            assert [e for e in a.events if e['direction']=='BOTTOM']==[e for e in b.events if e['direction']=='BOTTOM']
            assert a.bottom_histories==b.bottom_histories and a.rearm_records==b.rearm_records
            bottom['events']+=sum(e['direction']=='BOTTOM' for e in b.events)
            bottom['historyUpdates']+=len(b.bottom_histories);bottom['rearmUpdates']+=len(b.rearm_records)
            expected=ids.step(b);events.extend(b.events);tail.append((bar,b))
            if a!=b:
                changes.append(dict(time=bar.time,oldState=a.point['ordinaryState'],newState=b.point['ordinaryState'],
                    oldEvents=list(a.events),newEvents=list(b.events),oldStepSha256=digest(asdict(a)),newStepSha256=digest(asdict(b))))
            for e in b.events:counts[e['direction']+':'+e['type']]+=1
            record=dict(time=bar.time,baseR1StepSha256=digest(asdict(a)),expected=expected)
            line=encoded(record)+b'\n';raw+=len(line);assert raw<=128*1024**2
            stream_hash.update(line);stream.write(line)
            if n in by_n:
                old=by_n[n];assert old['through']==bar.time
                equal=context(left,a)==context(right,b)
                first_top=(right.state=='NONE' and right.wave.sign==1 and bool(right.history[1]))
                category=('CONTEXT_CHANGED' if not equal else 'FIRST_TOP_DOMAIN' if first_top and old['result']['reasonCode']!='CALIBRATION_FAILED' else 'RETAIN_OLD_EXPECTATION')
                forecasts.append(dict(rows=n,through=bar.time,category=category,
                    oldStatus=old['result']['status'],oldReason=old['result']['reasonCode'],
                    oldContext=context(left,a),candidateContext=context(right,b),
                    oldResultSha256=digest(old['result']),originalFile=f'{PRECHECK.relative_to(ROOT)}/forecasts_{period}_{gate}.json'))
    if path.exists():raise ValueError('Refusing unit overwrite')
    os.replace(partial,path)
    assert path.stat().st_size<=20*1024**2
    resumed=ReferenceGateCalculator(period=period,source_identity=origin,spec=spec,variant='ZC')
    resumed.restore(cut_snapshot)
    for bar,wanted in tail:assert resumed.step(bar)==wanted
    assert resumed.snapshot()==right.snapshot()
    if group in ('source','daily2020') and gate==1.0:
        # Three minute files and daily2020 are the exact old main ZC sources.
        if period!='day' or group=='daily2020':
            assert events==json.loads((OLD_RECHECK/f'{period}_ZC.json').read_text())['events']
    final=ids.convert(right.snapshot());final['specHash']=ids.new_hash
    info=dict(file=path.name,sha256=sha(path),contentSha256=stream_hash.hexdigest(),rawBytes=raw,
        rows=len(bars),through=bars[-1].time,start=bars[0].time,inputSha256=digest([asdict(v) for v in bars]),
        group=group,period=period,gate=gate,oldSpecHash=spec.spec_hash,expectedSpecHash=ids.new_hash,
        sourceIdentity=origin,eventCounts=dict(counts),bottomProtected=dict(bottom),changedEndpoints=len(changes),
        changes=changes,identityMap=ids.records,finalSnapshot=final,forecasts=forecasts,restoreRows=100,
        finalR1SnapshotSha256=digest(right.snapshot()))
    verify_stream(out,name,info);seal(out,name,info)
    return info,False


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();out=args.output.resolve()
    if out!=OUT:raise ValueError('Only the planned new report directory is allowed')
    out.mkdir(exist_ok=True);start=time.perf_counter()
    assert MAIN_SPEC.algorithm_version=='xxm-direction-v0.1-r1' and MAIN_SPEC.spec_hash=='533a9b441e49c1b2c076482ad6815f61e49494f63ec2c8c922a03d868e4ce730'
    data,sources=inputs();protected=protected_files()
    code={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__)),
          'scripts/research/index_market/xxm/top_activation_math.py':sha(Path(__file__).with_name('top_activation_math.py'))}
    manifest=dict(purpose='PRE_PRODUCT_CHANGE_EXPECTATIONS',productVersion=MAIN_SPEC.algorithm_version,
        sources=sources,protected=protected,preparationCode=code,units=24,rowsPerGate=44551,
        gates=[.75,1.,1.2],productChanged=False,softwareUniqueFormulaProven=False)
    previous=read_unit(out,'manifest')
    if previous is None:seal(out,'manifest',manifest)
    else:assert previous==manifest,'Source/code identity changed on resume'
    math_expected=expectations();previous=read_unit(out,'independent_math')
    if previous is None:seal(out,'independent_math',math_expected)
    else:assert previous==math_expected
    results=[];reused=0
    try:
        for group,periods in data.items():
            for period,bars in periods.items():
                for gate in (.75,1.,1.2):
                    assert time.perf_counter()-start<240,'Compute phase budget'
                    result,old=run_unit(out,group,period,bars,gate,min(start+240,time.perf_counter()+60))
                    results.append(result);reused+=old
                    print(json.dumps(dict(completed=len(results),total=24,group=group,period=period,gate=gate,
                        changed=result['changedEndpoints'],reused=old)),flush=True)
        assert len(results)==24 and sum(r['rows'] for r in results)==133653
        forecasts=[dict(group=r['group'],period=r['period'],gate=r['gate'],**f) for r in results for f in r['forecasts']]
        assert len(forecasts)==1215
        summary=dict(status='PREPARED_WITH_EXPLICIT_PENDING_FORECASTS',units=24,rows=133653,uniqueInputRows=44551,
            resumedUnits=reused,recognitionExpectationsComplete=True,forecastCategories=dict(Counter(f['category'] for f in forecasts)),
            independentMathComplete=True,allRealForecastExpectationsComplete=False,
            oldFilesAndProductUnchanged=all(sha(ROOT/p)==value for p,value in {**sources,**protected}.items()),
            unitSummaries=[{k:r[k] for k in ('group','period','gate','rows','changedEndpoints','eventCounts','bottomProtected','sha256','rawBytes')} for r in results],
            compressedBytes=sum((out/r['file']).stat().st_size for r in results),seconds=time.perf_counter()-start)
        assert summary['oldFilesAndProductUnchanged'] and summary['compressedBytes']<=512*1024**2
        for name,value in [('forecast_inventory',forecasts),('summary',summary)]:
            old=read_unit(out,name)
            if old is None:seal(out,name,value)
            elif name=='forecast_inventory':assert old==value
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    except BaseException as exc:
        name='failure_'+str(time.time_ns())
        seal(out,name,dict(type=type(exc).__name__,error=str(exc),seconds=time.perf_counter()-start,completed=len(results)))
        raise


if __name__=='__main__':main()
