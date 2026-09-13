"""Paired exits for frozen Chan entries; no portfolio or new signal generation."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from statistics import mean
import time

from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan.stock_calendar_opportunity import grid,tradable
from scripts.research.index_market.chan.stock_parameter_study import PERIODS
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class ExitSpec:
    source: str = 'calendar'
    arms: tuple = ('fixed10','sell','structure','fixed60')
    fixed_days: int = 10
    max_days: int = 60
    bars_day: int = 8
    seconds: int = 180
    input_bytes: int = 16*1024**2
    output_bytes: int = 64*1024**2


SPEC=ExitSpec()


def simulate(times,rows,signal_index,mode,triggers=()):
    if mode not in SPEC.arms:raise ValueError('unknown exit')
    entry=signal_index+1
    if entry>=len(rows) or not tradable(rows[entry]):return dict(status='entry_untradable')
    horizon=SPEC.fixed_days if mode=='fixed10' else SPEC.max_days
    deadline=signal_index+horizon*SPEC.bars_day
    if deadline>=len(rows):return dict(status='insufficient_horizon')
    pending=None
    for j in range(entry,len(rows)):
        can_sell=tradable(rows[j]) and times[j][:10]>times[entry][:10]
        if pending is not None and j>pending and can_sell:
            price,phase,reason=rows[j]['open'],'open',mode
            break
        if j>=deadline and can_sell:
            price=rows[j]['close'] if j==deadline else rows[j]['open']
            phase='close' if j==deadline else 'open'
            reason='fixed' if mode.startswith('fixed') else 'timeout'
            break
        if mode in ('sell','structure') and pending is None and j<deadline and j in triggers:
            pending=j
    else:return dict(status='unclosed')
    buy_price=rows[entry]['open']
    observed=[r for r in rows[entry:j+(phase=='close')] if tradable(r)]
    return dict(status='closed',entry_index=entry,entry_bar=times[entry],entry_price=buy_price,
        exit_index=j,exit_time=times[j],exit_price=price,exit_phase=phase,reason=reason,
        trigger_time=times[pending] if pending is not None else None,
        deadline=times[deadline],delay_slots=max(0,j-deadline),
        holding_days=(j-entry+(phase=='close'))/SPEC.bars_day,
        return_value=price/buy_price-1,
        adverse=min([0,price/buy_price-1]+[r['low']/buy_price-1 for r in observed]),
        favorable=max([0,price/buy_price-1]+[r['high']/buy_price-1 for r in observed]))


def paired(cases,lo,hi):
    result=[]
    for c in cases:
        if not lo<=c['signal_time'][:10]<=hi:continue
        if all(x['status']=='closed' and x['exit_time'][:10]<=hi for x in c['arms'].values()):
            result.append(c)
    return result


def disjoint(cases):
    result=[];end=-1
    for c in sorted(cases,key=lambda c:c['signal_index']):
        if c['signal_index']+1>end:
            result.append(c);end=max(x['exit_index'] for x in c['arms'].values())
    return result


def summarize(cases):
    out={}
    for mode in SPEC.arms:
        xs=[c['arms'][mode] for c in cases]
        if not xs:out[mode]=dict(n=0);continue
        values=sorted(x['return_value'] for x in xs)
        out[mode]=dict(n=len(xs),mean=mean(values),win=mean(x['return_value']>0 for x in xs),
            loss_rate=mean(x['return_value']<0 for x in xs),holding_days=mean(x['holding_days'] for x in xs),
            adverse=mean(x['adverse'] for x in xs),favorable=mean(x['favorable'] for x in xs),
            vs10=mean(c['arms'][mode]['return_value']-c['arms']['fixed10']['return_value'] for c in cases),
            vs60=mean(c['arms'][mode]['return_value']-c['arms']['fixed60']['return_value'] for c in cases),
            without_best=mean(values[:-1]) if len(values)>1 else None,reasons=dict(Counter(x['reason'] for x in xs)))
    return out


def execute(output):
    output=base.safe_output(output);store=StockResearchStore();src=store.root_key(SPEC.source)
    origin=store.read(src/'source.json')
    for p,h in origin['code_sha256'].items():
        store.verify_code(p,h)
    dates_path=store.root_key('initial')/'source.json'
    if store.sha(dates_path)!=origin['previous_source_sha256']:raise ValueError('calendar provenance')
    days=store.read(dates_path)['days']
    statuses=store.read(src/'status_10.json')
    output.mkdir();started=time.monotonic();all_summaries=[]
    save(output/'setup.json',dict(spec=asdict(SPEC),periods=PERIODS,source_sha256=store.sha(src/'source.json'),input_store=store.receipt,
        code_sha256={str(p):base.sha(p) for p in (Path(__file__),Path(base.__file__))},
        plan_sha256=base.sha(base.REPO/'docs/product/stock-chan-share-position-backtest-plan-v1.md')))
    for si,st in enumerate(statuses):
        if time.monotonic()-started>SPEC.seconds:raise TimeoutError('study budget')
        print(f'{si+1}/10 {st["code"]}',flush=True)
        folder=src/st['code'];manifest=store.read(folder/'manifest.json')
        if manifest['status']!='complete':raise ValueError('incomplete source')
        paths=[folder/x for x in ('input_30.json','input_60.json','full_events.json')]
        if sum(store.size(p) for p in paths)>SPEC.input_bytes:raise ValueError('input budget')
        for p in paths:
            if store.sha(p)!=manifest['artifacts_sha256'][p.name]:raise ValueError('input fingerprint')
        obs,structure,events=[store.read(p) for p in paths]
        times,rows=grid(obs,days);indices={t:i for i,t in enumerate(times)}
        buys=defaultdict(list);sells=defaultdict(set)
        for e in events:
            if not e['sure'] or structure[e['signal_index']]['time']!=e['signal_time']:raise ValueError('event time')
            i=indices[e['signal_time']]
            if e['group'] in ('B1','B2','B3') and e['signal_time'][:10]>=PERIODS['full'][0]:buys[i].append(e)
            if e['group'] in ('S1','S2','S3'):sells[e['group']].add(i)
        cases=[]
        for i,es in sorted(buys.items()):
            if any(not 0<=e['anchor_index']<=e['signal_index'] for e in es):raise ValueError('future anchor')
            stop=min(structure[e['anchor_index']]['low'] for e in es)
            sell_triggers=set().union(*(sells['S'+e['group'][1:]] for e in es))
            stop_triggers={indices[r['time']] for r in structure if r['close']<stop}
            arms={mode:simulate(times,rows,i,mode,sell_triggers if mode=='sell' else stop_triggers if mode=='structure' else ()) for mode in SPEC.arms}
            cases.append(dict(code=st['code'],signal_index=i,signal_time=times[i],types=sorted({e['group'] for e in es}),
                event_ids=[e['event_id'] for e in es],frozen_low=stop,arms=arms))
        summaries=[]
        for period,(lo,hi) in PERIODS.items():
            common=paired(cases,lo,hi)
            selected=[c for c in cases if lo<=c['signal_time'][:10]<=hi]
            summaries.append(dict(period=period,opportunities=len(selected),common=len(common),
                excluded=len(selected)-len(common),exclusion_reasons=dict(Counter(
                    'outside_period' if all(x['status']=='closed' for x in c['arms'].values()) else '|'.join(sorted({x['status'] for x in c['arms'].values() if x['status']!='closed'}))
                    for c in selected if c not in common)),
                summary=summarize(common),nonoverlap=summarize(disjoint(common)),
                annual={y:summarize([c for c in common if c['signal_time'][:4]==y]) for y in sorted({c['signal_time'][:4] for c in common})}))
        target=output/st['code'];target.mkdir()
        save(target/'cases.json',cases);save(target/'summary.json',summaries)
        save(target/'manifest.json',dict(status='complete',source_manifest_sha256=store.sha(folder/'manifest.json'),
            artifacts_sha256={p.name:base.sha(p) for p in target.iterdir()}))
        all_summaries.append(dict(code=st['code'],name=st['name'],periods=summaries))
    aggregate=[]
    for period in PERIODS:
        ps=[next(x for x in s['periods'] if x['period']==period) for s in all_summaries]
        for mode in SPEC.arms:
            xs=[p['summary'][mode] for p in ps if p['summary'][mode]['n']]
            ns=[p['nonoverlap'][mode] for p in ps if p['nonoverlap'][mode]['n']]
            robust=[x['without_best'] for x in xs if x['without_best'] is not None]
            aggregate.append(dict(period=period,mode=mode,stocks=len(xs),n=sum(x['n'] for x in xs),
                **{k:mean(x[k] for x in xs) if xs else None for k in ('mean','win','loss_rate','holding_days','adverse','favorable','vs10','vs60')},
                positive_vs10=sum(x['vs10']>0 for x in xs),positive_vs60=sum(x['vs60']>0 for x in xs),
                nonoverlap_mean=mean(x['mean'] for x in ns) if ns else None,
                nonoverlap_vs10=mean(x['vs10'] for x in ns) if ns else None,
                without_best=mean(robust) if robust else None,robust_stocks=len(robust)))
    store.verify_unchanged()
    save(output/'aggregate.json',aggregate)
    save(output/'manifest.json',dict(status='complete',seconds=time.monotonic()-started,stocks=len(statuses),
        setup_sha256=base.sha(output/'setup.json'),aggregate_sha256=base.sha(output/'aggregate.json')))
    if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>SPEC.output_bytes:raise ValueError('output budget')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
