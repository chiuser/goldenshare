"""Real isolated PostgreSQL acceptance. Never connects to a configured Prod DB."""

from dataclasses import replace
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjContractError, select_serving
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput, ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.models.raw.raw_stock_basic import RawStockBasic as Basic
from src.foundation.models.raw.raw_suspend_d import RawSuspendD as Suspend
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw
from src.foundation.models.core.trade_calendar import TradeCalendar as Calendar
from src.foundation.models.core_serving_light.bse_mapping import BseMappingLight as Mapping
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj as Serving
from src.foundation.models.core.stock_period_adj_delivery import StockPeriodAdjDelivery as Delivery
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from test_stock_period_adj_contracts import literal_rows


def migrate(engine, revision):
    path = next(Path('alembic/versions').glob(revision+'_*.py'))
    spec = importlib.util.spec_from_file_location('period_test_migration_'+revision, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()


@pytest.fixture
def pg():
    value = os.environ.get('STOCK_PERIOD_P2_DATABASE_URL')
    if not value:
        pytest.skip('explicit task-owned PostgreSQL socket required')
    url = make_url(value)
    assert url.drivername == 'postgresql+psycopg' and url.host is None and url.password is None
    assert url.database == 'postgres' and url.query['host'].startswith('/private/tmp/stock-period-p2-')
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    name = 'stock_period_p2_'+uuid4().hex[:12]
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url.set(database=name))
    with engine.begin() as conn:
        for schema in ['core','raw_tushare','core_serving','core_serving_light','ops']:
            conn.execute(text(f'CREATE SCHEMA {schema}'))
        for model in [Basic,Suspend,Raw,Calendar,Mapping,Serving,TaskRun,TaskRunNode,TaskRunIssue,OpsSchedule,ProbeRule,ProbeRunLog]:
            if model is Serving:
                # Reproduce the pre-190 schema, so migration190 itself creates
                # cycle uniqueness; current ORM metadata must agree afterwards.
                from sqlalchemy.schema import CreateTable
                conn.execute(CreateTable(model.__table__))
                for index in model.__table__.indexes:
                    if index.name.startswith('idx_'): index.create(conn)
            else:
                model.__table__.create(conn)
    migrate(engine,'20261116_000189')
    migrate(engine,'20261116_000190')
    with Session(engine) as session:
        session.add(Basic(ts_code='000001.SZ',curr_type='CNY',exchange='SZSE',list_status='L',list_date=date(1991,4,3)))
        for first,last in [(date(2020,2,24),date(2020,3,31)),(date(2026,11,9),date(2026,11,16))]:
            day=first
            while day<=last:
                session.add(Calendar(exchange='SSE',trade_date=day,is_open=day.weekday()<5))
                day+=timedelta(days=1)
        session.commit()
    yield engine
    engine.dispose(); admin.dispose()
    # Kept in this task-owned cluster for independent readback, not dropped per test.


def request(freq='month',kind='current_period',day=date(2026,11,13),run_id=None,filters=None):
    return DatasetActionRequest(dataset_key='stk_period_bar_adj_'+freq,action='maintain',
        time_input=DatasetTimeInput(mode='point',business_date=day) if kind=='current_period' else DatasetTimeInput(mode='point',trade_date=day),
        maintenance_intent={'kind':kind},filters=filters or {},run_id=run_id)


def plan(engine, req, **kwargs):
    with Session(engine) as session:
        return DatasetActionResolver(session).build_plan(req, persist_plan=True, **kwargs)


def row_for(unit, code='000001.SZ', end=date(2026,11,13), qfq=None):
    # Deliberate date/code variants of the real literal sample test execution rules,
    # not market-price correctness. Expected prices stay independent literals.
    row={**literal_rows()[0], 'ts_code':code, 'freq':unit.request_params['freq'],
         'trade_date':unit.trade_date, 'end_date':end}
    if qfq is not None: row['close_qfq']=Decimal(qfq)
    return row


def execute(engine, req, planned, *, rows=None, cancel=None, report=None):
    class Source:
        def iter_stock_period_adj_pages(self,**kwargs):
            unit=kwargs['unit']
            kwargs['control'].fetching(1,0)
            supplied=rows(unit) if rows else [row_for(unit)]
            yield SimpleNamespace(rows_raw=supplied)
    with Session(engine) as session:
        executor=IngestionExecutor(session); executor.source_client=Source()
        validated=ValidatedDatasetActionRequest(request_id=planned.plan_id,dataset_key=req.dataset_key,action='maintain',
            run_profile=planned.run_profile,trigger_source=req.trigger_source,run_id=req.run_id,execution_context=planned.execution_context)
        return executor.run(request=validated,definition=get_dataset_definition(req.dataset_key),units=planned.units,
            cancel_checker=cancel,progress_reporter=report)


