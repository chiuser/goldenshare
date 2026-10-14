"""Paired full-history readonly source comparison, includes all original guards."""
import sys,json,time,hashlib,resource
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from datetime import date
import duckdb
from src.foundation.clients.local_lake import major_index_mins_reader as m
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from reports.xxm_minute_reader_optimization_20261014.prototype import FastReader
OUT=Path(__file__).resolve().parent

def fingerprint(rows):
    h=hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row,sort_keys=True,default=str,separators=(',',':')).encode())
    return h.hexdigest()

def read(kind,freq):
    reader=m.MajorIndexMinsLakeReader(FORMAL_LAKE_ROOT) if kind=='original' else FastReader(FORMAL_LAKE_ROOT)
    request=m.IndexMinuteReadRequest('000001.SH',freq,None,date(2026,10,14),1000,None)
    started=time.perf_counter();sig_started=started
    signatures={k:reader.history_source_signature(request,dataset=k) for k in ('bars','indicators')}
    sig_seconds=time.perf_counter()-sig_started
    stages={};digest={};counts={}
    for k in ('bars','indicators'):
        t=time.perf_counter();page=reader.read_complete_history(request,dataset=k,timeout_seconds=8)
        stages[k]=time.perf_counter()-t;counts[k]=dict(rows=page.count,files=page.scanned_file_count)
        digest[k]=fingerprint(page.rows)
    row=dict(kind=kind,freq=freq,signatureSeconds=sig_seconds,readSeconds=stages,totalSeconds=time.perf_counter()-started,counts=counts,digest=digest,rssMaxBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return row,signatures

if __name__=='__main__':
    records=[]
    for freq in (60,90,120):
        for pair in range(3):
            kinds=('original','candidate') if pair%2==0 else ('candidate','original')
            rows={};sigs={}
            for kind in kinds:
                row,sig=read(kind,freq);row['pair']=pair;records.append(row);rows[kind]=row;sigs[kind]=sig
                print(json.dumps(row),flush=True)
            assert sigs['original']==sigs['candidate']
            assert rows['original']['digest']==rows['candidate']['digest'] and rows['original']['counts']==rows['candidate']['counts']
            (OUT/'comparison.json').write_text(json.dumps(dict(status='IN_PROGRESS',records=records),indent=2))
    (OUT/'comparison.json').write_text(json.dumps(dict(status='PASS',records=records),indent=2))
