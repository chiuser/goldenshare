"""LLD13.30: real API/worker/client/PostgreSQL/Quote chain on isolated resources.

Only external platform responses, authentication and unrelated app lifespan are
replaced. Fault injection acts after a real business commit or in observations;
it never fabricates a business result. Price literals come from doc365's captured
21-field sample. Code/date variants are deliberate execution fixtures, not market
data assertions. The existing task-owned PG fixture never uses configured Prod.
"""

from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
import threading
import time
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.models.app_user import AppUser
from src.foundation.config.settings import get_settings
from src.foundation.datasets.stock_period_adj_contracts import SOURCE_FIELDS, READINESS_FIELDS
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor as Factor
from src.foundation.models.core_serving.security_serving import Security
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.runtime.worker import OperationsWorker
from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
from src.ops.services.operations_task_run_reconciliation_service import (
    OperationsTaskRunReconciliationService, RUNNING_STALE_FOR_MINUTES,
)
from src.ops.services.stock_period_adj_probe_service import CURRENT_CONDITION, HISTORY_CONDITION
from test_stock_period_adj_p2_pg import pg as period_pg, Basic, Raw, Serving, Delivery, TaskRun, TaskRunNode, ProbeRule, ProbeRunLog
from test_stock_period_adj_contracts import literal_rows


EXECUTION_DAY = date(2026, 11, 16)
CODES = ('000001.SZ', '600000.SH')


def source_row(*, code='000001.SZ', freq='month', stamp=date(2020,2,29), end=EXECUTION_DAY, qfq=None):
    row={**literal_rows()[0], 'ts_code':code, 'freq':freq, 'trade_date':stamp, 'end_date':end}
    if qfq is not None: row['close_qfq']=Decimal(qfq)
    return row


def _wire(fields, rows):
    def cell(value):
        if isinstance(value,date): return json.dumps(value.strftime('%Y%m%d'))
        if isinstance(value,Decimal): return str(value)
        return json.dumps(value)
    return ('{"code":0,"msg":"","data":{"fields":'+json.dumps(fields)+',"items":['+
        ','.join('['+','.join(cell(row[field]) for field in fields)+']' for row in rows)+']}}').encode()


@pytest.fixture
def pg(period_pg):
    with period_pg.begin() as connection:
        connection.execute(text('CREATE SCHEMA app'))
        for model in (AppUser,Security,ConfigRevision,Factor): model.__table__.create(connection)
    with Session(period_pg) as session:
        session.add(AppUser(id=1,username='period-p4-test',password_hash='authentication-is-overridden',is_admin=True))
        session.add(Basic(ts_code=CODES[1],curr_type='CNY',exchange='SSE',list_status='L',list_date=date(2000,1,1)))
        session.add_all(Security(ts_code=code,symbol=code[:6],name='隔离股票'+code,curr_type='CNY',list_status='L') for code in CODES)
        session.commit()
    return period_pg