@pytest.mark.parametrize('freq,expected', [('week',date(2026,11,13)),('month',date(2026,11,30))])
def test_current_projection_and_real_transaction(freq,expected,pg):
    req=request(freq,day=date(2026,11,10)); planned=plan(pg,req)
    assert planned.units[0].request_params == {'freq':freq,'trade_date':expected.strftime('%Y%m%d')}
    assert planned.units[0].trade_date == expected
    result=execute(pg,req,planned)
    assert result.unit_done==1 and result.rows_written==1 and result.rows_rejected==0
    with Session(pg) as session:
        raw=session.scalar(select(Raw)); serving=session.scalar(select(Serving))
        assert raw.trade_date==serving.trade_date==expected
        assert raw.close_qfq==serving.close_qfq==Decimal('11.14')
        assert raw.change==serving.change_amount==Decimal('-1.04')
        assert set(session.scalars(select(Delivery.record_kind))) == {'plan_unit','plan_frozen','unit','batch_closed'}


def test_real_dual_month_literal_preserves_raw_and_selects_whole_latest(pg):
    with Session(pg) as session:
        session.add(Raw(**literal_rows()[1])); session.commit()
    req=request(kind='period',day=date(2020,2,29)); planned=plan(pg,req)
    execute(pg,req,planned,rows=lambda unit:[literal_rows()[0]])
    with Session(pg) as session:
        assert len(session.scalars(select(Raw)).all())==2
        row=session.scalar(select(Serving))
        assert row.trade_date==date(2020,2,29) and row.close_qfq==Decimal('11.14')
        assert row.open_hfq==Decimal('1527.27')


def test_older_source_cannot_overwrite_and_equal_date_platform_revision_can(pg):
    req=request(); first=plan(pg,req)
    execute(pg,req,first,rows=lambda unit:[row_for(unit,end=date(2026,11,13),qfq='11.14')])
    old=plan(pg,request(day=date(2026,11,10)))
    result=execute(pg,req,old,rows=lambda unit:[row_for(unit,end=date(2026,11,10),qfq='9.99')])
    assert result.rows_written==0
    same=plan(pg,request())
    execute(pg,req,same,rows=lambda unit:[row_for(unit,end=date(2026,11,13),qfq='11.15')])
    with Session(pg) as session:
        assert session.scalar(select(Raw.close_qfq))==Decimal('11.15')
        assert session.scalar(select(Serving.close_qfq))==Decimal('11.15')


def test_committed_replay_does_not_download_and_observation_failure_does_not_rollback(pg):
    req=request(run_id=100); planned=plan(pg,req)
    def failed_observation(*args): raise RuntimeError('observation unavailable')
    execute(pg,req,planned,report=failed_observation)
    result=execute(pg,req,planned,rows=lambda unit:pytest.fail('committed unit must not be fetched again'))
    assert result.unit_done==1 and result.rows_written==1
    with Session(pg) as session:
        assert len(session.scalars(select(Raw)).all())==1
        assert len(session.scalars(select(Delivery).where(Delivery.record_kind=='unit')).all())==1


def test_cancel_after_first_commit_only_resumes_second_original_unit(pg):
    req=DatasetActionRequest(dataset_key='stk_period_bar_adj_month',action='maintain',run_id=101,
        time_input=DatasetTimeInput(mode='range',start_date=date(2020,2,29),end_date=date(2020,3,31)))
    planned=plan(pg,req); canceled=False; seen=[]
    def report(snapshot,message):
        nonlocal canceled
        seen.append(snapshot.unit_done)
        if snapshot.unit_done==1: canceled=True
    with pytest.raises(IngestionCanceledError):
        execute(pg,req,planned,cancel=lambda run_id:canceled,report=report)
    assert seen==sorted(seen) and max(seen)==1
    with Session(pg) as session:
        assert len(session.scalars(select(Delivery).where(Delivery.record_kind=='unit')).all())==1
    requested=[]
    def source(unit):
        requested.append(unit.trade_date); return [row_for(unit)]
    result=execute(pg,req,planned,rows=source)
    assert requested==[date(2020,3,31)] and result.unit_done==2


def test_plan_cancel_keeps_unexecutable_draft_without_quotes(pg):
    req=request()
    def canceled(current,total): raise IngestionCanceledError('cancel planning')
    with pytest.raises(IngestionCanceledError): plan(pg,req,planning_report=canceled)
    with Session(pg) as session:
        assert list(session.scalars(select(Delivery.record_kind)))==['plan_unit']
        assert not session.scalars(select(Raw)).all()


