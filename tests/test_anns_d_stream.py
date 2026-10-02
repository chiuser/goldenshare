from dataclasses import replace
from datetime import date
import json
import os
from uuid import uuid4
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine,select,text,func
from sqlalchemy.orm import Session
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest,DatasetTimeInput
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.errors import IngestionError
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from src.foundation.models.raw.anns_d_sync import AnnsDSyncUnit,AnnsDSyncRequestBudget
from src.foundation.ingestion.announcement_stream import ANNOUNCEMENT_EXECUTION_LOCK

DAY=date(2026,1,1)


def action(context=None, start=DAY, end=DAY):
    return DatasetActionRequest(dataset_key='anns_d',action='maintain',
        time_input=DatasetTimeInput(mode='range',start_date=start,end_date=end),execution_context=context)


def test_frozen_contract_survives_json_and_requires_same_scope():
    resolver=DatasetActionResolver(Mock())
    plan=resolver.build_plan(action())
    frozen=json.loads(json.dumps(plan.execution_context))
    replay=resolver.build_plan(action(frozen))
    assert replay.execution_context==frozen
    assert resolver.build_plan(action()).execution_context['execution_token']!=frozen['execution_token']
    with pytest.raises(IngestionError):resolver.build_plan(action(frozen,end=date(2026,1,2)))
    altered={**frozen,'contract_digest':'0'*64}
    with pytest.raises(IngestionError):resolver.build_plan(action(altered))


def test_day_limit_checked_before_expansion(monkeypatch):
    import src.foundation.ingestion.unit_planner as planner
    monkeypatch.setattr(planner,'_expand_natural_dates',lambda *args:pytest.fail('expanded over budget'))
    with pytest.raises(IngestionError):DatasetActionResolver(Mock()).build_plan(action(start=date(2000,1,1),end=date(2026,1,1)))


@pytest.fixture
def engine():
    url=os.environ.get('ANNS_P1_TEST_DATABASE_URL')
    if not url:pytest.skip('isolated task-owned PostgreSQL required')
    assert '/private/tmp/anns-p1-pg-socket-' in url
    base=create_engine(url,isolation_level='AUTOCOMMIT')
    name='anns_p2_'+uuid4().hex[:12]
    with base.connect() as conn:conn.execute(text('CREATE DATABASE '+name))
    target=create_engine(base.url.set(database=name))
    with target.begin() as conn:
        conn.execute(text('CREATE SCHEMA raw_tushare'))
        RawAnnsD.__table__.create(conn)
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        spec=importlib.util.spec_from_file_location('receipt_migration','alembic/versions/20261002_000182_add_anns_d_sync_receipts.py')
        migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):migration.upgrade()
    yield target
    target.dispose();base.dispose()


def raw(i):
    return dict(ann_date='20260101',ts_code='155162.SH',name='债券',title=f'公告{i}',url=f'https://example.org/{i}.pdf',rec_time=None)


def fake_source(monkeypatch, rows):
    calls=[]
    class Connector:
        def call_bounded(self,**kwargs):
            kwargs['check']();kwargs['before_request']()
            params=kwargs['params'];calls.append(dict(params))
            return rows[params['offset']:params['offset']+params['limit']]
    monkeypatch.setattr('src.foundation.ingestion.source_client.create_source_connector',lambda key:Connector())
    return calls


def run(engine, plan, **kwargs):
    with Session(engine) as session:
        executor=IngestionExecutor(session)
        request=DatasetMaintainService._validated_request_from_plan(request=action(plan.execution_context),plan=plan)
        return executor.run(request=request,definition=get_dataset_definition('anns_d'),units=plan.units,**kwargs)


def counts(engine):
    with engine.connect() as c:
        return tuple(c.execute(select(func.count()).select_from(x)).scalar() for x in (RawAnnsD,AnnsDSyncUnit))