@pytest.fixture
def platform(monkeypatch,tmp_path):
    # get_settings gives the selected file priority over environment variables.
    # Never load the repository's production-connected .env in this acceptance.
    env_file=tmp_path/'isolated.env'; env_file.write_text('')
    monkeypatch.setenv('GOLDENSHARE_ENV_FILE',str(env_file))
    state={'requests':[], 'errors':[], 'reply':lambda request:[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if request.get('token')!='period-p4-test' or request.get('api_name')!='stk_week_month_adj':
                state['errors'].append('unexpected test credential or API'); self.send_response(400); self.end_headers(); return
            recorded={key:value for key,value in request.items() if key!='token'}
            state['requests'].append(recorded)
            response=state['reply'](recorded)
            if isinstance(response,bytes): data=response
            else: data=_wire(request['fields'].split(','),response)
            self.send_response(200); self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setenv('TUSHARE_BASE_URL',f'http://127.0.0.1:{server.server_port}')
    monkeypatch.setenv('TUSHARE_TOKEN','period-p4-test')
    get_settings.cache_clear()
    assert get_settings().tushare_base_url==f'http://127.0.0.1:{server.server_port}'
    assert get_settings().tushare_token=='period-p4-test'
    try: yield state
    finally:
        server.shutdown(); server.server_close(); thread.join(); get_settings.cache_clear()
    assert not state['errors']


@pytest.fixture
def api(pg,platform,monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('DATABASE_URL',pg.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    assert get_settings().database_url==pg.url.render_as_string(hide_password=False)
    from src.app.web.app import app
    from src.app.dependencies import get_db_session
    from src.app.auth.dependencies import require_admin, require_quote_access
    import src.foundation.ingestion.stock_period_adj_inputs as inputs
    import src.foundation.ingestion.stock_period_adj_execution as execution
    monkeypatch.setattr(inputs,'today',lambda:EXECUTION_DAY)
    monkeypatch.setattr(execution,'today',lambda:EXECUTION_DAY)
    @asynccontextmanager
    async def no_background(_app): yield
    def database():
        with Session(pg) as session: yield session
    user=AuthenticatedUser(id=1,username='period-p4-test',display_name='隔离运营',email=None,
        account_state='active',is_admin=True,is_active=True)
    previous=dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db_session:database,require_admin:lambda:user,require_quote_access:lambda:user})
    monkeypatch.setattr(app.router,'lifespan_context',no_background)
    try:
        with TestClient(app) as client: yield client
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous); get_settings.cache_clear()


def submit(api, *, freq='month', kind='stock_history', codes=None, keys=None, day=None, period=None, resume=None):
    if resume is not None: body={'resume_from_task_run_id':resume}
    else:
        intent={'kind':kind}
        if codes is not None: intent['stock_codes']=codes
        if keys is not None: intent['remove_keys']=keys
        time_input={'mode':'point','business_date':day.isoformat()} if day else (
            {'mode':'point','trade_date':period.isoformat()} if period else {'mode':'none'})
        body={'time_input':time_input,'filters':{},'maintenance_intent':intent}
    response=api.post(f'/api/v1/ops/manual-actions/stk_period_bar_adj_{freq}.maintain/task-runs',json=body)
    assert response.status_code==200,response.text
    return response.json()['run']['id']


def run(pg, task_id):
    with Session(pg) as session:
        result=OperationsWorker().run_task_run(session,task_id)
        return result.status


def view(api, task_id):
    response=api.get(f'/api/v1/ops/task-runs/{task_id}/view')
    assert response.status_code==200,response.text
    return response.json()


def quote(api, *, code=CODES[0],freq='month',adjustment='forward',limit=300,end=None):
    params={'ts_code':code,'security_type':'stock','period':freq,'adjustment':adjustment,'limit':limit}
    if end: params['end_date']=end
    response=api.get('/api/v1/quote/detail/kline',params=params)
    assert response.status_code==200,response.text
    return response.json()


def removal(code=CODES[0],stamp='2020-02-29',freq='month'):
    return {'ts_code':code,'trade_date':stamp,'freq':freq}


def history_reply(request):
    params=request['params']; code=params['ts_code']; freq=params['freq']
    return [{**row,'ts_code':code,'freq':freq} for row in literal_rows()]


@contextmanager
def after_unit_commit(callback):
    """Observe the real unit INSERT/COMMIT, without replacing its implementation."""
    def flushing(session, *_):
        for row in session.new:
            if isinstance(row,Delivery) and row.record_kind=='unit':
                session.info['period_p4_committed_unit']=row.unit_id
    def committed(session):
        unit=session.info.pop('period_p4_committed_unit',None)
        if unit is not None: callback(unit)
    event.listen(Session,'before_flush',flushing)
    event.listen(Session,'after_commit',committed)
    try: yield
    finally:
        event.remove(Session,'before_flush',flushing)
        event.remove(Session,'after_commit',committed)


def exit_worker_after_commit(url,task_id):
    # A real child process exits after COMMIT and before the next observation.
    import src.foundation.ingestion.stock_period_adj_inputs as inputs
    import src.foundation.ingestion.stock_period_adj_execution as execution
    inputs.today=lambda:EXECUTION_DAY
    execution.today=lambda:EXECUTION_DAY
    get_settings.cache_clear()
    engine=create_engine(url)
    with after_unit_commit(lambda unit:os._exit(1)):
        run(engine,task_id)


def test_cancel_after_real_commit_resume_remaining_and_replay(pg,api,platform,record_property):
    platform['reply']=history_reply
    task=submit(api,codes=list(CODES)); committed=[]
    def cancel(unit):
        committed.append(unit)
        response=api.post(f'/api/v1/ops/task-runs/{task}/cancel')
        assert response.status_code==200,response.text
    started=time.perf_counter()
    with after_unit_commit(cancel): assert run(pg,task)=='canceled'
    record_property('cancel_execution_seconds',time.perf_counter()-started)
    stopped=view(api,task)
    assert (stopped['progress']['unit_done'],stopped['progress']['unit_total'])==(1,2)
    assert stopped['nodes'][0]['status']=='canceled' and len(committed)==1
    assert [req['params']['ts_code'] for req in platform['requests']]==[CODES[0]]
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==1
        assert session.scalar(select(func.count()).select_from(Raw))==2
        assert session.scalar(select(func.count()).select_from(Serving))==1
    resumed=submit(api,resume=task); started=time.perf_counter()
    assert run(pg,resumed)=='success'
    record_property('resume_seconds',time.perf_counter()-started)
    assert [req['params']['ts_code'] for req in platform['requests']]==list(CODES)
    complete=view(api,resumed)
    assert (complete['progress']['unit_done'],complete['progress']['unit_total'])==(2,2)
    assert complete['nodes'][0]['status']=='success'
    replay=submit(api,resume=resumed); started=time.perf_counter()
    assert run(pg,replay)=='success'
    record_property('replay_seconds',time.perf_counter()-started)
    assert len(platform['requests'])==2
    started=time.perf_counter()
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==2
        assert session.scalar(select(func.count()).select_from(Raw))==4
        assert session.scalar(select(func.count()).select_from(Serving))==2
    assert all(quote(api,code=code)['meta']['bar_count']==1 for code in CODES)
    record_property('final_readback_seconds',time.perf_counter()-started)


def test_process_exit_reconciles_node_and_resume_uses_committed_business_fact(pg,api,platform):
    platform['reply']=history_reply
    task=submit(api,codes=list(CODES))
    process=multiprocessing.get_context('spawn').Process(target=exit_worker_after_commit,
        args=(pg.url.render_as_string(hide_password=False),task))
    process.start(); process.join()
    assert process.exitcode==1
    with Session(pg) as session:
        original=session.get(TaskRun,task); node=session.get(TaskRunNode,original.current_node_id)
        assert original.status==node.status=='running'
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==1
        assert session.scalar(select(func.count()).select_from(Raw))==2
        latest=max(value for value in (original.updated_at,node.updated_at) if value is not None)
        OperationsTaskRunReconciliationService().reconcile_stale_task_runs(session,
            now=latest+timedelta(minutes=RUNNING_STALE_FOR_MINUTES,microseconds=1))
    failed=view(api,task)
    assert failed['run']['status']==failed['nodes'][0]['status']=='failed'
    resumed=submit(api,resume=task); assert run(pg,resumed)=='success'
    assert [req['params']['ts_code'] for req in platform['requests']]==list(CODES)
    assert view(api,resumed)['progress']['unit_done']==2
    assert all(quote(api,code=code)['meta']['bar_count']==1 for code in CODES)


def test_schedule_api_binds_dual_probes_current_then_shared_daily_history(pg,api,platform):
    def reply(request):
        params=request['params']; freq=params['freq']
        if 'ts_code' in params: return history_reply(request)
        stamp=date(2026,11,20) if freq=='week' else date(2026,11,30)
        return [source_row(code=code,freq=freq,stamp=stamp) for code in CODES]
    platform['reply']=reply
    for freq in ('week','month'):
        response=api.post('/api/v1/ops/schedules',json={'target_type':'dataset_action',
            'target_key':f'stk_period_bar_adj_{freq}.maintain','display_name':'隔离'+freq,
            'schedule_type':'cron','trigger_mode':'probe','timezone':'Asia/Shanghai',
            'params_json':{},'probe_config':{'condition_kind':CURRENT_CONDITION}})
        assert response.status_code==200,response.text
    current=datetime(2026,11,16,20,tzinfo=ZoneInfo('Asia/Shanghai'))
    def tick():
        with Session(pg) as session:
            # Advance the fixture clock without waiting a real probe interval.
            for rule in session.scalars(select(ProbeRule)): rule.last_probed_at=None
            session.commit()
            tasks,counts=ProbeRuntimeService().run_once(session,now=current)
            return [task.id for task in tasks],counts
    with Session(pg) as session:
        rules=list(session.scalars(select(ProbeRule)))
        assert len(rules)==4
        assert {r.probe_condition_json['type'] for r in rules}=={CURRENT_CONDITION,HISTORY_CONDITION}
        assert all((r.window_start,r.window_end,r.probe_interval_seconds)==('20:00','00:00',60) for r in rules)
    tasks,counts=tick(); assert len(tasks)==counts.created_task_runs==2
    assert all(req['fields'].split(',')==list(READINESS_FIELDS) for req in platform['requests'])
    assert run(pg,tasks[0])=='success'
    assert tick()[0]==[] # Other frequency has not completed yet.
    assert run(pg,tasks[1])=='success'
    assert tick()[0]==[] # Completed zero-factor result is a valid probe miss.
    with Session(pg) as session:
        logs=list(session.scalars(select(ProbeRunLog)))
        assert any(log.payload_json.get('changed_count')==0 for log in logs)
        for code in CODES:
            session.add(Factor(ts_code=code,trade_date=date(2026,11,13),adj_factor=Decimal('1')))
            session.add(Factor(ts_code=code,trade_date=EXECUTION_DAY,adj_factor=Decimal('2')))
        session.commit()
    history,_=tick(); assert len(history)==2
    assert run(pg,history[0])=='success'
    # Later source factor changes cannot rescreen the other frozen frequency.
    with Session(pg) as session:
        session.get(Factor,(CODES[1],EXECUTION_DAY)).adj_factor=Decimal('1'); session.commit()
    assert run(pg,history[1])=='success'
    with Session(pg) as session:
        headers=list(session.scalars(select(Delivery).where(Delivery.purpose=='factor_history',Delivery.record_kind=='plan_frozen')))
        assert len(headers)==2
        for task_id in history:
            task=session.get(TaskRun,task_id)
            assert task.time_input_json['business_date']=='2026-11-16'
            assert task.request_payload_json['maintenance_intent']=={'kind':'factor_history'}
    assert len(platform['requests'])==8 # 2 readiness + 2 current + 4 stock histories.
    history_requests=[req for req in platform['requests'] if 'ts_code' in req['params']]
    assert {(r['params']['ts_code'],r['params']['freq']) for r in history_requests}=={(c,f) for c in CODES for f in ('week','month')}
    assert all(set(r['params'])=={'ts_code','freq','limit','offset'} for r in history_requests)
    assert tick()[0]==[] and len(platform['requests'])==8


@pytest.mark.parametrize('freq,period',[('week','20261113'),('month','20261130')])
def test_formal_api_current_client_database_and_quote_chain(pg,api,platform,freq,period):
    platform['reply']=lambda req:[source_row(code=code,freq=freq,stamp=date.fromisoformat('2026-11-13' if freq=='week' else '2026-11-30')) for code in CODES]
    task_id=submit(api,freq=freq,kind='current_period',day=date(2026,11,13))
    assert view(api,task_id)['run']['status']=='queued'
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Delivery))==0
        assert session.scalar(select(func.count()).select_from(Raw))==0
    assert not platform['requests']
    assert run(pg,task_id)=='success'
    received=platform['requests']
    assert len(received)==1 and received[0]['params']=={'freq':freq,'trade_date':period,'limit':6000,'offset':0}
    assert received[0]['fields'].split(',')==list(SOURCE_FIELDS)
    result=view(api,task_id)
    assert (result['progress']['unit_done'],result['progress']['unit_total'],result['progress']['rows_saved'])==(1,1,2)
    assert result['nodes'][0]['status']=='success'
    bars=quote(api,freq=freq)
    assert bars['meta']['bar_count']==1 and Decimal(str(bars['bars'][0]['close']))==Decimal('11.14')
    assert bars['bars'][0]['trade_date']==('2026-11-13' if freq=='week' else '2026-11-30')
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw).where(Raw.freq==freq))==2
        assert session.scalar(select(func.count()).select_from(Serving).where(Serving.freq==freq))==2


