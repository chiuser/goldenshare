from pathlib import Path
from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager
from datetime import date,datetime
import hashlib,json,time
from copy import deepcopy
from candidate import CandidateCalculator, OriginalCalculator
from scripts.research.index_market.xxm.acceptance import load_source
from src.biz.services.wealth.market.index_detail_xxm import forecast_detector
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast,inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import build_display_context,make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection,ProjectionPrecisionError
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS,CN_ZONE

ROOT=Path('/Users/congming/github/goldenshare');OUT=ROOT/'reports/xxm_bottom_history_precheck_20261016';SOURCE=ROOT/'reports/xxm_source_audit_20261013_213852'
future=ROOT/'reports/xxm_forecast_precheck_20261014/future_sse_calendar.json'
rows=json.loads((SOURCE/'sse_minute_calendar.json').read_text())
calendar={r['trade_date']:r['is_open'] for r in rows}
for r in json.loads(future.read_text())['rows']:
    if r['trade_date'] in calendar:assert calendar[r['trade_date']]==r['is_open']
    calendar[r['trade_date']]=r['is_open']

def slots(period,through):
    answer=[]
    for day,opened in sorted(calendar.items()):
        if day<through[:10] or not opened:continue
        for t in ([None] if period=='day' else ENDPOINTS[int(period[1:])]):
            stamp=day if t is None else datetime.combine(date.fromisoformat(day),t,CN_ZONE).isoformat()
            if stamp>through:answer.append(stamp)
            if len(answer)==20:return tuple(answer)
    raise AssertionError('future calendar missing')

@contextmanager
def detector(cls):
    old=forecast_detector.XxmCalculator;forecast_detector.XxmCalculator=cls
    try:yield
    finally:forecast_detector.XxmCalculator=old

def model(period,bars,n,cls,checkpoints,snapshots,confirmation):
    through=bars[n-1].time;clocks=('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in ENDPOINTS[int(period[1:])])
    start=time.perf_counter()
    def check():
        if (time.perf_counter()-start)*1000>200:raise TimeoutError('200ms')
    c=cls(period=period,source_identity='forecast-precheck:'+period)
    offset=n//1000*1000
    if offset:c.restore(deepcopy(checkpoints[offset]))
    for b in bars[offset:n]:c.step(b)
    check();assert c.snapshot()==snapshots[n]
    before=c.snapshot();last_confirm=confirmation[n]
    confirmed=c.state=='STRUCTURE' or last_confirm and last_confirm['time']==through
    with detector(cls):
        if confirmed:r=inactive_result('CONFIRMED')
        else:
            try:r=forecast(c,recover_projection(tuple(bars[:n]),period,check),slots(period,through),check)
            except ProjectionPrecisionError as exc:r=inactive_result('PRECISION_PENDING',exc.reason)
        actual_confirm=r['status']=='CONFIRMED'
        r.update(confirmedAt=last_confirm['time'] if actual_confirm and last_confirm else None,
                 confirmedDirection=last_confirm['direction'] if actual_confirm and last_confirm else None)
        r['direction']=r['confirmedDirection'] if actual_confirm else 'TOP' if bars[n-1].hist>0 else 'BOTTOM' if bars[n-1].hist<0 else None
        r['applicabilityText']='仅适用于本周期已计算的收盘条件；实际收盘后更新。' if r['activation'] else '按当前真实状态与明确的中间走势假设计算。'
        r['invalidationText']='原钝化消失、零柱或前序走势变化时重新计算；未达结构条件不等于钝化已消失。' if r['status'] in ('READY','CONDITIONAL_ENTRY','ENTRY_ONLY') else '新完成行情到达后重新判断。'
        ctx=build_display_context(bars[:n],period,through,r,clocks,check)
        r['display']=make_display(r,period,through,'REPLAY',ctx,check)
        check()
        child=forecast_detector.clone(c);assert child.snapshot()==before
        child.snapshot()['history'].clear();assert c.snapshot()==before
    assert c.snapshot()==before
    return r,(time.perf_counter()-start)*1000

summary={'calendarAdditionalSource':str(future.relative_to(ROOT)),'calendarAdditionalSha256':hashlib.sha256(future.read_bytes()).hexdigest(),'priceLookAhead':False,'productPatched':False,'temporaryModuleBinding':'scratch process only, restored after each model call','periods':{}}
for period in ('day','m60','m90','m120'):
    bars=load_source(SOURCE,period);times=[b.time for b in bars]
    events=json.loads((OUT/f'replay_{period}.json').read_text())['events']
    cuts={len(bars)}
    # Every added historical event, plus before/after it; earliest rows still exercise original calibration protection.
    for e in events:
        n=times.index(e['time'])+1;cuts.update(k for k in (n-1,n,n+1) if 0<k<=len(bars))
    for day in ('2024-07-09','2024-07-11','2024-07-22','2024-07-23','2024-07-31','2024-08-02','2024-08-05','2024-08-06','2024-08-13','2024-08-14','2024-08-15','2024-08-22','2024-08-30','2024-09-02','2024-09-03','2024-09-04','2026-07-10','2026-07-13','2026-09-30'):
        cuts.add(bisect_right(times,day if period=='day' else day+'T15:00:00+08:00'))
    cuts=sorted(k for k in cuts if k>0)
    inputs={}
    for cls in (OriginalCalculator,CandidateCalculator):
        c=cls(period=period,source_identity='forecast-precheck:'+period);cp={};snaps={};confirmation={};last=None
        for n,b in enumerate(bars,1):
            step=c.step(b)
            last=next((e for e in reversed(step.events) if e['type']=='STRUCTURE'),last)
            if n%1000==0:cp[n]=c.snapshot()
            if n in cuts:snaps[n]=c.snapshot();confirmation[n]=last
        inputs[cls]=(cp,snaps,confirmation)
    results=[]
    for n in cuts:
        baseline,bt=model(period,bars,n,OriginalCalculator,*inputs[OriginalCalculator])
        proposed,ct=model(period,bars,n,CandidateCalculator,*inputs[CandidateCalculator])
        assert proposed==baseline,(period,bars[n-1].time,baseline,proposed)
        results.append(dict(through=bars[n-1].time,rows=n,status=proposed['status'],reason=proposed['reasonCode'],target=proposed['targetEndpoint'],baselineMs=bt,candidateMs=ct,result=proposed))
    (OUT/f'forecast_{period}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    summary['periods'][period]=dict(comparisons=len(results),mathAndDisplayIdentical=True,statuses=dict(Counter(r['status'] for r in results)),calibrationProtected=sum(r['reason']=='CALIBRATION_FAILED' for r in results),candidateMaxMs=max(r['candidateMs'] for r in results),baselineMaxMs=max(r['baselineMs'] for r in results),candidateMaxResultBytes=max(len(json.dumps(r['result'],ensure_ascii=False).encode()) for r in results),clonePreservesBottomState=True)
    (OUT/'forecast_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(period,json.dumps(summary['periods'][period]),flush=True)
print('ALL FORECAST COMPARISONS PASSED',sum(v['comparisons'] for v in summary['periods'].values()),flush=True)
