"""Three predeclared buy-side parameter contrasts; authenticated offline inputs."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace, asdict
import json
from pathlib import Path
from statistics import mean
import time

from scripts.research.index_market.chan import stock_calendar_opportunity as cal
from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan.minute_data import MinuteSpec
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.stock_qfq_run import source_gate
from scripts.research.index_market.chan.run_m0 import save, expanded
from scripts.research.index_market.chan.stock_research_store import StockResearchStore

SOURCE = 'calendar'
PERIODS = {'early':('2022-09-22','2024-08-31'), 'late':('2024-09-01','2026-06-30'),
           'full':('2022-09-22','2026-09-08')}
CHANGES = {'baseline':{}, 'div08':{'divergence_rate-buy':0.8},
           'retr06':{'max_bs2_rate-buy':0.6}, 'area':{'macd_algo-buy':'area'}}


@dataclass(frozen=True)
class ParameterSpec(MinuteSpec):
    mode: str = 'baseline'
    def chan_config(self):
        return dict(VARIANT_A.chan_config(), **CHANGES[self.mode])


def config_audit(spec):
    from ChanConfig import CChanConfig
    from Common.CEnum import MACD_ALGO
    before = expanded(CChanConfig(VARIANT_A.chan_config()))
    after = expanded(CChanConfig(spec.chan_config()))
    expected = json.loads(json.dumps(before))
    for key,value in CHANGES[spec.mode].items():
        if key == 'macd_algo-buy':
            value = MACD_ALGO.AREA.value
        expected['bs_point_conf']['b_conf'][key.removesuffix('-buy')] = value
    if expected != after:
        raise ValueError('expanded configuration not a single buy-side change')
    return after


def observations(rows, days):
    times,data = cal.grid(rows,days)
    result = {}
    for period,(lo,hi) in PERIODS.items():
        for h in (5,10,20):
            items={}; reasons={}; pools=defaultdict(list)
            for i,t in enumerate(times):
                if not lo<=t[:10]<=hi or data[i] is None:
                    continue
                x,reason=cal.outcome(times,data,i,h*8)
                if x is not None and x['exit_time'][:10]>hi:
                    x,reason=None,'period_end'
                if x is None:
                    reasons[i]=reason
                else:
                    items[i]=x
                    pools[(t[:4],t[11:])].append(x['return_value'])
            result[(period,h)] = (items,reasons,{k:mean(v) for k,v in pools.items()})
    return times,result


def summarize(events,times,cache):
    indices={t:i for i,t in enumerate(times)}
    result=[]
    for (period,h),(lookup,reasons,pools) in cache.items():
        lo,hi=PERIODS[period]
        for group in ('ALL','B1','B2','B3'):
            selected={indices[e['signal_time']] for e in events if e['buy'] and e['sure']
                and e['group'] in (('B1','B2','B3') if group=='ALL' else (group,)) and lo<=e['signal_time'][:10]<=hi}
            items=[lookup[i] for i in sorted(selected) if i in lookup]
            def stats(xs):
                if not xs:return dict(n=0,mean=None,matched=None,excess=None,without_best=None)
                values=sorted(x['return_value'] for x in xs)
                matched=mean(pools[(x['signal_time'][:4],x['signal_time'][11:])] for x in xs)
                return dict(n=len(xs),mean=mean(values),matched=matched,excess=mean(values)-matched,
                            without_best=mean(values[:-1]) if len(values)>1 else None)
            result.append(dict(period=period,horizon=h,group=group,total=len(selected),
                censored=dict(Counter(reasons[i] for i in selected if i not in lookup)),
                **stats(items),nonoverlap=stats(base.nonoverlap(items))))
    return result


def aggregate_cells(cells):
    out=[]
    for mode in CHANGES:
        for period in PERIODS:
            xs=[s for c in cells if c['mode']==mode for s in c['summary'] if s['period']==period and s['group']=='ALL' and s['horizon']==10]
            valid=[x for x in xs if x['n']]
            robust=[x['without_best'] for x in valid if x['without_best'] is not None]
            out.append(dict(mode=mode,period=period,stocks=len(valid),n=sum(x['n'] for x in valid),
                mean=mean(x['mean'] for x in valid) if valid else None,
                excess=mean(x['excess'] for x in valid) if valid else None,
                positive=sum(x['excess']>0 for x in valid),
                nonoverlap_excess=mean(x['nonoverlap']['excess'] for x in valid) if valid else None,
                robust_stocks=len(robust),without_best=mean(robust) if robust else None))
    for x in out:
        baseline=next(b for b in out if b['mode']=='baseline' and b['period']==x['period'])
        x['candidate_gate']=(x['stocks']>=8 and x['n']>=50 and x['positive']>=7 and
            x['robust_stocks']>=8 and x['without_best']>0 and x['excess']>0 and
            x['nonoverlap_excess']>0 and x['excess']>baseline['excess'])
    return out


def execute(output):
    output=base.safe_output(output)
    source=source_gate()
    store=StockResearchStore()
    origin=store.root_key(SOURCE)
    old=store.read(origin/'source.json')
    for p,h in old['code_sha256'].items():
        store.verify_code(p,h)
    previous=store.root_key('initial')/'source.json'
    if store.sha(previous)!=old['previous_source_sha256']:raise ValueError('calendar provenance')
    days=store.read(previous)['days']
    statuses=store.read(origin/'status_10.json')
    output.mkdir()
    start=time.monotonic();cells=[];configs={}
    for mode in CHANGES:
        configs[mode]=config_audit(ParameterSpec(mode=mode))
    receipt=dict(status='running',changes=CHANGES,periods=PERIODS,expanded_configs=configs,source=source,
        source_sha256=store.sha(origin/'source.json'),input_store=store.receipt,plan_sha256=base.sha(base.REPO/'docs/product/stock-chan-share-position-backtest-plan-v1.md'),
        code_sha256={str(p):base.sha(p) for p in (Path(__file__),Path(cal.__file__),Path(base.__file__),Path(__file__).with_name('minute_replay.py'))})
    save(output/'setup.json',receipt)
    for si,st in enumerate(statuses):
        folder=origin/st['code'];m=store.read(folder/'manifest.json')
        if m['status']!='complete':raise ValueError('incomplete input')
        for name,h in m['artifacts_sha256'].items():
            if store.sha(folder/name)!=h:raise ValueError('source artifact hash')
        rows=store.read(folder/'input_60.json')
        obs=store.read(folder/'input_30.json')
        times,cache=observations(obs,days)
        for mode in CHANGES:
            before=time.monotonic()
            if before-start>900:raise TimeoutError('whole study budget')
            target=output/f'{st["code"]}_{mode}';target.mkdir()
            spec=replace(ParameterSpec(mode=mode),codes=(st['code'],),frequencies=(60,),replay_seconds=30)
            def one(data):return replay(data,st['code'],60,spec)
            print(f'{si+1}/10 {st["code"]} {mode}',flush=True)
            events=one(rows)
            checks={}
            if mode=='baseline':
                checks['exact_baseline']=events==store.read(folder/'full_events.json')
            else:
                cutoff='2024-08-31 23:59:59'
                expected=[e for e in events if e['signal_time']<=cutoff]
                checks['prefix']=one([r for r in rows if r['time']<=cutoff])==expected
                future=[dict(r,**{k:r[k]*(1.37 if r['time']>cutoff else 1) for k in ('open','high','low','close')}) for r in rows]
                checks['future_isolation']=[e for e in one(future) if e['signal_time']<=cutoff]==expected
                checks['scale']=one([dict(r,**{k:r[k]*2 for k in ('open','high','low','close')}) for r in rows])==events
            save(target/'events.json',events)
            save(target/'checks.json',checks)
            summary=summarize(events,times,cache)
            save(target/'summary.json',summary)
            if not all(checks.values()):raise ValueError('signal stability failed')
            if time.monotonic()-before>90:raise TimeoutError('cell budget')
            cell=dict(code=st['code'],name=st['name'],mode=mode,summary=summary,checks=checks,seconds=time.monotonic()-before,
                      input_manifest_sha256=store.sha(folder/'manifest.json'))
            cells.append(cell)
            save(target/'manifest.json',dict(status='complete',**cell,artifacts_sha256={p.name:base.sha(p) for p in target.iterdir()}))
        save(output/f'progress_{si+1:02d}.json',dict(stocks=si+1,cells=len(cells),seconds=time.monotonic()-start))
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>256*1024**2:raise ValueError('output budget')
    store.verify_unchanged()
    aggregate=aggregate_cells(cells)
    save(output/'aggregate.json',aggregate)
    candidates=[mode for mode in CHANGES if mode!='baseline' and all(x['candidate_gate'] for x in aggregate if x['mode']==mode and x['period'] in ('early','late'))]
    save(output/'manifest.json',dict(status='complete',seconds=time.monotonic()-start,candidates=candidates,
        completed_cells=len(cells),all_checks=True,setup_sha256=base.sha(output/'setup.json'),aggregate_sha256=base.sha(output/'aggregate.json')))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
