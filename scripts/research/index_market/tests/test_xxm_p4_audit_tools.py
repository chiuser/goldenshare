"""P4 tool expectations are literal contracts; no formal DB/Lake or replay.

The real ASGI -> AnyIO integration below substitutes only a seven-row SQLite
source and auth. Separate tests exercise original cache/shared-load methods.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from scripts.research.index_market import xxm_page_request_audit as audit
from scripts.research.index_market import xxm_forecast_display_audit as display


def group(scenario='mixed_single', period='day', mode='normal', samples=1):
    t=time.monotonic()
    return audit.AuditGroupSpec('1'*32,'forecast' if scenario=='forecast_series' else 'page',scenario,period,mode,None,samples,t,t+50,t+60)


def scope(g, n=1, kind='signals', tab='1', round_=1):
    path={'signals':'xxm-signals','forecast':'xxm-key-point-forecast','kline':'kline','nineTurn':'nine-turn'}[kind]
    params='tsCode=000001.SH'
    if kind not in ('nineTurn',): params+='&period='+g.period
    if g.mode=='debug' and kind in ('signals','forecast'): params+='&debug=1'
    return dict(type='http',path='/api/v1/wealth/market/index-detail/'+path,
                query_string=params.encode(),headers=[(b'x-request-id',f'{g.groupId}:{g.scenario}:{round_}:{tab}:{n}'.encode())])


def row(g, n=1, kind='forecast', **extra):
    c=audit.AuditCollector(g); identity=c.start(scope(g,n,kind))
    value=c.requests[identity]
    value.update(httpStatus=200,bodyBytes=100,httpSeconds=.01,clientSeconds=.02 if kind=='forecast' else None,
                 computedThrough='2023-01-03',sourceInputId='source-a',calendarInputId='calendar-a',
                 prefixRows=1,windowStart='2023-01-03',windowEnd='2023-01-03',publicDigest='public-a',terminal='success')
    value.update(extra);return value


def summary(g, rows):
    return dict(groupId=g.groupId,requests=rows,loads=[],activeRequests=0,cacheBytes=0,cacheEntries=0,cleanupStatus='cleaned')


@pytest.mark.parametrize('module',[audit,display])
@pytest.mark.parametrize('argv',[[],['--periods','day','day'],['--periods','m30'],['--periods','day','--samples','2'],
 ['--periods','day','--as-of','2023-02-30'],['--periods','day','--as-of','20230103'],
 ['--periods','day','--output','x'],['--periods','day','--candidate','x']])
def test_invalid_arguments_fail_before_settings_or_app(monkeypatch,module,argv):
    monkeypatch.setattr(audit,'run',lambda *a:pytest.fail('must not run'))
    monkeypatch.setattr(display,'run',lambda *a:pytest.fail('must not run'))
    with pytest.raises(SystemExit) as error: module.main(argv)
    assert error.value.code==2


@pytest.mark.parametrize('period',audit.PERIODS)
@pytest.mark.parametrize('mode',['normal','debug','both'])
@pytest.mark.parametrize('samples',[1,20])
def test_exact_explicit_task_lists(period,mode,samples):
    args=audit.parse_args(['--periods',period,'--mode',mode,'--samples',str(samples)])
    modes=['normal','debug'] if mode=='both' else [mode]
    expected=['mixed_single','mixed_two'] if samples==1 else ['kline_series'] if period=='day' else ['kline_series','indicator_series']
    assert audit.planned_groups(args,'page')==[(period,m,s) for m in modes for s in expected]
    assert audit.planned_groups(args,'forecast')==[(period,m,'forecast_series') for m in modes]
    for _,m,s in audit.planned_groups(args,'page'):
        g=group(s,period,m,samples)
        assert audit.expected_requests(g)==((4 if period=='day' else 5)*(2 if s=='mixed_two' else 1) if samples==1 else 20)


def test_request_parameters_are_actual_and_duplicate_or_unselected_rejected():
    g=group(mode='debug');c=audit.AuditCollector(g)
    one=c.start(scope(g,kind='kline'));two=c.start(scope(g,2))
    assert c.requests[one]['debug'] is None and c.requests[two]['debug']==1
    with pytest.raises(ValueError,match='Duplicate'):c.start(scope(g,2))
    wrong=scope(g,3);wrong['query_string']=b'tsCode=000001.SH&period=m60&debug=1'
    with pytest.raises(ValueError,match='period'):c.start(wrong)
    wrong=scope(g,3,kind='kline');wrong['query_string']+=b'&debug=1'
    with pytest.raises(ValueError,match='debug'):c.start(wrong)


def test_sample_count_p95_and_independent_timing_limits():
    g=group('kline_series',samples=20)
    rows=[row(g,i+1,'kline',round=i+1,httpSeconds=.7) for i in range(20)]
    assert audit.validate_summary(g,summary(g,rows))['p95HttpSeconds']==.7
    for r in rows[-2:]:r['httpSeconds']=.81
    with pytest.raises(ValueError,match='P95'):audit.validate_summary(g,summary(g,rows))
    with pytest.raises(ValueError,match='count'):audit.validate_summary(g,summary(g,rows[:-1]))
    f=group('forecast_series')
    good=row(f,computeSeconds=.39)
    assert audit.validate_summary(f,summary(f,[good]))['p95HttpSeconds'] is None
    for key,value in [('httpSeconds',4.01),('clientSeconds',5),('computeSeconds',.410),('httpSeconds',None),('terminal','error')]:
        with pytest.raises(ValueError):audit.validate_summary(f,summary(f,[dict(good,**{key:value})]))
    assert audit.validate_summary(f,summary(f,[dict(good,computeSeconds=None)]))


def test_twenty_static_results_are_not_falsely_called_forecast_cache_hits():
    g=group('forecast_series',samples=20)
    rows=[row(g,i+1,round=i+1) for i in range(20)]
    value=audit.validate_summary(g,summary(g,rows))
    assert value['forecastCacheHitCoverage']=='not_verified'
    assert len(value['requests'])==20
    rows[1].update(forecastCacheRead='hit',forecastCacheReadCalls=1)
    assert audit.validate_summary(g,summary(g,rows))['forecastCacheHitCoverage']=='verified'
    rows[1]['terminal']='error'
    with pytest.raises(ValueError):audit.validate_summary(g,summary(g,rows))


def test_only_actual_matching_source_calendar_window_pairs_are_compared():
    a,b=group('forecast_series'),group('forecast_series',mode='debug')
    one,two=row(a),row(b)
    assert audit.compare_modes(summary(a,[one]),summary(b,[two]))[0]['status']=='equal'
    for key in ['sourceInputId','calendarInputId','computedThrough','windowStart','windowEnd','indicatorVersion']:
        changed=dict(two,**{key:'changed'})
        assert audit.compare_modes(summary(a,[one]),summary(b,[changed]))[0]['status']=='not_comparable'
    with pytest.raises(ValueError,match='public'):
        audit.compare_modes(summary(a,[one]),summary(b,[dict(two,publicDigest='different')]))
    # No unrelated future-file signature is in the pairing key.
    assert audit.compare_modes(summary(a,[dict(one,futureSignature='x')]),summary(b,[dict(two,futureSignature='y')]))[0]['status']=='equal'


def test_original_cache_methods_once_and_no_context_passthrough():
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    g=group('forecast_series');c=audit.AuditCollector(g);identity=c.start(scope(g,kind='forecast'))
    original=q._CACHE
    with audit._observe(c) as cache:
        marker=SimpleNamespace(model_copy=lambda **k:'same-result')
        cache.entries[('forecast','key')]=(marker,1)
        token=audit._REQUEST_ID.set(identity)
        try:
            assert cache.get_forecast(('key',),check=lambda:1)=='same-result'
            assert c.requests[identity]['forecastCacheReadCalls']==1
            assert c.requests[identity]['forecastCacheRead']=='hit'
            cache.put_forecast(('new',),marker,1,check=lambda:1)
            assert c.requests[identity]['forecastCacheWriteCalls']==1
            assert c.requests[identity]['forecastCacheWrite']=='stored'
        finally:audit._REQUEST_ID.reset(token)
        cache.get_forecast(('absent',),check=lambda:1) # No context doesn't get attached to previous request.
        assert c.requests[identity]['forecastCacheReadCalls']==1
        c.active=0
    assert q._CACHE is original


@pytest.mark.parametrize('fail',[False,True])
def test_shared_actual_result_or_exception_keeps_one_load_and_cache_lookup(fail):
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    g=group('mixed_two');c=audit.AuditCollector(g)
    ids=[c.start(scope(g,tab=str(i))) for i in (1,2)]
    started,release=threading.Event(),threading.Event();values=[];errors=[];calls=[]
    with audit._observe(c) as cache:
        key=(1,'daily','day','rule',date(2023,1,3))
        marker=object();bad=ValueError('literal')
        def loader():
            calls.append(1);cache.get(('source',));started.set();assert release.wait(2)
            if fail:raise bad
            return marker
        def run(identity):
            token=audit._REQUEST_ID.set(identity)
            try:values.append(cache.loads.load(key,loader,lambda:2))
            except BaseException as error:errors.append(error)
            finally:audit._REQUEST_ID.reset(token)
        threads=[threading.Thread(target=run,args=(i,)) for i in ids]
        threads[0].start();assert started.wait(1);threads[1].start()
        end=time.monotonic()+1
        while time.monotonic()<end:
            with c.lock:
                if c._flights[key]['active']==2:break
            time.sleep(.001)
        release.set()
        for t in threads:t.join(2);assert not t.is_alive()
        assert calls==[1] and len(c.loads)==1
        assert [c.requests[i]['loadIds'] for i in ids]==[['load-1'],['load-1']]
        assert c.loads['load-1']['seriesCacheReadCalls']==1
        assert c.loads['load-1']['seriesCacheRead']=='miss'
        assert not c._flights
        if fail:assert errors==[bad,bad]
        else:assert values==[marker,marker]
        c.active=0


def test_computation_timer_includes_all_original_build_work_and_restores(monkeypatch):
    from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as fq
    class Clock:
        value=100.
        def perf_counter(self):return self.value
    clock=Clock();g=group('forecast_series');c=audit.AuditCollector(g);identity=c.start(scope(g,kind='forecast'))
    def build(self,called=True):
        if called:fq.time.perf_counter() # Exactly the original deadline creation point.
        clock.value+=.390
        return b'original'
    monkeypatch.setattr(fq,'time',clock);monkeypatch.setattr(fq.IndexDetailXxmForecastQueryService,'build',build)
    with audit._observe(c):
        token=audit._REQUEST_ID.set(identity)
        try:
            assert fq.IndexDetailXxmForecastQueryService().build() == b'original'
            assert c.requests[identity]['computeSeconds']==pytest.approx(.390)
            fq.IndexDetailXxmForecastQueryService().build(called=False)
            assert c.requests[identity]['computeSeconds'] is None
        finally:audit._REQUEST_ID.reset(token)
        c.active=0
    assert fq.time is clock and fq.IndexDetailXxmForecastQueryService.build is build


def test_real_asgi_to_sync_thread_preserves_each_request_identity():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    g=group('mixed_two');c=audit.AuditCollector(g);app=FastAPI()
    app.add_middleware(audit._RequestMiddleware,collector=c,stop=threading.Event())
    barrier=threading.Barrier(2)
    @app.get('/api/v1/wealth/market/index-detail/xxm-signals')
    def endpoint():
        identity=audit._REQUEST_ID.get();assert identity in c.requests;barrier.wait(2)
        return {'identity':identity}
    with TestClient(app) as client:
        values=[]
        def request(tab):
            identity=f'{g.groupId}:{g.scenario}:1:{tab}:1'
            response=client.get('/api/v1/wealth/market/index-detail/xxm-signals?tsCode=000001.SH&period=day',headers={'X-Request-ID':identity})
            values.append((identity,response.json()['identity'],response.headers['x-request-id']))
        threads=[threading.Thread(target=request,args=(i,)) for i in (1,2)]
        for t in threads:t.start()
        for t in threads:t.join(3);assert not t.is_alive()
        assert len(values)==2 and all(a==b==h for a,b,h in values)
        assert c.active==0 and len(c.requests)==2
        assert all(r['terminal']=='success' and r['bodyBytes']>0 for r in c.requests.values())


def test_worker_input_protocol_and_no_extra_scenarios():
    g=group('forecast_series');assert audit._group_from_json(asdict(g))==g
    for update in [{'samples':True},{'workDeadline':g.startedAt+51},{'scenario':'all'},{'period':'m5'},{'tool':'other'}]:
        with pytest.raises((ValueError,SystemExit)):audit._group_from_json({**asdict(g),**update})


@pytest.mark.parametrize('body',[
 "sys.stdout.write('{broken\\n');sys.stdout.flush()",
 "sys.stdout.write('partial');sys.stdout.flush()",
 "sys.stdout.write('x'*1100000);sys.stdout.flush()",
 "sys.stderr.write('x'*1100000);sys.stderr.flush()",
])
def test_supervisor_rejects_bad_or_overlimit_communication_with_no_app(body):
    g=group('forecast_series')
    with pytest.raises(RuntimeError):audit._supervise([sys.executable,'-c',f'import sys;sys.stdin.read();{body}'],{'group':asdict(g)},g)


def test_supervisor_terminates_real_stuck_thread_and_inherited_node_group(monkeypatch):
    if shutil_node:=__import__('shutil').which('node'):
        # Fast virtual supervision clock, real child/thread/Node and real signals.
        # The child installs its handler before the parent reaches virtual50s.
        original=time.monotonic;start=original()
        monkeypatch.setattr(audit,'time',SimpleNamespace(monotonic=lambda:start+(original()-start)*20,sleep=time.sleep))
        children=[];popen=subprocess.Popen
        def spawn(*args,**kwargs):
            child=popen(*args,**kwargs);children.append(child);return child
        monkeypatch.setattr(audit.subprocess,'Popen',spawn)
        g=group('forecast_series')
        code="""import sys,json,os,threading,subprocess,signal,time,socket
