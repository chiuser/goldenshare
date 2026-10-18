"""Current product acceptance against sealed, pre-development evidence."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import time

from . import bottom_history_acceptance as b
from .acceptance import sha
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast,inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import build_display_context,make_display
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection,ProjectionPrecisionError

ROOT=Path(__file__).resolve().parents[4]
PRECHECK=ROOT/'reports/xxm_reference_rescue_forecast_precheck_20261017_01/run_02'
R1=ROOT/'reports/xxm_reference_rescue_20261017_01/run_01'
MATH_KEYS=('status','reasonCode','targetEndpoint','barsAhead','activation','assumption','targetEntryRanges','targetEntryExclusions','relations','commonConditions','examples','nextBarOutcomes')


def semantic(event):
    return {k:event[k] for k in ('time','type','direction','route','fromState','eventReference')}


def frozen_mode(source,out,sources):
    """Only product r2 against the sealed pre-development files and math."""
    from dataclasses import asdict
    import hashlib
    from .frozen_inputs import expected_unit, assert_expected_recognition, EXPECTATIONS, forecast_inventory
    from .forecast_expectations import verify_changed_forecast
    from .cross_index_daily import read_unit, seal
    calendar=b.calendar_rows(source);summary=dict(periods={},softwareUniqueFormulaProven=False,liveSource=False)
    totals=Counter();inventory=forecast_inventory()
    identity=dict(sourceManifestSha256=sha(source/'manifest.json'),expectedManifestSha256=sha(EXPECTATIONS/'manifest.json'),
                  detectorSpecHash=b.MAIN_SPEC.spec_hash,forecastSpecHash=FORECAST_SPEC.spec_hash,
                  code={str(p.relative_to(ROOT)):sha(p) for directory in (
                      ROOT/'src/biz/services/wealth/market/index_detail_xxm',ROOT/'scripts/research/index_market/xxm')
                      for p in directory.glob('*.py')})
    old_identity=read_unit(out,'frozen_identity')
    if old_identity is None:seal(out,'frozen_identity',identity)
    else:assert old_identity==identity,'Cannot resume changed code/source/expected'
    for period,bars in sources.items():
        checks={r['rows'] for r in json.loads((R1/f'result_{period}.json').read_text())['restored']}
        gates={}
        for gate in (.75,1.,1.2):
            unit=f'frozen_{period}_{gate}';old=read_unit(out,unit)
            if old is not None:
                events=old['events']
                gates[str(gate)]=old['summary'];totals.update(old['totals']);continue
            expected=json.loads((PRECHECK/f'forecasts_{period}_{gate}.json').read_text())
            wanted={r['rows'] for r in expected}
            calc,events,snapshots,confirmations=assert_expected_recognition(bars,'source',period,gate,cuts=wanted|checks)
            unit_totals=Counter();results=[]
            if gate==1.:
                for n in sorted(checks):
                    child=XxmCalculator(period=period,source_identity=calc.source_identity,spec=calc.spec)
                    for bar in bars[:n]:child.step(bar)
                    assert child.snapshot()==snapshots[n]
                    restored=XxmCalculator(period=period,source_identity=calc.source_identity,spec=calc.spec);restored.restore(snapshots[n])
                    for bar in bars[n:n+250]:assert child.step(bar)==restored.step(bar)
                unit_totals['prefixRestoreCuts']+=len(checks)
            records={r['rows']:r for r in inventory if r['period']==period and r['gate']==gate}
            proofs={r['rows']:r for r in expected_unit(f'independent_real_{period}_{gate}')}
            for index,old in enumerate(expected,1):
                n=old['rows'];child=XxmCalculator(period=period,source_identity=calc.source_identity,spec=calc.spec);child.restore(snapshots[n]);saved=child.snapshot()
                started=time.perf_counter()
                def check():
                    if time.perf_counter()-started>.2:raise TimeoutError('200ms model budget')
                if child.state=='STRUCTURE' or confirmations[n] and confirmations[n]['time']==bars[n-1].time:
                    result=inactive_result('CONFIRMED')
                else:
                    try:result=forecast(child,recover_projection(tuple(bars[:n]),period,check),b.future_slots(calendar,period,bars[n-1].time),check)
                    except ProjectionPrecisionError as exc:result=inactive_result('PRECISION_PENDING',exc.reason)
                result.update(direction='TOP' if child.wave.sign>0 else 'BOTTOM' if child.wave.sign<0 else None,
                              rearmContext=child.pending_rearm,confirmedAt=confirmations[n]['time'] if result['status']=='CONFIRMED' else None,
                              confirmedDirection=confirmations[n]['direction'] if result['status']=='CONFIRMED' else None)
                clocks=('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in b.ENDPOINTS[int(period[1:])])
                context=build_display_context(bars[:n],period,bars[n-1].time,result,clocks,check)
                result['display']=make_display(result,period,bars[n-1].time,'REPLAY',context,check)
                check();ms=(time.perf_counter()-started)*1000
                record=records[n]
                # Bind the original full response too; no replacing old goldens.
                digest=hashlib.sha256(json.dumps(old['result'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                assert digest==record['oldResultSha256']
                if record['category']=='RETAIN_OLD_EXPECTATION':
                    assert {k:result[k] for k in (*MATH_KEYS,'display')}=={k:old['result'][k] for k in (*MATH_KEYS,'display')},(period,gate,old['through'])
                    unit_totals['retainedForecasts']+=1
                else:
                    try:
                        verify_changed_forecast(result,proofs[n],record['candidateContext'])
                    except AssertionError:
                        b.save(out,'failed_forecast.json',dict(period=period,gate=gate,through=old['through'],
                            rows=n,result=result,proof=proofs[n],context=record['candidateContext']))
                        raise
                    unit_totals['independentForecasts']+=1
                assert child.snapshot()==saved
                results.append(dict(rows=n,through=bars[n-1].time,milliseconds=ms,result=result))
                if index%15==0:print(json.dumps(dict(period=period,gate=gate,completed=index,total=len(expected))),flush=True)
            unit_totals['forecasts']+=len(results)
            info=dict(rows=len(bars),forecasts=len(results),maxMs=max(r['milliseconds'] for r in results),
                      calibrationProtected=sum(r['result']['reasonCode']=='CALIBRATION_FAILED' for r in results))
            seal(out,unit,dict(summary=info,totals=dict(unit_totals),results=results,events=events))
            b.save(out,f'forecasts_{period}_{gate}.json',results)
            gates[str(gate)]=info;totals.update(unit_totals)
            print(period,gate,json.dumps(info),flush=True)
        b.save(out,f'events_{period}.json',dict(events=events))
        summary['periods'][period]=gates;b.save(out,'frozen_summary.json',summary)
    assert totals['forecasts']==1215 and totals['prefixRestoreCuts']==45
    assert totals['retainedForecasts']==711 and totals['independentForecasts']==504
    summary['totals']=dict(totals);summary['simulations']=simulations(sources,out)
    return summary


def simulations(sources,out):
    # Independent software observations live in the original immutable case
    # records; same-segment acceptance's four literal expectations remain valid.
    from .same_segment_acceptance import simulations as existing
    return existing(sources,out)


def _readonly_request_session():
    # FastAPI expects a yield dependency, not a contextmanager return value.
    with b.readonly_session() as session:
        yield session


def formal_replay_mode(source,out,sources):
    """Real read-only routing for the sealed API cases, not a software oracle."""
    from fastapi.testclient import TestClient
    from src.app.auth.dependencies import require_quote_access
    from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
    fixture=ROOT/'reports/xxm_top_activation_r2_implementation_20261019/api'
    cases=json.loads((fixture/'result.json').read_text())['results']
    client=TestClient(b.app_for(_readonly_request_session,FORMAL_LAKE_ROOT,require_quote_access))
    records=[]
    result=dict(readonly=True,formalWrites=False,fixtureIsSoftwareOracle=False,periods=list(sources),cases=records)
    original_calendar,original_build=b.fq.future_calendar,b.fq.IndexDetailXxmForecastQueryService.build
    model_start=[None];model_seconds=[0.]
    def calendar(*a,**kw):
        value=original_calendar(*a,**kw);model_start[0]=time.perf_counter();return value
    def build(self,*a,**kw):
        model_start[0]=None
        try:return original_build(self,*a,**kw)
        finally:model_seconds[0]=time.perf_counter()-model_start[0] if model_start[0] else 0.
    b.fq.future_calendar=calendar;b.fq.IndexDetailXxmForecastQueryService.build=build
    try:
        for index,case in enumerate(cases):
            period,through=case['period'],case['through']
            if period not in sources:continue
            expected=json.loads((fixture/f'api_forecast_{index}_{period}.json').read_text())
            b.q._CACHE=b.q.XxmCache()
            started=time.perf_counter();response=b.prediction(client,period,through);elapsed=time.perf_counter()-started
            row=dict(case=index,period=period,through=through,httpStatus=response.status_code,
                     httpSeconds=elapsed,modelEnvelopeSeconds=model_seconds[0],forecastBytes=len(response.content))
            records.append(row);b.save(out,'replay_records.json',result)
            assert response.status_code==200 and elapsed<=4 and model_seconds[0]<=.2,(period,through,'forecast budget/status')
            value=response.json();b.save(out,f'forecast_{index}_{period}.json',value)
            assert len(response.content)<=32768 and value['computedThrough']==through and value['dataStatus']=='READY'
            assert value['detectorSpecHash']==b.MAIN_SPEC.spec_hash and value['forecastVersion']==FORECAST_SPEC.forecast_version
            keys=(*MATH_KEYS,'display','ordinaryState','confirmedAt','confirmedDirection')
            assert {k:value[k] for k in keys}=={k:expected[k] for k in keys},(period,through,'frozen semantics')
            assert (value['rearmContext'] or {}).get('status')==(expected['rearmContext'] or {}).get('status')
            started=time.perf_counter();recognized=b.recognition(client,period,through);elapsed=time.perf_counter()-started
            row.update(recognitionStatus=recognized.status_code,recognitionSeconds=elapsed,recognitionBytes=len(recognized.content),
                       ordinaryState=value['ordinaryState'],forecastStatus=value['status'],
                       hasNextBarOutcomes=value['nextBarOutcomes'] is not None,
                       cacheBytes=sum(size for _,size in b.q._CACHE.entries.values()),cacheEntries=len(b.q._CACHE.entries))
            b.save(out,'replay_records.json',result)
            assert recognized.status_code==200 and elapsed<=4 and len(recognized.content)<=1048576
            signal=recognized.json();assert signal['specHash']==b.MAIN_SPEC.spec_hash
            assert row['cacheBytes']<=64*1024*1024 and row['cacheEntries']<=16
            b.save(out,f'recognition_{index}_{period}.json',signal)
            print(json.dumps(row),flush=True)
    finally:
        b.fq.future_calendar=original_calendar;b.fq.IndexDetailXxmForecastQueryService.build=original_build
    assert len(records)==sum(c['period'] in sources for c in cases)
    result.update(passed=True,fixtureResultSha256=sha(fixture/'result.json'))
    return result


def main():
    # Existing bounded API/formal-readonly-budget command owns argument parsing,
    # source SHA checks, immutable output directories and failure recording.
    b.main()


if __name__=='__main__':main()