def test_full_day_suspension_and_zero_results_are_used_without_upstream_receipts(pg):
    with Session(pg) as session:
        session.add(Suspend(ts_code='000001.SZ',trade_date=date(2026,11,13),suspend_type='S',suspend_timing=None,row_key_hash='suspend-test'))
        session.commit()
    req=request(); planned=plan(pg,req)
    assert planned.units[0].progress_context['required_dates']=={}
    result=execute(pg,req,planned,rows=lambda unit:[])
    assert result.unit_done==1 and result.rows_written==0


def test_new_stock_intraday_suspension_still_requires_source(pg):
    with Session(pg) as session:
        session.add(Basic(ts_code='600000.SH',curr_type='CNY',exchange='SSE',list_status='L',list_date=date(2026,11,13)))
        session.add(Suspend(ts_code='600000.SH',trade_date=date(2026,11,13),suspend_type='S',suspend_timing='09:30-10:00',row_key_hash='intraday-test'))
        session.commit()
    req=request(); planned=plan(pg,req)
    assert planned.units[0].progress_context['required_dates']['600000.SH']=='2026-11-13'
    from src.foundation.ingestion.errors import IngestionWriteError
    with pytest.raises(IngestionWriteError,match='600000.SH'):
        execute(pg,req,planned)
    with Session(pg) as session:
        assert not session.scalars(select(Raw)).all()


def test_delivery_records_reject_update_and_delete_in_database(pg):
    plan(pg,request())
    for operation in ['UPDATE core.stock_period_adj_delivery SET purpose=purpose','DELETE FROM core.stock_period_adj_delivery']:
        with pytest.raises(Exception,match='append only'):
            with pg.begin() as conn: conn.execute(text(operation))


def test_period_capture_accepts_both_original_dates_and_selects_28_if_newer(pg):
    rows=literal_rows()
    rows[1]['end_date']=date(2026,11,16)
    req=request(kind='period',day=date(2020,2,29)); planned=plan(pg,req)
    execute(pg,req,planned,rows=lambda unit:rows)
    with Session(pg) as session:
        assert len(session.scalars(select(Raw)).all())==2
        selected=session.scalar(select(Serving))
        assert selected.trade_date==date(2020,2,28) and selected.close_qfq==Decimal('12.01')


def test_manual_republish_uses_raw_candidates_and_dry_run_does_not_write(pg):
    from src.foundation.dao.factory import DAOFactory
    from src.foundation.resolution.types import ResolutionPolicy
    from src.foundation.serving.publish_service import ServingPublishService
    rows=literal_rows(); rows[1]['end_date']=date(2026,11,16)
    with Session(pg) as session:
        session.add_all([Raw(**row) for row in rows]); session.commit()
        # Resolution metadata must never override the latest Raw row.
        store=SimpleNamespace(get_enabled_policy=lambda *a:ResolutionPolicy(dataset_key='stk_period_bar_adj_month',mode='primary',primary_source_key='other'))
        service=ServingPublishService(DAOFactory(session),policy_store=store)
        planned=service.plan_publish(dataset_key='stk_period_bar_adj_month',std_rows_by_source={'tushare':[rows[0]]})
        assert planned.rows==[rows[1]]
        assert service.execute_publish_plan(planned,dry_run=True).written==0
        assert not session.scalars(select(Serving)).all()
        assert service.execute_publish_plan(planned).written==1
        session.expire_all()
        assert session.scalar(select(Serving.trade_date))==date(2020,2,28)
        assert len(session.scalars(select(Raw)).all())==2


def test_same_period_unique_index_and_frequency_lock(pg):
    from src.foundation.ingestion.stock_period_adj_delivery import acquire_writer
    with Session(pg) as first, Session(pg) as second:
        acquire_writer(first,'week')
        with pytest.raises(StockPeriodAdjContractError,match='已有发布事务'): acquire_writer(second,'week')
        acquire_writer(second,'month')
    rows=literal_rows()
    with Session(pg) as session:
        session.add(Serving(**{('change_amount' if k=='change' else k):v for k,v in rows[0].items()})); session.commit()
        session.add(Serving(**{('change_amount' if k=='change' else k):v for k,v in rows[1].items()}))
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError,match='uq_stk_period_adj_serving_month'): session.commit()


