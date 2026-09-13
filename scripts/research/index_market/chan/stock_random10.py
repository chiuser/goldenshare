"""Frozen random ten stocks: bounded direct DG 60m opportunity replication."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan import stock_opportunity_filters as filters
from scripts.research.index_market.chan.stock_chan_replay_data import Reader, SPEC as READ, LAKE, validate_rows
from scripts.research.index_market.chan.stock_qfq_run import source_gate, run_signals
from scripts.research.index_market.chan.stock_qfq_model import SPEC as QFQ
from scripts.research.index_market.chan.stock_timeframe_opportunity import project, attach_detection_indices
from scripts.research.index_market.chan.run_m0 import save

CODES = ('002084.SZ','603360.SH','300407.SZ','002587.SZ','000731.SZ','605186.SH','002252.SZ','300263.SZ','002225.SZ','688069.SH')
SQL = """SELECT ts_code AS code,freq AS frequency,exchange,'qfq' AS price_basis,
CAST(trade_date AS VARCHAR) AS date,CAST(trade_time AS VARCHAR) AS time,
open,high,low,close,vol,amount FROM read_parquet(?,hive_partitioning=false)
WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY trade_time"""


def validate_pair(original, rows, days, code):
    for frequency, data in ((30, original), (60, rows)):
        validate_rows(data, days, code, QFQ.start, QFQ.end+' 23:59:59', days[250], replace(READ, frequency=frequency))
    lookup = {r['time']: i for i,r in enumerate(original)}
    for r in rows:
        i = lookup[r['time']]
        if abs(r['close']/original[i]['close']-1) > 1e-7:
            raise ValueError('QFQ scale mismatch')
        r['source_end'] = i


def execute(output):
    output = base.safe_output(output)
    source = source_gate()
    control = base.REPO/'reports/stock_opportunity_002245_60m_20260912_audited'
    frozen = filters.checked_report(control)
    for p,h in frozen['code_sha256'].items():
        if base.sha(Path(p)) != h:
            raise ValueError('frozen code changed')
    global_start = time.monotonic()
    meta = Reader(replace(READ,max_files=2,max_bytes=16*1024**2,query_seconds=30))
    calendar = LAKE/'silver/calendar/trade_calendar/full/part-000.parquet'
    life = LAKE/'silver/basic/stock_lifecycle/full/part-000.parquet'
    days = [r['date'] for r in meta.read([calendar], "SELECT CAST(trade_date AS VARCHAR) AS date FROM read_parquet(?,hive_partitioning=false) WHERE exchange='SSE' AND is_open AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY trade_date",[str(calendar),QFQ.start,QFQ.end],2000)]
    lives = meta.read([life], "SELECT ts_code,name FROM read_parquet(?,hive_partitioning=false) WHERE ts_code IN (SELECT unnest(?)) AND is_cny_stock AND exchange IN ('SSE','SZSE') AND list_date<=CAST(? AS DATE) AND (delist_date IS NULL OR delist_date>CAST(? AS DATE))",[str(life),list(CODES),QFQ.start,QFQ.asof],10)
    if {r['ts_code'] for r in lives} != set(CODES) or len(lives)!=10:
        raise ValueError('fixed universe no longer eligible')
    names = {r['ts_code']:r['name'] for r in lives}
    meta.verify_unchanged()
    output.mkdir()
    save(output/'source.json',dict(source=source,source_hashes=meta.hashes,queries=meta.queries,days=days,stocks=lives,plan_sha256=base.sha(base.REPO/filters.SPEC.plan),code_sha256={str(p):base.sha(p) for p in [Path(__file__),Path(base.__file__),Path(filters.__file__)]}))
    statuses=[]
    for code in CODES:
        if time.monotonic()-global_start>1800:
            raise TimeoutError('batch budget')
        started=time.monotonic()
        folder=output/code
        folder.mkdir()
        reader=Reader(replace(READ,max_files=12,max_bytes=16*1024**2,query_seconds=30))
        status=dict(code=code,name=names[code],status='running')
        print(f'{len(statuses)+1}/10 {code} {names[code]}',flush=True)
        try:
            data={}
            for freq in (30,60):
                paths=[LAKE/f'gold/quote/stk_mins_qfq/freq={freq}/ts_code={code}/year={y}/part-000.parquet' for y in range(2021,2027)]
                data[freq]=reader.read(paths,SQL,[[str(p) for p in paths],QFQ.start,QFQ.end],10000 if freq==30 else 5000)
            validate_pair(data[30],data[60],days,code)
            for freq,rows in data.items():
                save(folder/f'input_{freq}.json',rows)
            events,_,checks=run_signals(data[60],folder,started,replace(QFQ,code=code,name=names[code],frequency=60,total_seconds=180,replay_seconds=30))
            buys=[e for e in events if e['group'] in ('B1','B2','B3')]
            fs=[filters.features(data[60],e) for e in buys]
            if any(filters.features(data[60][:e['signal_index']+1],e)!=f for e,f in zip(buys,fs,strict=True)):
                raise ValueError('filter prefix mismatch')
            save(folder/'features.json',fs)
            for variant in filters.SPEC.variants:
                r=base.evaluate(data[30],[project(e,data[60]) for e,f in zip(buys,fs,strict=True) if filters.passes(f,variant)])
                filters.enrich(data[30],r)
                attach_detection_indices(r,data[60])
                save(folder/f'{variant}.json',r)
            status['status']='complete' if checks['all_passed'] else 'stability_differences'
        except (ValueError,TimeoutError) as exc:
            status.update(status='excluded_pending_audit',error=str(exc))
        finally:
            status.update(seconds=time.monotonic()-started,read_audit=reader.verify_unchanged(),source_hashes=reader.hashes,queries=reader.queries)
            status['artifacts_sha256']={p.name:base.sha(p) for p in folder.iterdir()}
            save(folder/'manifest.json',status)
            statuses.append(status)
            save(output/f'status_{len(statuses):02d}.json',statuses)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>256*1024**2:
            raise ValueError('output budget')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