def test_commit_cancel_resume_replay_and_new_observation(engine,monkeypatch):
    calls=fake_source(monkeypatch,[raw(i) for i in range(2001)])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    snapshots=[]
    canceled=False
    def progress(snapshot,message):
        nonlocal canceled
        snapshots.append(snapshot)
        if snapshot.rows_committed>=500:canceled=True
    with pytest.raises(IngestionCanceledError):run(engine,plan,cancel_checker=lambda _:canceled,progress_reporter=progress)
    assert counts(engine)==(500,0)
    assert [x.rows_committed for x in snapshots]==sorted(x.rows_committed for x in snapshots)
    result=run(engine,plan)
    assert counts(engine)==(2001,1) and result.unit_done==1
    assert [x['offset'] for x in calls]==[0,0,2000]
    before=len(calls);run(engine,plan)
    assert len(calls)==before and counts(engine)==(2001,1)
    new=DatasetActionResolver(Mock()).build_plan(action())
    run(engine,new)
    assert len(calls)==before+2 and counts(engine)==(2001,2)
    with engine.connect() as c:
        issued=c.execute(select(AnnsDSyncRequestBudget.issued_requests).where(AnnsDSyncRequestBudget.execution_token==plan.execution_context['execution_token'])).scalar()
        assert issued==3


def test_observation_failure_does_not_rollback_or_block(engine,monkeypatch):
    fake_source(monkeypatch,[raw(1)])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    def failing(*args):raise RuntimeError('observation offline')
    result=run(engine,plan,progress_reporter=failing)
    assert result.rows_committed==1 and counts(engine)==(1,1)


def test_process_exit_after_commit_preserves_batch_without_receipt(engine,monkeypatch):
    fake_source(monkeypatch,[raw(i) for i in range(2001)])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    def exiting(snapshot,message):
        if snapshot.rows_committed==500:raise SystemExit('simulated process exit')
    with pytest.raises(SystemExit):run(engine,plan,progress_reporter=exiting)
    assert counts(engine)==(500,0)
    run(engine,plan)
    assert counts(engine)==(2001,1)


def test_empty_day_receipt_and_dataset_lock(engine,monkeypatch):
    calls=fake_source(monkeypatch,[])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        lock.execute(text('SELECT pg_advisory_lock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK})
        try:
            with pytest.raises(IngestionError,match='占用'):run(engine,plan)
        finally:lock.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK})
    assert not calls
    run(engine,plan)
    assert counts(engine)==(0,1)


def test_receipt_failure_rolls_back_only_terminal_batch(engine,monkeypatch):
    from src.foundation.dao.anns_d_sync_dao import AnnsDSyncDAO
    fake_source(monkeypatch,[raw(i) for i in range(501)])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    method=AnnsDSyncDAO.complete
    monkeypatch.setattr(AnnsDSyncDAO,'complete',lambda *args,**kw:(_ for _ in ()).throw(RuntimeError('receipt fault')))
    with pytest.raises(RuntimeError):run(engine,plan)
    assert counts(engine)==(500,0)
    monkeypatch.setattr(AnnsDSyncDAO,'complete',method)
    run(engine,plan)
    assert counts(engine)==(501,1)


def test_old_storage_blocks_empty_day_before_request(engine,monkeypatch):
    calls=fake_source(monkeypatch,[])
    with engine.begin() as c:c.execute(text('ALTER TABLE raw_tushare.anns_d ADD COLUMN group_key VARCHAR(64)'))
    plan=DatasetActionResolver(Mock()).build_plan(action())
    with pytest.raises(IngestionError,match='原始存储结构'):run(engine,plan)
    assert not calls and counts(engine)==(0,0)


def test_persisted_budget_exhaustion_survives_resume(engine,monkeypatch):
    from src.foundation.dao.anns_d_sync_dao import AnnsDSyncDAO
    calls=fake_source(monkeypatch,[])
    plan=DatasetActionResolver(Mock()).build_plan(action())
    with Session(engine) as s:
        dao=AnnsDSyncDAO(s,plan.execution_context)
        dao.reserve_request(15000)
        s.execute(text('UPDATE raw_tushare.anns_d_sync_request_budget SET issued_requests=15000'))
        s.commit()
    for _ in range(2):
        with pytest.raises(IngestionError,match='预算已用完'):run(engine,plan)
    assert not calls and counts(engine)==(0,0)