def test_date_audit_normalizes_selected_source_date_and_keeps_real_gap(pg):
    from src.ops.services.date_completeness_audit_service import ActualBucketReader
    row=literal_rows()[1]
    with Session(pg) as session:
        session.add(Serving(**{('change_amount' if k=='change' else k):v for k,v in row.items()})); session.commit()
        reader=ActualBucketReader()
        params=dict(target_table='core_serving.stk_period_bar_adj',observed_field='trade_date',date_axis='natural_day',
            row_identity_filters={'freq':'month'},period_frequency='month')
        assert reader.read(session,start_date=date(2020,2,29),end_date=date(2020,2,29),**params)=={date(2020,2,29)}
        assert reader.read(session,start_date=date(2020,3,31),end_date=date(2020,3,31),**params)==set()


def rule_for(freq='month'):
    return ProbeRule(name='股票复权周期线测试',dataset_key='stk_period_bar_adj_'+freq,source_key='tushare',
        window_start='20:00',window_end='00:00',timezone_name='Asia/Shanghai',probe_interval_seconds=60,
        max_triggers_per_day=1,probe_condition_json={'type':'stock_period_adj_current_ready'},
        on_success_action_json={'action_type':'dataset_action','action_key':'stk_period_bar_adj_'+freq+'.maintain','request':{'time_input':{'mode':'point'}}})


def test_probe_window_open_day_and_active_or_completed_delivery_skip_source(pg,monkeypatch):
    import src.ops.services.stock_period_adj_probe_service as probe
    calls=[]
    monkeypatch.setattr(probe,'check_current_period',lambda *a,**kw:(calls.append(kw) or True,'ready',{'business_date':'2026-11-13'}))
    from zoneinfo import ZoneInfo
    sh=ZoneInfo('Asia/Shanghai')
    with Session(pg) as session:
        rule=rule_for()
        for day,hour,minute in [(13,19,59),(14,0,0),(14,20,0)]:
            assert probe.evaluate(session,rule,current=datetime(2026,11,day,hour,minute,tzinfo=sh))[0] is False
        assert not calls
        assert probe.evaluate(session,rule,current=datetime(2026,11,13,20,tzinfo=sh))[0]
        create_task(session)
        assert probe.evaluate(session,rule,current=datetime(2026,11,13,20,tzinfo=sh))[0] is False
        assert len(calls)==1
    # A business completion suppresses a probe even without a successful TaskRun.
    req=request(); planned=plan(pg,req); execute(pg,req,planned)
    with Session(pg) as session:
        assert probe.evaluate(session,rule,current=datetime(2026,11,13,20,tzinfo=sh))[0] is False
        assert len(calls)==1


def create_task(session, *, resume=None, kind='current_period', dates=None):
    from src.ops.services.task_run_service import TaskRunCommandService,TaskRunCreateContext
    return TaskRunCommandService().create_task_run(session,context=TaskRunCreateContext(
        task_type='dataset_action',resource_key='stk_period_bar_adj_month',action='maintain',
        time_input={} if resume else (dates or {'mode':'point','business_date':'2026-11-13'}),filters={},
        request_payload={} if resume else {'maintenance_intent':{'kind':kind}},trigger_source='manual',
        requested_by_user_id=1,resume_from_task_run_id=resume))


def patch_source(monkeypatch, supplier):
    from src.foundation.ingestion.source_client import DatasetSourceClient
    def pages(self,**kwargs):
        kwargs['control'].fetching(1,0)
        yield SimpleNamespace(rows_raw=supplier(kwargs['unit']),page_no=1)
    monkeypatch.setattr(DatasetSourceClient,'iter_stock_period_adj_pages',pages)


def test_task_intake_worker_real_commit_and_terminal_node(pg,monkeypatch):
    from src.ops.runtime.worker import OperationsWorker
    patch_source(monkeypatch,lambda unit:[row_for(unit)])
    with Session(pg) as session:
        task=create_task(session)
        assert not session.scalars(select(Delivery)).all(), 'intake must not generate a long plan'
        finished=OperationsWorker().run_task_run(session,task.id)
        assert finished.status=='success'
        assert (finished.unit_done,finished.unit_total,finished.progress_percent)==(1,1,100)
        node=session.get(TaskRunNode,finished.current_node_id)
        assert node.status=='success' and node.rows_saved==finished.rows_saved==1
        assert session.scalar(select(Serving.close_qfq))==Decimal('11.14')
        assert finished.time_input_json=={'mode':'point','business_date':'2026-11-13'}
        assert finished.request_payload_json['maintenance_intent']=={'kind':'current_period'}


