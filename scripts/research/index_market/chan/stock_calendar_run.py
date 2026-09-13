"""Complete the fixed random cohort with verified suspension handling."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from scripts.research.index_market.chan import stock_calendar_opportunity as calendar
from scripts.research.index_market.chan import stock_random10 as prior
from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan import stock_opportunity_filters as filters
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.stock_chan_replay_data import Reader, SPEC as READ, LAKE
from scripts.research.index_market.chan.stock_qfq_run import source_gate, run_signals
from scripts.research.index_market.chan.stock_qfq_model import SPEC as QFQ
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_research_store import StockResearchStore

PREVIOUS = 'initial'


def validate(rows, days, code, freq, suspended):
    expected=[f'{d} {s}' for d in days if d not in suspended for s in slots(freq)]
    if [r['time'] for r in rows]!=expected:
        raise ValueError('unexplained grid gap')
    for r in rows:
        if r['code']!=code or r['frequency']!=freq or r['exchange']!=('SSE' if code.endswith('.SH') else 'SZSE') or r['date']!=r['time'][:10]:
            raise ValueError('identity mismatch')
        if any(r[k] is None or not math.isfinite(r[k]) for k in ('open','high','low','close','vol','amount')):
            raise ValueError('nonfinite data')
        if not 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:
            raise ValueError('invalid OHLC')
        positive=r['vol']>0 and r['amount']>0
        flat_zero=r['vol']==r['amount']==0 and r['low']==r['high']
        if not (positive or flat_zero):
            raise ValueError('invalid zero/negative volume')


def execute(output):
    output=base.safe_output(output)
    source=source_gate()
    store=StockResearchStore()
    previous=store.root_key(PREVIOUS)
    old_source=store.read(previous/'source.json')
    for p,h in old_source['code_sha256'].items():
        store.verify_code(p,h)
    days=old_source['days']
    for p,h in old_source['source_hashes'].items():
        if base.sha(Path(p))!=h:
            raise ValueError('calendar/lifecycle changed; revalidate cohort')
    output.mkdir()
    save(output/'source.json',dict(previous_source_sha256=store.sha(previous/'source.json'),source=source,
        input_store=store.receipt,
        plan_sha256=base.sha(base.REPO/filters.SPEC.plan),codes=prior.CODES,
        code_sha256={str(p):base.sha(p) for p in (Path(__file__),Path(calendar.__file__),Path(filters.__file__),Path(base.__file__))}))
    started_all=time.monotonic()
    statuses=[]
    for code in prior.CODES:
        if time.monotonic()-started_all>1800:
            raise TimeoutError('batch budget')
        started=time.monotonic()
        old=previous/code
        manifest=store.read(old/'manifest.json')
        for name,h in manifest['artifacts_sha256'].items():
            if store.sha(old/name)!=h:
                raise ValueError('prior artifact changed')
        folder=output/code
        folder.mkdir()
        reader=Reader(replace(READ,max_files=32,max_bytes=16*1024**2,query_seconds=30))
        status=dict(code=code,name=manifest['name'],status='running')
        print(f'{len(statuses)+1}/10 {code}',flush=True)
        try:
            data={}
            reused=manifest['status']=='complete'
            for freq in (30,60):
                if reused:
                    data[freq]=store.read(old/f'input_{freq}.json')
                else:
                    paths=[LAKE/f'gold/quote/stk_mins_qfq/freq={freq}/ts_code={code}/year={y}/part-000.parquet' for y in range(2021,2027)]
                    data[freq]=reader.read(paths,prior.SQL,[[str(p) for p in paths],QFQ.start,QFQ.end],10000 if freq==30 else 5000)
            missing=sorted(set(days)-{r['date'] for r in data[30]})
            susp=[]
            if missing:
                paths=[LAKE/f'silver/quote/stock_suspend_daily/trade_date={d}/part-000.parquet' for d in missing]
                susp=reader.read(paths,"SELECT CAST(trade_date AS VARCHAR) AS day,suspend_type,suspend_timing FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=? ORDER BY trade_date",[[str(p) for p in paths],code],100)
                for d in missing:
                    records=[s for s in susp if s['day']==d]
                    if not any(s['suspend_type']=='S' and not (s['suspend_timing'] or '').strip() for s in records) or any(s['suspend_type']=='R' for s in records):
                        raise ValueError('unconfirmed suspension')
            for freq in (30,60):
                validate(data[freq],days,code,freq,set(missing))
                save(folder/f'input_{freq}.json',data[freq])
            lookup={r['time']:r for r in data[30]}
            if any(abs(r['close']/lookup[r['time']]['close']-1)>1e-7 for r in data[60]):
                raise ValueError('price scale mismatch')
            if reused:
                events=store.read(old/'full_events.json')
                checks=store.read(old/'signal_checks.json')
                save(folder/'full_events.json',events)
                save(folder/'signal_checks.json',checks)
            else:
                events,_,checks=run_signals(data[60],folder,started,replace(QFQ,code=code,frequency=60,total_seconds=180,replay_seconds=30))
            buys=[e for e in events if e['group'] in ('B1','B2','B3')]
            fs=[filters.features(data[60],e) for e in buys]
            if any(filters.features(data[60][:e['signal_index']+1],e)!=f for e,f in zip(buys,fs,strict=True)):
                raise ValueError('filter prefix')
            save(folder/'features.json',fs)
            save(folder/'data_checks.json',dict(suspension_days=missing,suspension_records=susp,
                zero_times=[r['time'] for r in data[30] if r['vol']==0],reused_signals=reused))
            for variant in filters.SPEC.variants:
                r=calendar.evaluate(data[30],days,[e for e,f in zip(buys,fs,strict=True) if filters.passes(f,variant)])
                if reused:
                    previous_result=store.read(old/f'{variant}.json')
                    if r['recall']!=previous_result['recall']:
                        raise ValueError('complete grid recall regression')
                    for a,b in zip(r['summary'],previous_result['summary'],strict=True):
                        if {k:v for k,v in a.items() if k!='censor_reasons'}!=b:
                            raise ValueError('complete grid summary regression')
                save(folder/f'{variant}.json',r)
            status.update(status='complete' if checks['all_passed'] else 'stability_differences',complete_grid_control=reused)
            if time.monotonic()-started>180:
                raise TimeoutError('stock budget')
        except (ValueError,TimeoutError) as exc:
            status.update(status='pending',error=str(exc))
        finally:
            status.update(seconds=time.monotonic()-started,source_hashes=reader.hashes,queries=reader.queries,
                read_audit=reader.verify_unchanged(),previous_manifest_sha256=store.sha(old/'manifest.json'))
            status['artifacts_sha256']={p.name:base.sha(p) for p in folder.iterdir()}
            save(folder/'manifest.json',status)
            statuses.append(status)
            save(output/f'status_{len(statuses):02d}.json',statuses)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>256*1024**2:
            raise ValueError('output budget')
    store.verify_unchanged()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
