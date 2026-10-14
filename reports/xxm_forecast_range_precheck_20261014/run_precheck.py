import csv,json,time,math,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from reports.xxm_forecast_range_precheck_20261014.range_model import make_result
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS,CN_ZONE
from datetime import date,datetime
OUT=Path(__file__).resolve().parent
SOURCE=OUT.parent/'xxm_source_audit_20261013_213852'
CAL=OUT.parent/'xxm_forecast_precheck_20261014/future_sse_calendar.json'

def frozen(period):
    file=SOURCE/('daily_source.csv' if period=='day' else f'minute_{period[1:]}_source.csv')
    with file.open() as f:rows=list(csv.DictReader(f))
    if period=='day':bars=tuple(XxmBar(r['trade_date'],float(r['close']),float(r['macd_dif_bfq']),float(r['macd_dea_bfq']),float(r['macd_bfq'])) for r in rows)
    else:bars=tuple(XxmBar(r['trade_time'].replace(' ','T')+'+08:00',float(r['close']),float(r['macd_dif']),float(r['macd_dea']),float(r['macd'])) for r in rows)
    return bars,file

def endpoints(period,through):
    slots=[]
    records = {r['trade_date']:r for r in json.loads((SOURCE/'sse_minute_calendar.json').read_text())+json.loads(CAL.read_text())['rows']}
    for r in sorted(records.values(),key=lambda r:r['trade_date']):
        if not r['is_open']:continue
        for t in ([None] if period=='day' else ENDPOINTS[int(period[1:])]):
            stamp=r['trade_date'] if t is None else datetime.combine(date.fromisoformat(r['trade_date']),t,CN_ZONE).isoformat()
            if stamp>through:slots.append(stamp)
    assert len(slots)>=20
    return slots[:20]

if __name__=='__main__':
    allrows=[]
    for period in ('day','m60','m90','m120'):
        bars,file=frozen(period);c=XxmCalculator(period=period,source_identity='frozen-range-precheck')
        for b in bars:c.step(b)
        started=time.perf_counter()
        def check():
            if time.perf_counter()-started>.2:raise TimeoutError('200ms')
        try:
            p=recover_projection(bars,period,check)
            result=make_result(c,p,endpoints(period,bars[-1].time),check)
            seconds=time.perf_counter()-started
            body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
            (OUT/f'candidate_{period}.json').write_bytes(body)
            row=dict(period=period,status=result['status'],seconds=seconds,bytes=len(body),target=result['targetEndpoint'],activation=result['activation'])
        except Exception as exc:
            row=dict(period=period,error=f'{type(exc).__name__}: {exc}',seconds=time.perf_counter()-started)
            import traceback;traceback.print_exc()
        print(json.dumps(row,ensure_ascii=False),flush=True)
        allrows.append(row)
    (OUT/'initial_probe.json').write_text(json.dumps(allrows,ensure_ascii=False,indent=2))