import uvicorn
from fastapi import FastAPI
raw=json.loads(sys.stdin.read());g=raw['group']
signal.signal(signal.SIGINT,signal.SIG_IGN)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
app=FastAPI()
@app.get('/stuck')
def stuck():threading.Event().wait(300)
sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(4)
server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,lifespan='off'))
threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True).start()
while not server.started:time.sleep(.01)
subprocess.Popen([NODE,'-e',f"fetch('http://127.0.0.1:{sock.getsockname()[1]}/stuck').catch(()=>{{}})"])
print(json.dumps(dict(type='started',groupId=g['groupId'],pid=os.getpid(),processGroupId=os.getpgrp())),flush=True)
time.sleep(300)
""".replace('NODE',repr(shutil_node))
        with pytest.raises(RuntimeError):audit._supervise([sys.executable,'-c',code],{'group':asdict(g)},g)
        assert len(children)==1 and children[0].returncode is not None
        # Confirm the actual test-owned group disappeared, not just that an
        # exception was raised. Allow the kernel's short orphan-reap interval.
        until=original()+.2
        while audit._group_alive(children[0].pid) and original()<until:time.sleep(.01)
        assert not audit._group_alive(children[0].pid)
        assert original()-start<5


def test_permission_to_query_process_group_does_not_prove_absence(monkeypatch):
    def refused(*args):raise PermissionError('not observable')
    monkeypatch.setattr(audit.os,'killpg',refused)
    assert audit._group_alive(12345) is True


def _node_fixture_prelude(g, *, bad=None):
    """Only transport is replaced; production TS clients/decoders/scheduler run.

    Independent P3 literal DTO fixtures supply API fields; this is not a formal
    source or HTTP performance proof. Assertions below independently fix counts,
    chart dates, limit and absence of debug on the ordinary data requests.
    """
    root=Path(__file__).resolve().parents[4]
    return f'''
import {{createRequire}} from 'node:module';
const require=createRequire({json.dumps(str(root/'wealth/package.json'))});
const {{build}}=require('esbuild');
const prefix={json.dumps(str(root/'wealth/src/features/index-detail')+'/')};
const code=`export {{xxmFixture,xxmDebugFixture}} from ${{JSON.stringify(prefix+'xxm/xxmFixtures.test-support.ts')}}; export {{forecastFixture,forecastDebugFixture}} from ${{JSON.stringify(prefix+'xxm-forecast/forecastFixtures.test-support.ts')}};`;
const compiled=await build({{stdin:{{contents:code,resolveDir:{json.dumps(str(root))}}},bundle:true,write:false,platform:'node',format:'esm'}});
const facts=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64'));
const g={json.dumps(asdict(g))},bad={json.dumps(bad)},rows=[],calls=[];
const base='http://fixture.invalid';
function result(value,headers={{}},status=200){{return new Response(JSON.stringify(value),{{status,headers}});}}
globalThis.fetch=async(input,options={{}})=>{{
 const url=new URL(String(input),base),endpoint=url.pathname.split('/').at(-1);
 calls.push(endpoint);
 if(endpoint==='context')return result({{groupId:g.groupId,businessDate:'2023-01-13'}});
 if(endpoint==='reset')return result({{groupId:g.groupId,ok:true}});
 if(endpoint==='metrics')return result({{groupId:g.groupId,requests:rows,loads:[],activeRequests:0,cacheBytes:0,cacheEntries:0,cleanupStatus:'pending',observedCalls:calls}});
 const requestId=new Headers(options.headers).get('X-Request-ID');
 const debug=url.searchParams.get('debug')==='1';
 const minute=g.period!=='day',freq=minute?Number(g.period.slice(1)):null;
 function minuteResponse(response){{
  function dates(value){{
   if(typeof value==='string'&&/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(value))return value+'T15:00:00+08:00';
   if(Array.isArray(value))return value.map(dates);
   if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,dates(v)]));
   return value;
  }}
  const value=dates(response);value.period=g.period;value.source.kind='minute_gold';value.source.indicatorVersion=1;return value;
 }}
 let body,kind;
 if(endpoint==='minutes'||endpoint==='minute-indicators'){{
  if(url.searchParams.has('debug')||url.searchParams.get('freq')!==String(freq)||url.searchParams.get('limit')!=='500'||url.searchParams.get('endDate')!=='2023-01-13')throw new Error('wrong minute params');
  const point=(g.mode==='debug'?facts.xxmDebugFixture():facts.xxmFixture()).response.points[0];
  const item={{tsCode:'000001.SH',freq,tradeDate:'2023-01-12',tradeTime:'2023-01-12T15:00:00+08:00',open:point.close,high:point.close+1,low:point.close-1,close:point.close,vol:100,amount:1000,exchange:'SSE'}};
  body={{tsCode:'000001.SH',freq,meta:{{count:1,limit:500}},dataStatus:{{status:'READY'}}}};
  if(endpoint==='minutes'){{body.bars=[item];kind='kline';}}
  else {{
   await new Promise(resolve=>setTimeout(resolve,15));
   body.items=[{{...item,tradeTime:bad==='minute-mismatch'?'2023-01-12T11:30:00+08:00':item.tradeTime,macdDif:point.dif,macdDea:point.dea,macd:point.hist,kdjK:1,kdjD:2,kdjJ:3,paramsKey:'MACD:12,26,9',indicatorVersion:1}}];kind='indicators';
  }}
 }}else if(endpoint==='kline'){{
  if(url.searchParams.has('debug')||url.searchParams.get('limit')!=='1000'||url.searchParams.get('endDate')!=='2023-01-13')throw new Error('wrong chart params');
  await new Promise(resolve=>setTimeout(resolve,10));
  const p=(g.mode==='debug'?facts.xxmDebugFixture():facts.xxmFixture()).response.points[0];
  body={{bars:bad==='empty'?[]:[{{tradeDate:p.time,close:bad==='bad-number'?null:p.close,factors:{{macd:{{dif:p.dif,dea:p.dea,macd:p.hist}}}}}}]}};kind='kline';
 }}else if((endpoint==='nine-turn'||endpoint==='minute-nine-turn')){{
  if(url.searchParams.has('debug')||url.searchParams.get('limit')!==(minute?'500':'1000')||url.searchParams.get('endDate')!=='2023-01-13')throw new Error('wrong nine params');
  body={{markers:[]}};kind='nineTurn';
 }}else if(endpoint==='xxm-key-point-forecast'){{
  if(url.searchParams.has('asOf'))throw new Error('must keep latest');
  body=debug?facts.forecastDebugFixture(g.period):facts.forecastFixture(g.period);kind='forecast';
 }}else if((endpoint==='xxm-signals'||endpoint==='minute-xxm-signals')){{
  if(!(minute?calls.includes('minutes')&&calls.includes('minute-indicators'):calls.includes('kline'))||url.searchParams.get('startDate')!=='2023-01-12'||url.searchParams.get('endDate')!=='2023-01-12'||url.searchParams.get('limit')!=='1')throw new Error('wrong actual window');
  body=(debug?facts.xxmDebugFixture():facts.xxmFixture()).response;if(minute)body=minuteResponse(body);kind='signals';
  if(bad==='contract')body={{...body,specHash:'old'}};
 }}else throw new Error('unexpected endpoint');
 const bytes=Buffer.byteLength(JSON.stringify(body));
 rows.push({{requestId,endpointKind:kind,httpStatus:200,bodyBytes:bytes,terminal:'success'}});
 return result(body,{{'X-Request-ID':requestId}});
}};
'''


@pytest.mark.parametrize('mode',['normal','debug'])
@pytest.mark.parametrize('scenario',['mixed_single','mixed_two','forecast_series','kline_series'])
def test_actual_node_clients_selected_counts_dates_and_debug(mode,scenario):
    from base64 import b64encode
    g=group(scenario,mode=mode,samples=20 if scenario in ('forecast_series','kline_series') else 1)
    prelude='data:text/javascript;base64,'+b64encode(_node_fixture_prelude(g).encode()).decode()
    command=[__import__('shutil').which('node'),'--import',prelude,str(Path(audit.__file__).with_suffix('.mjs')),
             'http://fixture.invalid',json.dumps(asdict(g))]
    result=subprocess.run(command,capture_output=True,timeout=8)
    assert result.returncode==0,result.stderr.decode()
    value=json.loads(result.stdout)
    assert len(value['requests'])==audit.expected_requests(g)
    assert len({r['requestId'] for r in value['requests']})==len(value['requests'])
    assert value['privateRequests']==3
    expected={'forecast_series':{'xxm-key-point-forecast':20},'kline_series':{'kline':20},
              'mixed_single':{'xxm-key-point-forecast':1,'kline':1,'nine-turn':1,'xxm-signals':1},
              'mixed_two':{'xxm-key-point-forecast':2,'kline':2,'nine-turn':2,'xxm-signals':2}}[scenario]
    from collections import Counter
    assert Counter(value['observedCalls'])==Counter(expected)|Counter({'context':1,'reset':1,'metrics':1})
    for r in value['requests']:
        assert r['httpSeconds'] is not None and r['terminal']=='success'
        assert (r['clientSeconds'] is not None)==(r['endpointKind'] in ('signals','forecast'))


@pytest.mark.parametrize('bad',['empty','bad-number','contract'])
def test_actual_node_clients_reject_empty_bad_source_and_old_contract(bad):
    from base64 import b64encode
    g=group();prelude='data:text/javascript;base64,'+b64encode(_node_fixture_prelude(g,bad=bad).encode()).decode()
    result=subprocess.run([__import__('shutil').which('node'),'--import',prelude,str(Path(audit.__file__).with_suffix('.mjs')),
                           'http://fixture.invalid',json.dumps(asdict(g))],capture_output=True,timeout=8)
    assert result.returncode!=0 and not result.stdout
    error=json.loads(result.stderr);assert error['stage']=='client'
    assert error['sentRequests']<=4


@pytest.mark.parametrize('period',['m60','m90','m120'])
@pytest.mark.parametrize('mode',['normal','debug'])
@pytest.mark.parametrize('scenario',['mixed_single','mixed_two','kline_series','indicator_series'])
def test_actual_minute_node_clients_wait_for_paired_indicators(period,mode,scenario):
    from base64 import b64encode
    g=group(scenario,period=period,mode=mode,samples=20 if scenario.endswith('_series') else 1)
    prelude='data:text/javascript;base64,'+b64encode(_node_fixture_prelude(g).encode()).decode()
    result=subprocess.run([__import__('shutil').which('node'),'--import',prelude,str(Path(audit.__file__).with_suffix('.mjs')),
                           'http://fixture.invalid',json.dumps(asdict(g))],capture_output=True,timeout=8)
    assert result.returncode==0,result.stderr.decode()
    value=json.loads(result.stdout)
    assert len(value['requests'])==audit.expected_requests(g)
    assert value['privateRequests']==3
    if scenario.startswith('mixed'):
        assert sum(r['endpointKind']=='signals' for r in value['requests'])==(2 if scenario=='mixed_two' else 1)
    else: assert {r['endpointKind'] for r in value['requests']}==({'indicators'} if scenario=='indicator_series' else {'kline'})


def test_actual_minute_node_clients_reject_mismatched_pair_before_signals():
    from base64 import b64encode
    g=group(period='m60');prelude='data:text/javascript;base64,'+b64encode(_node_fixture_prelude(g,bad='minute-mismatch').encode()).decode()
    result=subprocess.run([__import__('shutil').which('node'),'--import',prelude,str(Path(audit.__file__).with_suffix('.mjs')),
                           'http://fixture.invalid',json.dumps(asdict(g))],capture_output=True,timeout=8)
    assert result.returncode!=0 and not result.stdout
    assert json.loads(result.stderr)['sentRequests']<=4 # No fifth (signals) request.


def test_supervisor_accepts_one_valid_terminal_only_after_clean_exit():
    g=group('forecast_series');value=summary(g,[row(g)])
    code="""import json,os,sys