def test_history_to_quote_pagination_withdrawal_and_combination(pg,api,platform):
    platform['reply']=lambda req:[*history_reply(req),source_row(code=req['params']['ts_code'],stamp=date(2020,1,31))]
    initial=submit(api,codes=list(CODES)); assert run(pg,initial)=='success'
    assert [req['params'] for req in platform['requests']]==[
        {'ts_code':code,'freq':'month','limit':6000,'offset':0} for code in CODES]
    latest=quote(api,limit=1)
    assert latest['meta']=={'bar_count':1,'has_more_history':True,'next_start_date':'2020-01-31'}
    assert latest['bars'][0]['trade_date']=='2020-02-29' and Decimal(str(latest['bars'][0]['close']))==Decimal('11.14')
    older=quote(api,limit=1,end=latest['meta']['next_start_date'])
    assert older['bars'][0]['trade_date']=='2020-01-31' and not older['meta']['has_more_history']
    assert Decimal(str(quote(api,adjustment='backward')['bars'][-1]['close']))==Decimal('1582.95')
    previous_calls=len(platform['requests'])
    withdraw=submit(api,kind='remove_keys',keys=[removal()]); assert run(pg,withdraw)=='success'
    assert len(platform['requests'])==previous_calls
    remaining=quote(api,limit=1)
    assert remaining['bars'][0]['trade_date']=='2020-02-28' and Decimal(str(remaining['bars'][0]['close']))==Decimal('12.01')
    combination=submit(api,kind='stock_history_and_remove',codes=[CODES[0]],keys=[removal(),removal(CODES[1])])
    assert run(pg,combination)=='success'
    assert len(platform['requests'])==previous_calls+1
    for code in CODES:
        assert quote(api,code=code,limit=1)['bars'][0]['trade_date']=='2020-02-28'
    empty=submit(api,kind='remove_keys',keys=[removal(stamp='2020-02-28'),removal(stamp='2020-01-31')])
    assert run(pg,empty)=='success' and quote(api)['bars']==[]
    assert quote(api,code=CODES[1])['meta']['bar_count']==2