def test_task_worker_failure_and_cancel_have_consistent_terminal_nodes(pg,monkeypatch):
    from src.ops.runtime.worker import OperationsWorker
    patch_source(monkeypatch,lambda unit:[])
    with Session(pg) as session:
        task=create_task(session); result=OperationsWorker().run_task_run(session,task.id)
        assert result.status=='failed' and result.unit_done==0
        assert session.get(TaskRunNode,result.current_node_id).status=='failed'
    def cancel_source(unit):
        with Session(pg) as writer:
            task=writer.scalar(select(TaskRun).where(TaskRun.status=='running'))
            task.cancel_requested_at=datetime.now(UTC); writer.commit()
        return [row_for(unit)]
    patch_source(monkeypatch,cancel_source)
    with Session(pg) as session:
        task=create_task(session); result=OperationsWorker().run_task_run(session,task.id)
        assert result.status=='canceled' and result.unit_done==0
        assert session.get(TaskRunNode,result.current_node_id).status=='canceled'
        assert not session.scalars(select(Raw)).all()


def test_explicit_resume_restores_frozen_range_after_input_changes(pg,monkeypatch):
    from src.ops.runtime.worker import OperationsWorker
    patch_source(monkeypatch,lambda unit:[])
    with Session(pg) as session:
        task=create_task(session); OperationsWorker().run_task_run(session,task.id); original=task.id
        session.add(Basic(ts_code='600000.SH',curr_type='CNY',list_date=date(2026,11,13))); session.commit()
        restored=create_task(session,resume=original)
        assert restored.time_input_json['business_date']=='2026-11-13'
        patch_source(monkeypatch,lambda unit:[row_for(unit)])
        finished=OperationsWorker().run_task_run(session,restored.id)
        assert finished.status=='success' and finished.rows_saved==1


def test_source_same_count_different_code_and_identical_duplicate_are_rejected(pg):
    from src.foundation.ingestion.errors import IngestionWriteError
    req=request(); planned=plan(pg,req)
    for supplied in [lambda unit:[row_for(unit,code='600000.SH')],lambda unit:[row_for(unit),row_for(unit)]]:
        with pytest.raises(IngestionWriteError): execute(pg,req,planned,rows=supplied)
    with Session(pg) as session: assert not session.scalars(select(Raw)).all()


def test_process_exit_after_commit_keeps_original_manifest_and_resume(pg):
    req=DatasetActionRequest(dataset_key='stk_period_bar_adj_month',action='maintain',run_id=201,
        time_input=DatasetTimeInput(mode='range',start_date=date(2020,2,29),end_date=date(2020,3,31)))
    planned=plan(pg,req)
    def process_exit(snapshot,message):
        if snapshot.unit_done==1: raise SystemExit('deliberate process exit after business commit')
    with pytest.raises(SystemExit): execute(pg,req,planned,report=process_exit)
    with Session(pg) as session:
        restored=DatasetActionResolver(session).build_plan(replace(req,execution_context=planned.execution_context))
        assert restored.units==planned.units
    asked=[]
    result=execute(pg,req,restored,rows=lambda unit:(asked.append(unit.trade_date) or [row_for(unit)]))
    assert asked==[date(2020,3,31)] and result.unit_done==2


def test_probe_real_readiness_wait_then_enqueues_original_business_day(pg,monkeypatch):
    from src.ops.services.operations_probe_runtime_service import ProbeRuntimeService
    from src.ops.services.stock_period_adj_probe_service import evaluate
    from zoneinfo import ZoneInfo
    rule=rule_for(); current=datetime(2026,11,13,20,tzinfo=ZoneInfo('Asia/Shanghai'))
    patch_source(monkeypatch,lambda unit:[])
    with Session(pg) as session:
        assert evaluate(session,rule,current=current)[0] is False
        assert not session.scalars(select(TaskRun)).all()
        patch_source(monkeypatch,lambda unit:[{'ts_code':'000001.SZ','trade_date':unit.trade_date,'end_date':date(2026,11,13)}])
        matched,_,payload=evaluate(session,rule,current=current)
        assert matched and payload['source_received']==1
        task=ProbeRuntimeService()._enqueue_on_match(session,rule,probe_payload=payload)
        assert task.time_input_json=={'mode':'point','business_date':'2026-11-13'}
        assert task.request_payload_json['maintenance_intent']=={'kind':'current_period'}
        assert not session.scalars(select(Delivery)).all()


def test_worker_observation_database_failure_does_not_rollback_business(pg,monkeypatch):
    from src.ops.runtime.worker import OperationsWorker
    from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
    def observation_error(*args): raise RuntimeError('deliberate observation transaction failure')
    monkeypatch.setattr(TaskRunIngestionContext,'_update_current_running_node',observation_error)
    patch_source(monkeypatch,lambda unit:[row_for(unit)])
    with Session(pg) as session:
        task=create_task(session); result=OperationsWorker().run_task_run(session,task.id)
        assert result.status=='success' and result.unit_done==1 and result.progress_percent==100
        node=session.get(TaskRunNode,result.current_node_id)
        assert node.status=='success' and node.rows_saved==1
        assert len(session.scalars(select(Delivery).where(Delivery.record_kind=='unit')).all())==1