def test_bounded_source_page_row_limits_and_retry(monkeypatch):
    from src.foundation.clients.bounded_tushare_call import BoundedTushareError
    definition=get_dataset_definition('anns_d')
    plan=DatasetActionResolver(Mock()).build_plan(action())
    unit=replace(plan.units[0],page_limit=2,max_source_rows_per_unit=4)
    control=Mock(); calls=[]
    class Connector:
        def call_bounded(self,**kwargs):
            kwargs['before_request']();calls.append(kwargs['params']['offset'])
            if len(calls)==1:raise BoundedTushareError('source_connection_failed','network')
            return [raw(1),raw(2)]
    monkeypatch.setattr('src.foundation.ingestion.source_client.create_source_connector',lambda key:Connector())
    policy=replace(definition.planning.announcement_policy,max_pages_per_unit=2)
    limited=replace(definition,planning=replace(definition.planning,announcement_policy=policy))
    pages=DatasetSourceClient().iter_bounded_pages(definition=limited,unit=unit,control=control)
    assert next(pages).retry_count==1
    assert next(pages).offset==2
    with pytest.raises(IngestionError,match='页数'):next(pages)
    assert calls==[0,0,2] and control.reserve.call_count==3
    control.reset_mock();calls.clear()
    pages=DatasetSourceClient().iter_bounded_pages(definition=definition,unit=replace(unit,max_source_rows_per_unit=1),control=control)
    with pytest.raises(IngestionError,match='源行'):next(pages)


def test_retry_wait_cancellation_does_not_issue_next_request(monkeypatch):
    from src.foundation.clients.bounded_tushare_call import BoundedTushareError
    class Connector:
        def call_bounded(self,**kwargs):
            kwargs['before_request']()
            raise BoundedTushareError('source_connection_failed','network')
    monkeypatch.setattr('src.foundation.ingestion.source_client.create_source_connector',lambda key:Connector())
    control=Mock();control.wait.side_effect=IngestionCanceledError('stop during retry')
    plan=DatasetActionResolver(Mock()).build_plan(action())
    with pytest.raises(IngestionCanceledError):list(DatasetSourceClient().iter_bounded_pages(
        definition=get_dataset_definition('anns_d'),unit=plan.units[0],control=control))
    assert control.reserve.call_count==1


