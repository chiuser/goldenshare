"""Readonly full-replay versus original snapshot/restore batch checkpoint."""
import sys,time,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.research.index_market.tests.test_xxm_key_point_forecast import frozen,endpoints
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
OUT=Path(__file__).resolve().parent

def full(bars,period):
    c=XxmCalculator(period=period,source_identity='checkpoint-precheck')
    for b in bars:c.step(b)
    return c

def restored(bars,period,n,checkpoints):
    c=XxmCalculator(period=period,source_identity='checkpoint-precheck')
    offset=n//BUDGET.source_batch_rows*BUDGET.source_batch_rows
    if offset:c.restore(checkpoints[offset])
    for b in bars[offset:n]:c.step(b)
    return c

if __name__=='__main__':
    records=[]
    for period in ('day','m60','m90','m120'):
        bars=frozen(period);c=XxmCalculator(period=period,source_identity='checkpoint-precheck');snapshots={}
        for i,b in enumerate(bars,1):
            c.step(b)
            if i%BUDGET.source_batch_rows==0:snapshots[i]=c.snapshot()
        for n in sorted({1,249,250,len(bars)-4,len(bars)-1,len(bars)}|{v for v in (999,1000,1001,1999,2000,2001) if v<=len(bars)}):
            before=json.dumps(snapshots,sort_keys=True);t=time.perf_counter();original=full(bars[:n],period);full_seconds=time.perf_counter()-t
            t=time.perf_counter();candidate=restored(bars,period,n,snapshots);cached_seconds=time.perf_counter()-t
            assert candidate.snapshot()==original.snapshot() and json.dumps(snapshots,sort_keys=True)==before
            active=False
            if n>=250 and n>=len(bars)-4:
                p=recover_projection(bars[:n],period,lambda:None);slots=endpoints(period,bars[n-1].time)
                assert forecast(original,p,slots)==forecast(candidate,p,slots);active=True
            row=dict(period=period,prefixRows=n,replayedRows=n%BUDGET.source_batch_rows,fullSeconds=full_seconds,checkpointSeconds=cached_seconds,forecastEqual=active,checkpointCount=len(snapshots),checkpointJsonBytes=len(json.dumps(snapshots).encode()))
            records.append(row);print(json.dumps(row),flush=True)
    (OUT/'checkpoint_comparison.json').write_text(json.dumps(dict(status='PASS',records=records,rule='original full history still read/validated; same 1000-row batch snapshots in existing 64MiB cache; no new knob/TTL/table; whole EMA calibration unchanged'),indent=2))