def test_normal_identity_mapping_prefers_confirmed_current_code_and_excludes_future_listing(pg):
    from src.foundation.ingestion.stock_period_adj_inputs import period_inputs
    with Session(pg) as session:
        session.add_all([Basic(ts_code='830001.BJ',curr_type='CNY',list_date=date(2020,1,1)),
                         Basic(ts_code='920001.BJ',curr_type='CNY',list_date=date(2020,1,1)),
                         Basic(ts_code='600001.SH',curr_type='CNY',list_date=date(2026,11,16))])
        session.add(Mapping(o_code='830001.BJ',n_code='920001.BJ',fetched_at=datetime.now(UTC))); session.commit()
        inputs=period_inputs(session,day=date(2026,11,13),freq='month')
        assert inputs['eligible_codes']==['000001.SZ','920001.BJ']
        assert '830001.BJ' not in inputs['required_dates'] and '600001.SH' not in inputs['required_dates']


def test_plan_row_and_byte_budgets_fail_before_quote_write(pg):
    from src.foundation.ingestion.stock_period_adj_planning import resolve_units
    definition=get_dataset_definition('stk_period_bar_adj_month')
    definition=replace(definition,planning=replace(definition.planning,
        stock_period_adj_policy=replace(definition.planning.stock_period_adj_policy,max_plan_bytes=100)))
    with Session(pg) as session:
        with pytest.raises(StockPeriodAdjContractError,match='字节限制'):
            resolve_units(session,request(),definition,persist=True)
        assert not session.scalars(select(Delivery)).all() and not session.scalars(select(Raw)).all()


def test_period_synthetic_page_boundary_transaction_budget(pg,tmp_path):
    """6,000 synthetic stock identities test the declared page/SQL boundary, not real prices."""
    import time
    from src.foundation.datasets.stock_period_adj_contracts import canonical_json
    codes=[f'{value:06d}.SZ' for value in range(1,6001)]
    with Session(pg) as session:
        session.add_all([Basic(ts_code=code,curr_type='CNY',list_date=date(1991,4,3)) for code in codes[1:]])
        session.commit()
    started=time.monotonic(); req=request(); planned=plan(pg,req); planning_seconds=time.monotonic()-started
    rows=[row_for(planned.units[0],code=code) for code in codes]
    started=time.monotonic(); result=execute(pg,req,planned,rows=lambda unit:rows); first_seconds=time.monotonic()-started
    started=time.monotonic(); repeated=execute(pg,req,planned,rows=lambda unit:pytest.fail('no download on replay')); replay_seconds=time.monotonic()-started
    started=time.monotonic()
    with Session(pg) as session:
        from sqlalchemy import func
        assert session.scalar(select(func.count()).select_from(Raw))==6000
        assert session.scalar(select(func.count()).select_from(Serving))==6000
        fact=session.scalar(select(Delivery).where(Delivery.record_kind=='unit'))
        assert fact.payload['source_received']==fact.payload['raw_written']==fact.payload['serving_written']==6000
        assert fact.payload['candidate_rows']==6000
    readback_seconds=time.monotonic()-started
    assert result.rows_written==repeated.rows_written==6000
    (tmp_path/'boundary-performance.json').write_text(json.dumps({'synthetic_stocks':6000,'canonical_bytes':len(canonical_json(rows).encode()),
        'planning_seconds':planning_seconds,'capture_publish_seconds':first_seconds,'replay_seconds':replay_seconds,
        'final_count_readback_seconds':readback_seconds}))


def test_freshness_period_and_current_delivery_dates_are_distinct(pg):
    from src.ops.dataset_definition_projection import get_dataset_freshness_projection
    from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
    req=request(); planned=plan(pg,req); execute(pg,req,planned)
    with Session(pg) as session:
        session.add(Serving(**{('change_amount' if k=='change' else k):v for k,v in literal_rows()[1].items()})); session.commit()
        projection=get_dataset_freshness_projection('stk_period_bar_adj_month')
        observed,_,_=OpsFreshnessQueryService()._observed_dataset_snapshots(session,[projection],reference_date=date(2026,11,13))
        assert observed['stk_period_bar_adj_month']==(date(2020,2,29),date(2020,2,29))
        from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
        assert StockPeriodAdjDeliveryDAO(session).latest_complete_date('month',date(2026,11,13))==date(2026,11,13)
        assert StockPeriodAdjDeliveryDAO(session).latest_complete_date('week',date(2026,11,13)) is None