def test_closed_period_full_market_and_older_history_cannot_overwrite_current(pg,api,platform):
    platform['reply']=lambda req:[source_row(code=code) for code in CODES]
    period=submit(api,kind='period',period=date(2020,2,29)); assert run(pg,period)=='success'
    platform['reply']=lambda req:[source_row(code=req['params']['ts_code'],end=date(2026,11,13),qfq='9.99')]
    history=submit(api,codes=[CODES[0]]); assert run(pg,history)=='success'
    assert Decimal(str(quote(api,limit=1)['bars'][0]['close']))==Decimal('11.14')
    with Session(pg) as session:
        fact=session.scalar(select(Delivery).where(Delivery.record_kind=='unit',Delivery.purpose=='stock_history'))
        assert fact.payload['raw_written']==0 and fact.payload['raw_protected']==1


def test_real_http_full_page_then_short_page_counts_and_deduplicates(pg,api,platform):
    row=source_row()
    platform['reply']=lambda req:[row]*6000 if req['params']['offset']==0 else [row]
    task=submit(api,codes=[CODES[0]])
    assert run(pg,task)=='success'
    assert [r['params']['offset'] for r in platform['requests']]==[0,6000]
    summary=view(api,task)['progress']
    assert summary['rows_fetched']==6001 and summary['rows_saved']==1 and summary['rows_rejected']==0
    with Session(pg) as session:
        fact=session.scalar(select(Delivery).where(Delivery.record_kind=='unit'))
        assert (fact.payload['source_received'],fact.payload['source_unique'],fact.payload['pages'])==(6001,1,2)
    assert quote(api)['meta']['bar_count']==1