def test_multiple_pages_bound_memory_transactions_and_readback(engine,monkeypatch):
    import resource,time
    from sqlalchemy import event
    from pathlib import Path
    from src.foundation.models.raw.raw_anns_d import RawAnnsD
    durations=[];snapshots=[];offsets=[]
    @event.listens_for(Session,'after_begin')
    def begun(session,transaction,connection):session.info['anns_test_start']=time.monotonic()
    @event.listens_for(Session,'after_commit')
    def committed(session):
        if 'anns_test_start' in session.info:durations.append(time.monotonic()-session.info.pop('anns_test_start'))
    class Connector:
        def call_bounded(self,**kwargs):
            kwargs['before_request']();offset=kwargs['params']['offset'];offsets.append(offset)
            return [raw(i) for i in range(offset,min(offset+2000,10001))]
    monkeypatch.setattr('src.foundation.ingestion.source_client.create_source_connector',lambda key:Connector())
    try:
        plan=DatasetActionResolver(Mock()).build_plan(action())
        started=time.monotonic()
        result=run(engine,plan,progress_reporter=lambda snapshot,message:snapshots.append((time.monotonic(),snapshot)))
        with engine.connect() as c:
            titles=set(c.execute(select(RawAnnsD.title)).scalars())
        assert titles=={f'公告{i}' for i in range(10001)}
        assert offsets==[0,2000,4000,6000,8000,10000]
        assert result.rows_committed==10001 and counts(engine)==(10001,1)
        assert max(durations)<30
        gaps=[b[0]-a[0] for a,b in zip(snapshots,snapshots[1:])]
        assert max(gaps)<30
        evidence={'source_rows':10001,'source_pages':6,'physical_rows':len(titles),'completed_days':1,
                  'elapsed_seconds':round(time.monotonic()-started,3),'maximum_commit_transaction_seconds':round(max(durations),3),
                  'maximum_progress_gap_seconds':round(max(gaps),3),'process_peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'note':'generated single-page fixture, parent test-process RSS includes pytest; not Prod capacity proof'}
        Path('/private/tmp/anns-p2-stream-performance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    finally:
        event.remove(Session,'after_begin',begun);event.remove(Session,'after_commit',committed)


def test_receipt_migration_has_stable_ddl_and_actual_head():
    import importlib.util,io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('receipt_migration','alembic/versions/20261002_000182_add_anns_d_sync_receipts.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=io.StringIO()
    ctx=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
    with Operations.context(ctx):module.upgrade()
    ddl=output.getvalue()
    assert module.down_revision=='20261002_000181'
    assert 'CREATE TABLE raw_tushare.anns_d_sync_unit' in ddl and 'CREATE TABLE raw_tushare.anns_d_sync_request_budget' in ddl
    assert 'FOREIGN KEY' not in ddl

def test_live_verified_missing_url_pair_preserves_both_source_records(engine,monkeypatch):
    # MCP read-only verification: 155162.SH / 2023-06-09, six explicit source fields.
    rows = [
    {
        "ann_date": "20230609",
        "ts_code": "155162.SH",
        "name": "19津投04",
        "title": "关于19津投04（155162）盘中临时停牌的公告",
        "url": None,
        "rec_time": None
    },
    {
        "ann_date": "20230609",
        "ts_code": "155162.SH",
        "name": "19津投04",
        "title": "关于19津投04（155162）盘中临时停牌的公告",
        "url": "http://dataclouds.cninfo.com.cn/sjother/regulatory_announcement/sse/7d5d3210069711eeb155fa163ebe0297.pdf",
        "rec_time": None
    }
]
    fake_source(monkeypatch,rows)
    day=date(2023,6,9)
    plan=DatasetActionResolver(Mock()).build_plan(action(start=day,end=day))
    result=run(engine,plan)
    with engine.connect() as c:
        saved=list(c.execute(select(RawAnnsD)).mappings())
    assert result.rows_fetched==2 and result.rows_committed==2 and result.rows_rejected==0
    assert len(saved)==2 and {r['url'] for r in saved} == {None, rows[1]['url']}
    assert all(r['rec_time'] is None for r in saved)
    assert counts(engine)==(2,1)


def test_batch_deadline_is_cumulative_across_statements(engine):
    from src.foundation.ingestion.announcement_stream import bounded_business_batch
    import time
    from sqlalchemy.exc import OperationalError
    with Session(engine) as session:
        started=time.monotonic()
        with pytest.raises(OperationalError):
            with bounded_business_batch(session,.3,lambda:None):
                session.execute(text('SELECT pg_sleep(0.2)'))
                session.execute(text('SELECT pg_sleep(0.2)'))
        session.rollback()
        assert time.monotonic()-started<1.5
        assert counts(engine)==(0,0)


@pytest.mark.parametrize('field',['max_pages_per_unit','max_requests_per_execution','max_response_bytes','source_call_timeout_seconds'])
@pytest.mark.parametrize('value',[0,-1,None,True])
def test_policy_budget_rejects_non_positive_integer(monkeypatch,field,value):
    from src.foundation.ingestion.linter import lint_all_dataset_definitions
    definition=get_dataset_definition('anns_d')
    policy=replace(definition.planning.announcement_policy,**{field:value})
    broken=replace(definition,planning=replace(definition.planning,announcement_policy=policy))
    monkeypatch.setattr('src.foundation.ingestion.linter.list_dataset_definitions',lambda:[broken])
    report=lint_all_dataset_definitions()
    assert any(x.code=='announcement_stream_budget_invalid' for x in report.issues)