def test_ambiguous_identity_mapping_is_reported_not_chosen(pg):
    from src.foundation.ingestion.stock_period_adj_inputs import period_inputs
    with Session(pg) as session:
        session.add_all([Mapping(o_code='830001.BJ',n_code=code,fetched_at=datetime.now(UTC)) for code in ['920001.BJ','920002.BJ']]); session.commit()
        with pytest.raises(StockPeriodAdjContractError,match='多个确认股票代码'):
            period_inputs(session,day=date(2026,11,13),freq='month')


@pytest.mark.parametrize('adjustment,expected',[('forward',Decimal('11.14')),('backward',Decimal('1582.95'))])
def test_quote_real_unique_period_pagination_and_indicator_input(pg,adjustment,expected):
    from src.biz.queries.quote_query_service import QuoteQueryService,ResolvedInstrument
    from src.foundation.ingestion.stock_period_adj_delivery import republish_groups,bounded_transaction,acquire_writer
    from src.foundation.datasets.stock_period_adj_contracts import period_start
    rows=literal_rows()
    older={**rows[0],'trade_date':date(2020,1,31)}
    policy=get_dataset_definition('stk_period_bar_adj_month').planning.stock_period_adj_policy
    with Session(pg) as session:
        session.add_all([Raw(**row) for row in [older,*rows]]);session.commit()
        with bounded_transaction(session,policy,lambda:None):
            acquire_writer(session,'month')
            republish_groups(session,[('000001.SZ',date(2020,1,1)),('000001.SZ',date(2020,2,1))],'month',policy,lambda:None)
            session.commit()
        instrument=ResolvedInstrument(ts_code='000001.SZ',symbol='000001',market='CN',security_type='stock',
            name='平安银行',exchange='SZSE',industry=None,list_status='L')
        query=QuoteQueryService()
        latest=query.build_kline(session,instrument=instrument,period='month',adjustment=adjustment,start_date=None,end_date=None,limit=1)
        assert latest.meta.bar_count==1 and latest.bars[0].close==expected
        assert latest.meta.has_more_history and latest.meta.next_start_date==date(2020,1,31)
        before=query.build_kline(session,instrument=instrument,period='month',adjustment=adjustment,start_date=None,end_date=latest.meta.next_start_date,limit=1)
        assert before.meta.bar_count==1 and not before.meta.has_more_history
        assert before.bars[0].trade_date==date(2020,1,31)
        both=query._load_stock_period_points(session,ts_code='000001.SZ',period='month',adjustment=adjustment,
            start_date=None,end_date=None,limit=100)
        assert [point.trade_date for point in both]==[date(2020,1,31),date(2020,2,29)]


def test_cancel_immediately_after_commit_reports_committed_unit(pg,monkeypatch):
    import src.foundation.ingestion.stock_period_adj_delivery as delivery
    canceled=False
    acquire=delivery.acquire_writer
    def mark(session,freq):
        acquire(session,freq); session.info['period_publication']=True
    commit=Session.commit
    def committed(session):
        nonlocal canceled
        commit(session)
        if session.info.get('period_publication'): canceled=True
    monkeypatch.setattr(delivery,'acquire_writer',mark)
    monkeypatch.setattr(Session,'commit',committed)
    req=request(run_id=601); planned=plan(pg,req)
    with pytest.raises(IngestionCanceledError) as raised:
        execute(pg,req,planned,cancel=lambda run_id:canceled)
    assert raised.value.stock_period_adj_progress['unit_done']==1
    assert raised.value.stock_period_adj_progress['rows_saved']==1
    with Session(pg) as session:
        assert len(session.scalars(select(Delivery).where(Delivery.record_kind=='unit')).all())==1
        assert len(session.scalars(select(Raw)).all())==len(session.scalars(select(Serving)).all())==1


def test_closed_period_uses_union_and_last_required_day_not_only_last_day(pg):
    from src.foundation.ingestion.stock_period_adj_inputs import period_inputs
    with Session(pg) as session:
        session.add(Basic(ts_code='600000.SH',curr_type='CNY',list_date=date(2010,1,1),delist_date=date(2026,11,12)))
        session.add(Suspend(ts_code='000001.SZ',trade_date=date(2026,11,13),suspend_type='S',suspend_timing=None,row_key_hash='closed-suspend'))
        session.commit()
        current=period_inputs(session,day=date(2026,11,13),freq='week')
        assert current['required_dates']=={} and current['eligible_codes']==['000001.SZ']
        closed=period_inputs(session,day=date(2026,11,13),freq='week',closed_period=True)
        assert closed['required_dates']=={'000001.SZ':'2026-11-12','600000.SH':'2026-11-11'}