@pytest.mark.parametrize('failure',['api_error','missing_field'])
def test_source_failure_is_not_zero_and_original_scope_can_resume(pg,api,platform,failure):
    if failure=='api_error': platform['reply']=lambda req:b'{"code":-1,"msg":"deliberate source failure","data":null}'
    else: platform['reply']=lambda req:_wire(list(SOURCE_FIELDS[:-1]),[source_row()])
    task=submit(api,codes=[CODES[0]])
    assert run(pg,task)=='failed'
    failed=view(api,task)
    assert failed['run']['status']=='failed' and failed['nodes'][0]['status']=='failed'
    with Session(pg) as session:
        assert session.scalar(select(func.count()).select_from(Raw))==0
        assert session.scalar(select(func.count()).select_from(Delivery).where(Delivery.record_kind=='unit'))==0
    assert len(platform['requests'])==1
    platform['reply']=history_reply
    recovered=submit(api,resume=task); assert run(pg,recovered)=='success'
    assert quote(api)['bars'][0]['trade_date']=='2020-02-29'


def test_observation_failure_does_not_rollback_real_client_business_commit(pg,api,platform,monkeypatch):
    from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
    platform['reply']=history_reply
    def failed_observation(*args): raise RuntimeError('deliberate observation failure')
    monkeypatch.setattr(TaskRunIngestionContext,'_update_current_running_node',failed_observation)
    task=submit(api,codes=[CODES[0]]); assert run(pg,task)=='success'
    assert view(api,task)['nodes'][0]['status']=='success'
    calls=len(platform['requests']); replay=submit(api,resume=task)
    assert run(pg,replay)=='success' and len(platform['requests'])==calls
    assert quote(api)['meta']['bar_count']==1
