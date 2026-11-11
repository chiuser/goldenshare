"""Disposable PostgreSQL: existing ingestion/Serving entry -> persisted facts -> card queries.

The official monthly payload is the Tushare sample recorded in LLD §9.3.
Other prices, basic data and calendar rows are explicit synthetic fixtures.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from time import perf_counter

import pytest
from sqlalchemy import create_engine, insert, select, delete, func, event
from sqlalchemy.orm import Session, sessionmaker

from tests.wealth_watchlist_postgres_support import isolated_postgres
from tests.test_index_period_raw import source_mock
from src.app.models.app_user import AppUser
from src.app.runtime.ops_worker_factory import build_operations_worker
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.ingestion.index_period_serving import SHANGHAI
from src.ops.index_series_active_store_adapter import OpsIndexSeriesActiveStore
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.dataset_card_query_service import DatasetCardQueryService
from src.ops.queries.dataset_card_query_service import DatasetResolutionPolicy, ProbeRule, StdMappingRule, StdCleansingRule
from src.ops.queries.biz_table_card_query_service import BizTableCardQueryService
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.queries.task_run_query_service import TaskRunQueryService
from src.ops.schemas.manual_action import ManualActionTaskRunCreateRequest
from src.ops.services.manual_action_service import ManualActionCommandService
from src.ops.services.task_run_service import TaskRunCommandService
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService

NOW=datetime(2026,11,10,22,30,tzinfo=SHANGHAI)
DAY=date(2026,11,10)
CODES=('000001.SH','399001.SZ','399006.SZ','000688.SH','000300.SH',
       '000905.SH','000852.SH','899050.BJ','000510.SH','000016.SH')


@pytest.fixture(scope='module')
def cluster(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp('period-cards-pg')) as engine:
        yield engine


@pytest.fixture
def pg_env(cluster,mocker,request):
    database='cards_'+uuid4().hex
    with cluster.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.exec_driver_sql(f'CREATE DATABASE {database}')
    engine=create_engine(cluster.url.set(database=database))
    models=(AppUser,IndexBasic,TradeCalendar,IndexSeriesActive,RawIndexDaily,RawIndexWeeklyBar,RawIndexMonthlyBar,
        IndexWeeklyServing,IndexMonthlyServing,TaskRun,TaskRunNode,TaskRunIssue,OpsSchedule,DatasetStatusSnapshot,
        DatasetResolutionPolicy,ProbeRule,StdMappingRule,StdCleansingRule)
    with engine.begin() as conn:
        for schema in sorted({m.__table__.schema for m in models}):
            conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
        for model in models:
            model.__table__.create(conn)
        first=date(2026,9,1)
        days=[first+timedelta(days=i) for i in range((date(2026,12,31)-first).days+1)]
        conn.execute(insert(TradeCalendar),[dict(exchange='SSE',trade_date=d,is_open=d.weekday()<5 and not date(2026,10,1)<=d<=date(2026,10,7)) for d in days])
        codes=getattr(request,'param',CODES)
        if codes:
            conn.execute(insert(IndexSeriesActive),[dict(resource='index_period_serving',ts_code=c,first_seen_date=DAY,last_seen_date=DAY,last_checked_at=NOW) for c in codes])
            conn.execute(insert(IndexBasic),[dict(ts_code=c,list_date=date(2000,1,1)) for c in codes])
    factory=sessionmaker(bind=engine)
    clock=mocker.patch('src.ops.runtime.index_period_serving_executor.datetime')
    clock.now.side_effect=lambda zone:NOW.astimezone(zone)
    mocker.patch.object(BizTableCardQueryService,'_local_now',return_value=NOW)
    mocker.patch.object(OpsFreshnessQueryService,'_business_reference_now',side_effect=lambda today=None,now=None:now or NOW)
    with factory() as session:
        for frequency in ('weekly','monthly'):
            for serving in (False,True):
                session.add(OpsSchedule(target_type='maintenance_action' if serving else 'dataset_action',
                    target_key=f'maintenance.update_index_{frequency}_serving' if serving else f'index_{frequency}.maintain',
                    display_name=f'{frequency}-{serving}',schedule_type='cron',trigger_mode='schedule',timezone='Asia/Shanghai',
                    cron_expr='0 22 * * *' if serving else '0 19 * * *',calendar_policy='trading_day_point' if serving else
                    'weekly_last_trading_day' if frequency=='weekly' else 'monthly_first_trading_day'))
        session.commit()
        yield session,build_operations_worker(session_factory=factory),engine
    engine.dispose()


def card_map(session,source):
    response=DatasetCardQueryService().list_cards(session,source_key=source)
    return {c.card_key:c for g in response.groups for c in g.items}


@pytest.mark.parametrize('pg_env',[(CODES[0],)],indirect=True)
def test_formal_monthly_raw_child_serving_snapshot_and_cards(pg_env,mocker):
    session,worker,engine=pg_env
    # Exact recorded Tushare payload; only network fetching is replaced.
    payload=dict(ts_code=CODES[0],trade_date='20261030',open=3838.9774,high=3864.1181,low=3574.2712,
        close=3599.0166,pre_close=3842.1946,change=-243.178,pct_chg=-0.0633,vol=781191473400.0,amount=12647618608842.0)
    calls=source_mock(mocker,lambda *_:[payload])
    schedule=session.scalar(select(OpsSchedule).where(OpsSchedule.target_key=='index_monthly.maintain'))
    due=datetime(2026,11,2,19,tzinfo=SHANGHAI)
    schedule.next_run_at=due
    session.commit()
    parent,=OperationsScheduleService().enqueue_due_schedules(session,now=due)
    result=worker.run_task_run(session,parent.id)
    assert result.status=='success', TaskRunQueryService().get_issue_detail(session,task_run_id=result.id,issue_id=result.primary_issue_id).model_dump()
    child=session.scalar(select(TaskRun).where(TaskRun.trigger_source=='system'))
    assert child.time_input_json['trade_date']=='2026-10-30'
    assert worker.run_task_run(session,child.id).status=='success'
    assert session.get(RawIndexMonthlyBar,(CODES[0],date(2026,10,30))).close==Decimal('3599.0166')
    assert session.scalar(select(IndexMonthlyServing.close))==Decimal('3599.0166')
    assert len(calls)==1
    assert DatasetStatusSnapshotService().refresh_resources(session,['index_weekly','index_monthly'],strict=True)==2
    raw=card_map(session,'tushare')['index_monthly']
    serving=card_map(session,'biz_tableset')['index_monthly_serving']
    assert raw.latest_business_date==date(2026,10,30) and raw.expected_business_date==date(2026,10,30)
    assert raw.latest_task_run.id==parent.id
    assert serving.expected_business_date==DAY and serving.updated_code_count==0 and serving.expected_code_count==1
    assert serving.latest_task_run.id==child.id and serving.latest_task_run.time_scope.start=='2026-10-30'


def test_daily_partial_failure_persists_nine_codes_and_card_diagnostics(pg_env,mocker):
    session,worker,engine=pg_env
    days=[date(2026,11,i) for i in (2,3,4,5,6,9,10)]
    session.execute(insert(RawIndexDaily),[dict(ts_code=c,trade_date=d,open=100,high=106,low=98,close=102,pre_close=100,vol=7,amount=250)
        for c in CODES for d in days if not(c=='899050.BJ' and d==DAY)])
    for model,first in ((IndexWeeklyServing,date(2026,11,9)),(IndexMonthlyServing,date(2026,11,2))):
        session.execute(insert(model),[dict(ts_code=c,period_start_date=first,trade_date=date(2026,11,9),source='derived_daily',close=100) for c in CODES])
    session.commit()
    for frequency,model in (('weekly',IndexWeeklyServing),('monthly',IndexMonthlyServing)):
        action=f'maintenance.update_index_{frequency}_serving'
        run_id=ManualActionCommandService().create_task_run_for_action(session,user=SimpleNamespace(id=1),action_key=action,
            body=ManualActionTaskRunCreateRequest(time_input={'mode':'point','trade_date':DAY.isoformat()},filters={}))
        run=worker.run_task_run(session,run_id)
        assert run.status=='failed' and run.rows_saved==9
        with Session(engine) as reader:
            assert reader.scalar(select(func.count()).select_from(model).where(model.trade_date==DAY))==9
        card=card_map(session,'biz_tableset')[f'index_{frequency}_serving']
        assert (card.updated_code_count,card.expected_code_count,card.status)==(9,10,'failed')
        assert card.latest_task_run.id==run_id
        issue=TaskRunQueryService().get_issue_detail(session,task_run_id=run_id,issue_id=run.primary_issue_id)
        assert '899050.BJ' in str(issue.technical_payload) and '2026-11-10' in str(issue.technical_payload)
    # Measure only the two newly added cards; the fifteen existing cards are independently regressed.
    from src.ops.catalog.biz_dataset_definitions import list_biz_dataset_definitions
    definitions=tuple(d for d in list_biz_dataset_definitions() if d.observation_query_key=='index_period_serving')
    mocker.patch('src.ops.queries.biz_table_card_query_service.list_biz_dataset_definitions',return_value=definitions)
    measured=[]
    for step in ('normal','repeat','readback'):
        observed=[]
        def observe(conn,cursor,sql,parameters,context,executemany):
            if sql.startswith('SELECT'):
                observed.append((sql,cursor.rowcount))
        event.listen(engine,'after_cursor_execute',observe)
        started=perf_counter()
        try:
            result=card_map(session,'biz_tableset')
        finally:
            event.remove(engine,'after_cursor_execute',observe)
        elapsed=(perf_counter()-started)*1000
        assert all(c.updated_code_count==9 and c.expected_code_count==10 for c in result.values())
        coverage=[n for sql,n in observed if 'period_start_date =' in sql and 'ts_code IN' in sql]
        assert coverage==[10,10]
        recent=[sql for sql,n in observed if 'ops.task_run.primary_issue_id' in sql and 'LIMIT' in sql and 'ops.task_run.requested_at DESC' in sql]
        assert len(recent)==2
        assert all('plan_snapshot_json' not in sql and 'ingestion_diagnostics_json' not in sql for sql in recent)
        measured.append(dict(step=step,select_statements=len(observed),sql_projected_rows=sum(n for _,n in observed),
            serving_rows=sum(coverage),elapsed_ms=round(elapsed,3)))
    print('PHASE4_CARD_READS '+json.dumps(measured))


@pytest.mark.parametrize('pg_env',[()],indirect=True)
def test_cutover_backup_pool_only_cleanup_resume_and_rollback(pg_env,tmp_path):
    session,worker,engine=pg_env
    models=(IndexWeeklyServing,IndexMonthlyServing)
    outsiders=('000998.SH','000999.SH')
    for model in models:
        session.execute(insert(model),[dict(ts_code=c,period_start_date=date(2026,11,9) if model is IndexWeeklyServing else date(2026,11,2),
            trade_date=DAY,source='derived_daily' if c=='899050.BJ' else 'api',close=Decimal('123.4567')) for c in (*CODES,*outsiders)])
    session.execute(insert(IndexSeriesActive),dict(resource='index_daily',ts_code=CODES[0],first_seen_date=DAY,last_seen_date=DAY,last_checked_at=NOW))
    session.commit()
    retained={m.__tablename__:session.execute(select(m.__table__).where(m.ts_code.in_(CODES)).order_by(m.ts_code)).mappings().all() for m in models}
    backup={m.__tablename__:[dict(row) for row in session.execute(select(m.__table__).where(m.ts_code.in_(outsiders))).mappings()] for m in models}
    path=tmp_path/'outside-backup.json'
    path.write_text(json.dumps(backup,default=str))
    OpsIndexSeriesActiveStore(session).upsert_seen_codes('index_period_serving',{c:DAY for c in CODES},checked_at=NOW)
    session.commit()
    assert OpsIndexSeriesActiveStore(session).list_active_codes('index_period_serving')==sorted(CODES)
    # Simulate interruption after the first committed table/code unit, then read persisted facts in a new session.
    session.execute(delete(IndexWeeklyServing).where(IndexWeeklyServing.ts_code==outsiders[0]))
    session.commit()
    with Session(engine) as resumed:
        for model in models:
            remaining=resumed.scalars(select(model.ts_code).where(model.ts_code.in_(outsiders))).all()
            if remaining:
                resumed.execute(delete(model).where(model.ts_code.in_(remaining)))
                resumed.commit()
            assert resumed.scalar(select(func.count()).select_from(model).where(model.ts_code.not_in(CODES)))==0
            assert resumed.execute(select(model.__table__).where(model.ts_code.in_(CODES)).order_by(model.ts_code)).mappings().all()==retained[model.__tablename__]
        restored=json.loads(path.read_text())
        for model in models:
            rows=restored[model.__tablename__]
            for row in rows:
                for column in model.__table__.columns:
                    value=row[column.name]
                    if value is not None and column.type.python_type in (date,datetime,Decimal):
                        row[column.name]=(column.type.python_type.fromisoformat(value) if column.type.python_type in (date,datetime) else Decimal(value))
            resumed.execute(insert(model),rows)
        resumed.execute(delete(IndexSeriesActive).where(IndexSeriesActive.resource=='index_period_serving',IndexSeriesActive.ts_code.in_(CODES)))
        resumed.commit()
        assert OpsIndexSeriesActiveStore(resumed).list_active_codes('index_period_serving')==[]
        assert OpsIndexSeriesActiveStore(resumed).list_active_codes('index_daily')==[CODES[0]]
        for model in models:
            assert resumed.scalar(select(func.count()).select_from(model))==12
            assert resumed.execute(select(model.__table__).where(model.ts_code.in_(outsiders)).order_by(model.ts_code)).mappings().all()==backup[model.__tablename__]
            assert resumed.execute(select(model.__table__).where(model.ts_code.in_(CODES)).order_by(model.ts_code)).mappings().all()==retained[model.__tablename__]