def test_latest_conflict_rolls_back_new_raw_serving_and_unit_fact(pg):
    from src.foundation.ingestion.errors import IngestionWriteError
    rows=literal_rows(); rows[1]['end_date']=rows[0]['end_date']
    with Session(pg) as session: session.add(Raw(**rows[1]));session.commit()
    req=request(kind='period',day=date(2020,2,29)); planned=plan(pg,req)
    with pytest.raises(IngestionWriteError,match='最新计算截至日期'):
        execute(pg,req,planned,rows=lambda unit:[rows[0]])
    with Session(pg) as session:
        assert list(session.scalars(select(Raw.trade_date)))==[date(2020,2,28)]
        assert not session.scalars(select(Serving)).all()
        assert not session.scalars(select(Delivery).where(Delivery.record_kind.in_(['unit','batch_closed']))).all()


def test_cumulative_database_deadline_rolls_back_whole_unit(pg):
    from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction
    policy=replace(get_dataset_definition('stk_period_bar_adj_month').planning.stock_period_adj_policy,
        db_statement_timeout_seconds=.15)  # Tightened test-only deadline; deployed value remains20s.
    with pytest.raises(StockPeriodAdjContractError) as raised:
        with Session(pg) as session:
            with bounded_transaction(session,policy,lambda:None):
                session.add(Raw(**literal_rows()[0]));session.flush()
                session.execute(text('select pg_sleep(0.10)'))
                session.execute(text('select pg_sleep(0.10)'))
                session.commit()
    assert raised.value.code=='stock_period_adj.business_deadline_exceeded'
    with Session(pg) as session: assert not session.scalars(select(Raw)).all()


@pytest.mark.parametrize('order',[('week','month'),('month','week')])
def test_two_frequencies_complete_independently_in_both_orders(pg,order):
    from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
    for index,freq in enumerate(order):
        req=request(freq,run_id=800+index); planned=plan(pg,req); execute(pg,req,planned)
        with Session(pg) as session:
            dao=StockPeriodAdjDeliveryDAO(session)
            assert dao.complete(date(2026,11,13),freq) is not None
            if index==0: assert dao.complete(date(2026,11,13),order[1]) is None
    with Session(pg) as session: assert set(session.scalars(select(Serving.freq)))=={'week','month'}


def test_formal_download_rechecks_after_successful_precheck(pg,monkeypatch):
    from src.foundation.ingestion.stock_period_adj_readiness import check_current_period
    from src.foundation.ingestion.errors import IngestionWriteError
    class Ready:
        def iter_stock_period_adj_pages(self,**kwargs):
            yield SimpleNamespace(rows_raw=[{'ts_code':'000001.SZ','trade_date':date(2026,11,30),'end_date':date(2026,11,13)}])
    with Session(pg) as session:
        assert check_current_period(session,dataset_key='stk_period_bar_adj_month',business_date=date(2026,11,13),source_client=Ready())[0]
    req=request(); planned=plan(pg,req)
    with pytest.raises(IngestionWriteError,match='未达到'): execute(pg,req,planned,rows=lambda unit:[])
    with Session(pg) as session:
        assert not session.scalars(select(Raw)).all()
        assert not session.scalars(select(Delivery).where(Delivery.record_kind=='unit')).all()
    # This failed frequency never becomes a dependency of the other current task.
    week=request('week'); execute(pg,week,plan(pg,week))


def test_resume_uses_original_policy_instead_of_new_definition_defaults(pg):
    req=request(); planned=plan(pg,req)
    definition=get_dataset_definition(req.dataset_key)
    changed=replace(definition,planning=replace(definition.planning,
        stock_period_adj_policy=replace(definition.planning.stock_period_adj_policy,source_timeout_seconds=1,max_pages=1)))
    class Source:
        def iter_stock_period_adj_pages(self,**kwargs):
            policy=kwargs['definition'].planning.stock_period_adj_policy
            assert policy.source_timeout_seconds==20 and policy.max_pages==3
            yield SimpleNamespace(rows_raw=[row_for(kwargs['unit'])])
    with Session(pg) as session:
        executor=IngestionExecutor(session);executor.source_client=Source()
        result=executor.run(request=ValidatedDatasetActionRequest(request_id=planned.plan_id,dataset_key=req.dataset_key,
            action='maintain',run_profile=planned.run_profile,trigger_source='manual',execution_context=planned.execution_context),
            definition=changed,units=planned.units,cancel_checker=None,progress_reporter=None)
        assert result.unit_done==1
