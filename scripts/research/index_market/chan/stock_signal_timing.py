"""Frozen signal type/confirmation-delay contrasts; no signal regeneration."""
import argparse
from collections import Counter
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from statistics import mean, median
import time

from scripts.research.index_market.chan import stock_parameter_study as study
from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class TimingSpec:
    variants: tuple = ('all','B1','B2','B3','lag4','lag8')
    thresholds: tuple = (4,8)
    seconds: int = 180
    input_bytes: int = 16*1024**2
    output_bytes: int = 64*1024**2
    previous: str = 'parameters'


SPEC=TimingSpec()


def feature(rows,days,event):
    i,a=event['signal_index'],event['anchor_index']
    if not 0<=a<=i<len(rows) or event['lag_bars']!=i-a:
        raise ValueError('future/invalid anchor or lag')
    if rows[i]['time']!=event['signal_time'] or rows[a]['time']!=event['anchor_time']:
        raise ValueError('timestamp mismatch')
    if not event['buy'] or not event['sure'] or event['group'] not in ('B1','B2','B3'):
        raise ValueError('not a confirmed buy')
    return dict(event_id=event['event_id'],group=event['group'],time=event['signal_time'],
        lag=i-a,market_day_lag=days.index(rows[i]['date'])-days.index(rows[a]['date']),
        already_risen=rows[i]['close']/rows[a]['low']-1)


def keep(f,variant):
    if variant=='all':return True
    if variant in ('B1','B2','B3'):return f['group']==variant
    if variant=='lag4':return f['lag']<=SPEC.thresholds[0]
    if variant=='lag8':return f['lag']<=SPEC.thresholds[1]
    raise ValueError('unapproved variant')


def aggregate(cells):
    out=[]
    for variant in SPEC.variants:
        for period in study.PERIODS:
            xs=[s for c in cells if c['variant']==variant for s in c['summary'] if s['period']==period and s['group']=='ALL' and s['horizon']==10]
            valid=[s for s in xs if s['n']]
            robust=[s['without_best'] for s in valid if s['without_best'] is not None]
            out.append(dict(variant=variant,period=period,stocks=len(valid),n=sum(s['n'] for s in valid),
                mean=mean(s['mean'] for s in valid) if valid else None,
                excess=mean(s['excess'] for s in valid) if valid else None,
                nonoverlap_excess=mean(s['nonoverlap']['excess'] for s in valid) if valid else None,
                positive=sum(s['excess']>0 for s in valid),robust_stocks=len(robust),
                without_best=mean(robust) if robust else None))
    for s in out:
        control=next(x for x in out if x['variant']=='all' and x['period']==s['period'])
        s['gate']=s['stocks']>=8 and s['n']>=50 and s['positive']>=7 and s['robust_stocks']>=8 and s['without_best']>0 and s['excess']>0 and s['nonoverlap_excess']>0 and s['excess']>control['excess']
    return out


def execute(output):
    output=base.safe_output(output)
    store=StockResearchStore()
    previous=store.root_key(SPEC.previous)
    setup=store.read(previous/'setup.json')
    manifest=store.read(previous/'manifest.json')
    if manifest['status']!='complete' or store.sha(previous/'setup.json')!=manifest['setup_sha256']:
        raise ValueError('previous not complete/authenticated')
    for p,h in setup['code_sha256'].items():
        store.verify_code(p,h)
    origin=store.root_key(study.SOURCE)
    origin_setup=store.read(origin/'source.json')
    if store.sha(origin/'source.json')!=setup['source_sha256']:raise ValueError('origin provenance')
    dates_path=store.root_key('initial')/'source.json'
    if store.sha(dates_path)!=origin_setup['previous_source_sha256']:raise ValueError('date provenance')
    days=store.read(dates_path)['days']
    stocks=store.read(origin/'status_10.json')
    output.mkdir();start=time.monotonic();cells=[];diagnostics=[]
    save(output/'setup.json',dict(spec=asdict(SPEC),periods=study.PERIODS,previous_manifest_sha256=store.sha(previous/'manifest.json'),input_store=store.receipt,
        plan_sha256=base.sha(base.REPO/'docs/product/stock-chan-share-position-backtest-plan-v1.md'),
        code_sha256={str(p):base.sha(p) for p in (Path(__file__),Path(study.__file__),Path(base.__file__))}))
    for si,st in enumerate(stocks):
        if time.monotonic()-start>SPEC.seconds:raise TimeoutError('timing study budget')
        print(f'{si+1}/10 {st["code"]}',flush=True)
        folder=origin/st['code'];m=store.read(folder/'manifest.json')
        if m['status']!='complete':raise ValueError('incomplete stock')
        paths=[folder/x for x in ('input_30.json','input_60.json','full_events.json')]
        if sum(store.size(p) for p in paths)>SPEC.input_bytes:raise ValueError('input budget')
        for p in paths:
            if store.sha(p)!=m['artifacts_sha256'][p.name]:raise ValueError('input hash')
        obs,rows,events=[store.read(p) for p in paths]
        buys=[e for e in events if e['group'] in ('B1','B2','B3')]
        fs=[feature(rows,days,e) for e in buys]
        if any(feature(rows[:e['signal_index']+1],days,e)!=f for e,f in zip(buys,fs,strict=True)):
            raise ValueError('feature prefix mismatch')
        target=output/st['code'];target.mkdir()
        save(target/'features.json',fs)
        times,cache=study.observations(obs,days)
        for group in ('B1','B2','B3'):
            active=[f for f in fs if f['group']==group and f['time'][:10]>=study.PERIODS['full'][0]]
            diagnostics.append(dict(code=st['code'],group=group,n=len(active),median_lag=median(f['lag'] for f in active) if active else None,
                median_already_risen=median(f['already_risen'] for f in active) if active else None))
        for variant in SPEC.variants:
            selected=[e for e,f in zip(buys,fs,strict=True) if keep(f,variant)]
            summary=study.summarize(selected,times,cache)
            if variant=='all':
                old_folder=previous/f'{st["code"]}_baseline'
                old_m=store.read(old_folder/'manifest.json')
                if store.sha(old_folder/'summary.json')!=old_m['artifacts_sha256']['summary.json'] or summary!=store.read(old_folder/'summary.json'):
                    raise ValueError('baseline regression')
            save(target/f'{variant}.json',summary)
            save(target/f'{variant}_ids.json',[e['event_id'] for e in selected])
            cells.append(dict(code=st['code'],name=st['name'],variant=variant,summary=summary))
        save(target/'manifest.json',dict(status='complete',source_manifest_sha256=store.sha(folder/'manifest.json'),
            baseline_equal=True,feature_prefix=True,artifacts_sha256={p.name:base.sha(p) for p in target.iterdir()}))
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>SPEC.output_bytes:raise ValueError('output budget')
    store.verify_unchanged()
    results=aggregate(cells)
    save(output/'aggregate.json',results);save(output/'diagnostics.json',diagnostics)
    candidates=[v for v in SPEC.variants if v!='all' and all(s['gate'] for s in results if s['variant']==v and s['period'] in ('early','late'))]
    save(output/'manifest.json',dict(status='complete',seconds=time.monotonic()-start,stocks=len(stocks),candidates=candidates,
        baseline_equal=True,feature_prefix=True,aggregate_sha256=base.sha(output/'aggregate.json'),setup_sha256=base.sha(output/'setup.json')))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