p=json.loads(sys.stdin.read());g=p['group'];s=p['summary']
print(json.dumps(dict(type='started',groupId=g['groupId'],pid=os.getpid(),processGroupId=os.getpgrp())),flush=True)
print(json.dumps(dict(type='result',groupId=g['groupId'],summary=s)),flush=True)
"""
    result=audit._supervise([sys.executable,'-c',code],{'group':asdict(g),'summary':value},g)
    assert result['cleanupStatus']=='cleaned' and result['requests'][0]['terminal']=='success'


@pytest.mark.parametrize('change',['wrong-pid','wrong-group','duplicate-start','double-result','no-start','partial-after-result'])
def test_supervisor_rejects_wrong_order_or_identity_even_with_valid_result(change):
    g=group('forecast_series');value=summary(g,[row(g)])
    code="""import json,os,sys
p=json.loads(sys.stdin.read());g=p['group'];s=p['summary'];c=p['change']
a=dict(type='started',groupId=g['groupId'],pid=os.getpid(),processGroupId=os.getpgrp())
b=dict(type='result',groupId=g['groupId'],summary=s)
if c=='wrong-pid': a['pid']+=1
if c=='wrong-group': b['groupId']='other'
if c!='no-start': print(json.dumps(a),flush=True)
if c=='duplicate-start': print(json.dumps(a),flush=True)
print(json.dumps(b),flush=True)
if c=='double-result': print(json.dumps(b),flush=True)
if c=='partial-after-result': sys.stdout.write('unfinished');sys.stdout.flush()
"""
    with pytest.raises(RuntimeError):audit._supervise([sys.executable,'-c',code],{'group':asdict(g),'summary':value,'change':change},g)


def test_failed_client_keeps_measured_time_and_does_not_call_http200_success():
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    g=group('forecast_series');c=audit.AuditCollector(g)
    identity=c.start(scope(g,kind='forecast'))
    c.requests[identity].update(httpStatus=200,bodyBytes=125,terminal='success')
    c.active=0
    client=dict(requestId=identity,httpSeconds=.012,clientSeconds=None,terminal='error',httpStatus=200,
                bodyBytes=125,computedThrough=None,responseRows=None,windowStart=None,windowEnd=None)
    audit._validate_client_records(g,[client],1)
    error=audit.AuditGroupFailure('client',error_type='XxmContractError',client_records=[client])
    value=audit._failure_summary(c,q.XxmCache(),error,None)
    assert value['cleanupStatus']=='failed' and 'p95HttpSeconds' not in value
    assert value['requests'][0]['terminal']=='error'
    assert value['requests'][0]['httpSeconds']==.012 and value['requests'][0]['clientSeconds'] is None
    audit._validate_failure(g,dict(stage='client',errorType='XxmContractError',errorCode=None,cleanupStatus='failed',summary=value))
    # A final budget failure after Node returned must retain its known times too.
    returned=summary(g,[dict(c.requests[identity],httpSeconds=4.01,clientSeconds=4.02)])
    value=audit._failure_summary(c,q.XxmCache(),ValueError('budget'),returned)
    assert value['requests'][0]['httpSeconds']==4.01 and value['requests'][0]['clientSeconds']==4.02


@pytest.mark.parametrize('change',['extra-field','wrong-id','nan','duplicate'])
def test_failed_client_records_reject_unknown_fields_and_untrusted_values(change):
    g=group('forecast_series');identity=f'{g.groupId}:forecast_series:1:1:1'
    value=dict(requestId=identity,httpSeconds=.01,clientSeconds=None,terminal='error',httpStatus=200,
               bodyBytes=125,computedThrough=None,responseRows=None,windowStart=None,windowEnd=None)
    records=[value]
    if change=='extra-field':value['body']='not allowed'
    if change=='wrong-id':value['requestId']='other-group'
    if change=='nan':value['httpSeconds']=float('nan')
    if change=='duplicate':records.append(dict(value))
    with pytest.raises(ValueError):audit._validate_client_records(g,records,len(records))


@pytest.mark.parametrize('broken',[False,True])
def test_supervisor_reports_failed_records_only_with_valid_communication(broken):
    g=group('forecast_series');value=summary(g,[row(g,terminal='error',httpSeconds=.02)])
    value['cleanupStatus']='failed'
    code="""import json,os,sys
p=json.loads(sys.stdin.read());g=p['group']
print(json.dumps(dict(type='started',groupId=g['groupId'],pid=os.getpid(),processGroupId=os.getpgrp())),flush=True)
print(json.dumps(dict(type='failed',groupId=g['groupId'],stage='client',errorType='XxmContractError',errorCode=None,cleanupStatus='failed',summary=p['summary'])),flush=True)
if p['broken']:sys.stdout.write('partial');sys.stdout.flush()
sys.exit(1)
"""
    with pytest.raises(RuntimeError) as caught:
        audit._supervise([sys.executable,'-c',code],{'group':asdict(g),'summary':value,'broken':broken},g)
    if broken:assert not isinstance(caught.value,audit.AuditGroupFailure)
    else:
        assert isinstance(caught.value,audit.AuditGroupFailure)
        assert caught.value.summary['requests'][0]['httpSeconds']==.02
        assert 'p95HttpSeconds' not in caught.value.summary


def test_failed_group_stops_remaining_selected_groups(monkeypatch,capsys):
    from src.foundation.config import settings as settings_module
    monkeypatch.setattr(settings_module,'get_settings',lambda:object())
    calls=[]
    def fail(g,settings):
        calls.append((g.period,g.mode,g.scenario))
        raise audit.AuditGroupFailure('client',error_type='XxmContractError')
    monkeypatch.setattr(audit,'run_audit_group',fail)
    with pytest.raises(SystemExit) as caught:
        audit.run(audit.parse_args(['--periods','day','m60','--mode','both']),'page')
    assert caught.value.code==1 and calls==[('day','normal','mixed_single')]
    value=json.loads(capsys.readouterr().out)
    assert value['status']=='failed' and value['summary'] is None


def test_actual_minute_pair_child_threads_keep_one_load_without_extra_reads(monkeypatch):
    from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader as Reader
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    barrier=threading.Barrier(2);calls=[]
    def literal_read(self,request,**kwargs):
        assert audit._LOAD_ID.get() is None # Standard executor really has no copied context.
        calls.append(kwargs['dataset']);barrier.wait(2)
        return kwargs['dataset']
    monkeypatch.setattr(Reader,'_read_complete_history',literal_read)
    g=group('forecast_series',period='m60');c=audit.AuditCollector(g)
    identity=c.start(scope(g,kind='forecast'));reader=object.__new__(Reader)
    request=SimpleNamespace(freq=60,start_date=date(2023,1,3),end_date=date(2023,1,4))
    with audit._observe(c) as cache:
        token=audit._REQUEST_ID.set(identity)
        try:
            value=cache.loads.load(('source','object','m60'),lambda:reader.read_complete_history_pair(request,timeout_seconds=2),lambda:2)
            assert value==('bars','indicators') and sorted(calls)==['bars','indicators']
            assert c.requests[identity]['loadIds']==['load-1']
            load=c.loads['load-1']
            assert (load['pairCalls'],load['barsCalls'],load['indicatorCalls'])==(1,1,1)
            assert c._pair_owners=={}
        finally:audit._REQUEST_ID.reset(token);c.active=0


def test_real_node_failure_protocol_preserves_client_error_records(monkeypatch):
    from base64 import b64encode
    g=group();prelude='data:text/javascript;base64,'+b64encode(_node_fixture_prelude(g,bad='contract').encode()).decode()
    monkeypatch.setenv('NODE_OPTIONS','--import='+prelude)
    with pytest.raises(audit.AuditGroupFailure) as caught:
        audit._run_node(audit.AuditApp(None,'http://fixture.invalid',None,threading.Event()),g)
    assert caught.value.stage=='client'
    records=caught.value.client_records
    assert len(records)==4
    errors=[r for r in records if r['terminal']=='error']
    assert errors and all(r['httpStatus']==200 and r['httpSeconds'] is not None for r in errors)
    assert all(set(r)==audit._CLIENT_FIELDS for r in records)


def test_partial_observation_setup_restores_already_registered_patches(monkeypatch):
    from unittest.mock import patch
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    cache,build=q._CACHE,q.IndexDetailXxmQueryService.build
    def fail(target,name,*args,**kwargs):
        if name=='load_entry':raise RuntimeError('injected setup failure')
        return patch.object(target,name,*args,**kwargs)
    monkeypatch.setattr(audit,'patch',SimpleNamespace(object=fail))
    with pytest.raises(RuntimeError,match='setup failure'):
        with audit._observe(audit.AuditCollector(group())):pytest.fail('must not yield')
    assert q._CACHE is cache and q.IndexDetailXxmQueryService.build is build
