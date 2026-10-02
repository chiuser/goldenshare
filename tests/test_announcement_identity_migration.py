from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.foundation.datasets.anns_d_contracts import identity, AnnouncementPersistenceError
from src.foundation.ingestion.announcement_stream import ANNOUNCEMENT_EXECUTION_LOCK
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from src.foundation.services.migration.announcement_identity import AnnouncementIdentityMigration, old_identity, validate_row, business_bytes, atomic_json, read_metadata
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime.maintenance_executor import MaintenanceExecutionRequest
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.services.announcement_identity_task_executor import ACTION, AnnouncementIdentityTaskExecutor
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


def old_row(i=1, **values):
    row = dict(id=i, ann_date=date(2023,6,9), ts_code='155162.SH', name=None, title=f'公告{i}',
               url=f'https://example.org/{i}.pdf', rec_time=datetime(2023,6,9,tzinfo=timezone.utc),
               group_key=None, api_name='anns_d', fetched_at=datetime(2026,1,1,tzinfo=timezone.utc), raw_payload='original')
    row.update(values)
    row['row_key_hash'] = old_identity(row)
    return row


def test_old_name_null_and_nonempty_conflicts_remain_distinct():
    a, b = old_row(), old_row(2,title='公告1',url='https://example.org/other.pdf',name='公司')
    assert validate_row(a) == identity(a)
    assert validate_row(b) == identity(b)
    assert a['row_key_hash'] == old_row(name='公司')['row_key_hash']
    assert identity(a) != identity(old_row(name='公司'))


@pytest.mark.parametrize('change', [dict(url=None),dict(rec_time=None),dict(ts_code='155162.sh'),dict(title=' 公告1 '),dict(name='')])
def test_invalid_old_fields_stop(change):
    row=old_row();row.update(change)
    with pytest.raises((AnnouncementPersistenceError,ValueError)):validate_row(row)


def test_explicit_timezone_old_hash_is_not_silently_changed():
    row=old_row()
    row['row_key_hash']=hashlib.sha256('\x1f'.join(('anns_d','2023-06-09','155162.SH','公告1',row['url'],row['rec_time'].isoformat())).encode()).hexdigest()
    with pytest.raises(AnnouncementPersistenceError,match='旧身份'):validate_row(row)


def test_atomic_metadata_does_not_remove_existing_foreign_temporary_file(tmp_path):
    path=tmp_path/'state';temp=tmp_path/'state.writing';temp.write_text('foreign')
    with pytest.raises(FileExistsError):atomic_json(path,{'frozen':False})
    assert temp.read_text()=='foreign'


@pytest.mark.parametrize('params', [dict(execution_mode='DELETE'),dict(start_id=True),dict(end_id=0),dict(finalize='true'),dict(execution_mode='CHECK',finalize=True),dict(execution_mode='APPLY'),dict(unknown=True)])
def test_plan_rejects_unsafe_intents(params):
    values=dict(start_id=1,end_id=10,state_path='/private/tmp/test-state',execution_mode='CHECK');values.update(params)
    executor=AnnouncementIdentityTaskExecutor(session_factory=lambda:None)
    with pytest.raises(ValueError):executor.plan(MaintenanceExecutionRequest(ACTION,values))
    action=get_maintenance_action(ACTION)
    assert action.schedule_enabled is False


@pytest.fixture
def engine():
    url=os.environ.get('ANNS_P1_TEST_DATABASE_URL')
    if not url:pytest.skip('task-owned isolated PostgreSQL required')
    assert '/private/tmp/anns-p1-pg-socket-' in url
    base=create_engine(url,isolation_level='AUTOCOMMIT')
    name='anns_identity_'+uuid4().hex[:12]
    with base.connect() as connection:connection.execute(text(f'CREATE DATABASE "{name}"'))
    target=create_engine(base.url.set(database=name))
    with target.begin() as connection:
        connection.execute(text('CREATE SCHEMA raw_tushare'))
        connection.execute(text('CREATE SCHEMA ops'))
        for table in (RawAnnsD.__table__,TaskRun.__table__,TaskRunNode.__table__,TaskRunIssue.__table__):table.create(connection)
        connection.execute(text('ALTER TABLE raw_tushare.anns_d ALTER COLUMN group_key DROP NOT NULL'))
        connection.execute(text('CREATE SCHEMA core_serving_light'))
        connection.execute(text('CREATE VIEW core_serving_light.anns_d AS SELECT ann_date,ts_code,name,title,url,rec_time,row_key_hash FROM raw_tushare.anns_d'))
    yield target
    target.dispose();base.dispose()


def seed(engine,n=3):
    with engine.begin() as connection:connection.execute(insert(RawAnnsD.__table__),[old_row(i) for i in range(1,n+1)])


def stored(engine):
    with engine.connect() as connection:return list(connection.execute(select(RawAnnsD.__table__).order_by(RawAnnsD.id)).mappings())


def prepare(engine,tmp_path,n=3):
    seed(engine,n)
    runner=AnnouncementIdentityMigration(engine)
    path=tmp_path/'state.json'
    header=runner.run(mode='CHECK',start_id=1,end_id=n,state_path=path)
    # Test fixture recovery evidence only; production requires an actual pg_dump restore rehearsal.
    backup=tmp_path/'backup';backup.write_bytes(b'isolated test backup evidence')
    report=tmp_path/'restore.json'
    report.write_text(json.dumps(dict(table='raw_tushare.anns_d',database=header['scope']['database'],start_id=1,end_id=n,
        backup_path=str(backup),backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),restore_verified_at=datetime.now(timezone.utc).isoformat())))
    args=dict(mode='APPLY',start_id=1,end_id=n,state_path=path,recovery_report_path=report,expected_state_digest=header['state_digest'])
    return runner,args,header


def test_postgres_all_rows_and_fields_preserved_replay_and_finalize(engine,tmp_path):
    runner,args,header=prepare(engine,tmp_path)
    before=[business_bytes(r) for r in stored(engine)]
    runner.run(**args)
    assert [business_bytes(r) for r in stored(engine)]==before
    assert all((r['group_key'],r['row_key_hash'])==identity(r) for r in stored(engine))
    runner.run(**args,finalize=True)
    with engine.connect() as c:
        assert c.scalar(text("SELECT attnotnull FROM pg_attribute WHERE attrelid='raw_tushare.anns_d'::regclass AND attname='group_key'"))
        assert c.scalar(text('SELECT count(*) FROM core_serving_light.anns_d'))==3
    runner.run(**args,finalize=True)
    assert len(stored(engine))==header['count']==3


@pytest.mark.parametrize('exit_type',[IngestionCanceledError,SystemExit])
def test_postgres_cancel_or_process_exit_then_resume(engine,tmp_path,exit_type):
    runner,args,_=prepare(engine,tmp_path,501)
    values=[];canceled=False
    def progress(value):
        nonlocal canceled
        values.append(value)
        if value['phase']=='applying' and value['completed']==500:
            if exit_type is SystemExit:raise SystemExit('process exit')
            canceled=True
    with pytest.raises(exit_type):runner.run(**args,cancel=lambda:canceled,progress=progress)
    assert sum(r['group_key'] is not None for r in stored(engine))==500
    completed=[v['completed'] for v in values if v['phase']=='applying']
    assert completed==sorted(completed)
    AnnouncementIdentityMigration(engine).run(**args)
    assert len(stored(engine))==501 and all(r['group_key'] is not None for r in stored(engine))


def test_postgres_sql_failure_rolls_back_batch_without_dropping_index(engine,tmp_path):
    runner,args,_=prepare(engine,tmp_path)
    before=stored(engine)
    with engine.begin() as c:
        c.execute(text("""CREATE FUNCTION reject_identity() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.id=2 THEN RAISE EXCEPTION 'injected batch failure'; END IF; RETURN NEW; END $$"""))
        c.execute(text('CREATE TRIGGER identity_test BEFORE UPDATE ON raw_tushare.anns_d FOR EACH ROW EXECUTE FUNCTION reject_identity()'))
    with pytest.raises(AnnouncementPersistenceError,match='SQLSTATE=P0001'):runner.run(**args)
    assert stored(engine)==before
    runner._require_index()


def test_postgres_readback_drift_and_recovery_fail_before_update(engine,tmp_path):
    runner,args,_=prepare(engine,tmp_path)
    with engine.begin() as c:c.execute(update(RawAnnsD.__table__).where(RawAnnsD.id==2).values(raw_payload='changed'))
    with pytest.raises(AnnouncementPersistenceError,match='业务字段'):runner.run(**args)
    assert all(r['group_key'] is None for r in stored(engine))
    report=Path(args['recovery_report_path']);data=json.loads(report.read_text());data['backup_sha256']='0'*64;report.write_text(json.dumps(data))
    with pytest.raises(AnnouncementPersistenceError,match='备份摘要'):runner.run(**args)


def test_postgres_dataset_lock_and_partial_finalize_rejected(engine,tmp_path):
    runner,args,_=prepare(engine,tmp_path)
    with engine.connect() as c:
        c.execute(text('SELECT pg_advisory_lock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK});c.commit()
        try:
            with pytest.raises(AnnouncementPersistenceError,match='正在运行'):runner.run(**args)
        finally:c.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':ANNOUNCEMENT_EXECUTION_LOCK});c.commit()
    partial=tmp_path/'partial'
    header=runner.run(mode='CHECK',start_id=2,end_id=3,state_path=partial)
    with pytest.raises(AnnouncementPersistenceError,match='覆盖全表'):
        runner.run(**{**args,'start_id':2,'state_path':partial,'expected_state_digest':header['state_digest']},finalize=True)


def test_postgres_observation_failure_does_not_rollback_business(engine,tmp_path):
    runner,args,_=prepare(engine,tmp_path)
    def fail_progress(value):raise RuntimeError('observation unavailable')
    runner.run(**args,progress=fail_progress)
    assert all(r['group_key'] is not None for r in stored(engine))


def test_postgres_mid_batch_cancel_has_no_partial_commit(engine,tmp_path):
    runner,args,_=prepare(engine,tmp_path)
    canceled=False
    def on_sql(conn,cursor,statement,params,context,many):
        nonlocal canceled
        if statement.startswith('UPDATE raw_tushare.anns_d'):canceled=True
    event.listen(engine,'after_cursor_execute',on_sql)
    try:
        with pytest.raises(IngestionCanceledError):runner.run(**args,cancel=lambda:canceled)
    finally:event.remove(engine,'after_cursor_execute',on_sql)
    assert all(r['group_key'] is None for r in stored(engine))


def test_postgres_new_hash_unique_conflict_keeps_every_row_and_index(engine,tmp_path,monkeypatch):
    runner,args,_=prepare(engine,tmp_path)
    import src.foundation.services.migration.announcement_identity as module
    original=module.validate_row
    phase=False
    target=stored(engine)[1]['row_key_hash']
    def value(row):
        group,key=original(row)
        return group,target if phase and row['id']==1 else key
    monkeypatch.setattr(module,'validate_row',value)
    # Test injection after frozen scope recheck, without changing business columns.
    def progress(value):
        nonlocal phase
        if value['phase']=='applying':phase=True
    with pytest.raises(AnnouncementPersistenceError,match='SQLSTATE=23505'):runner.run(**args,progress=progress)
    assert len(stored(engine))==3 and all(r['group_key'] is None for r in stored(engine))
    runner._require_index()


def task(engine,params):
    with Session(engine) as session:
        record=TaskRunCommandService().create_task_run(session,context=TaskRunCreateContext(task_type='maintenance_action',resource_key=None,
            action='maintain',time_input={},filters={},request_payload={'target_key':ACTION,'target_type':'maintenance_action',**params},
            trigger_source='manual',requested_by_user_id=None))
        return record.id


def test_postgres_worker_success_failed_and_canceled_node_consistency(engine,tmp_path,monkeypatch):
    runner,args,header=prepare(engine,tmp_path,501)
    executor=AnnouncementIdentityTaskExecutor(session_factory=sessionmaker(engine))
    worker=OperationsWorker(TaskRunDispatcher(maintenance_executors={'announcement_identity':executor}))
    params={k:str(v) if isinstance(v,Path) else v for k,v in args.items() if k!='mode'}
    params['execution_mode']='APPLY'
    ident=task(engine,params)
    from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
    original=TaskRunIngestionContext.update_progress
    def progress(self,**kwargs):
        original(self,**kwargs)
        if kwargs.get('rows_saved')==500:
            with Session(engine) as session:
                session.execute(update(TaskRun).where(TaskRun.id==ident).values(cancel_requested_at=datetime.now(timezone.utc)));session.commit()
    monkeypatch.setattr(TaskRunIngestionContext,'update_progress',progress)
    with Session(engine) as session:
        record=worker.run_task_run(session,ident)
        assert record.status=='canceled' and record.rows_saved==500
        node=session.get(TaskRunNode,record.current_node_id)
        assert node.status==record.status and node.rows_saved==500
    monkeypatch.setattr(TaskRunIngestionContext,'update_progress',original)
    ident=task(engine,params)
    with Session(engine) as session:
        record=worker.run_task_run(session,ident)
        assert record.status=='success' and record.rows_saved==501
        assert session.get(TaskRunNode,record.current_node_id).status==record.status
    bad={**params,'expected_state_digest':'0'*64}
    ident=task(engine,bad)
    with Session(engine) as session:
        record=worker.run_task_run(session,ident)
        assert record.status=='failed'
        assert session.get(TaskRunNode,record.current_node_id).status==record.status


def test_postgres_actual_process_exit_releases_lock_and_resumes(engine,tmp_path):
    import subprocess
    import sys
    runner,args,_=prepare(engine,tmp_path,501)
    payload={k:str(v) if isinstance(v,Path) else v for k,v in args.items()}
    code='''import json, os
from sqlalchemy import create_engine
from src.foundation.services.migration.announcement_identity import AnnouncementIdentityMigration
args=json.loads(os.environ['MIGRATION_TEST_ARGS'])
def progress(value):
    if value['phase']=='applying' and value['completed']==500: os._exit(17)
AnnouncementIdentityMigration(create_engine(os.environ['MIGRATION_TEST_URL'])).run(**args,progress=progress)
'''
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'MIGRATION_TEST_ARGS':json.dumps(payload),
        'MIGRATION_TEST_URL':engine.url.render_as_string(hide_password=False)},timeout=20,capture_output=True)
    assert result.returncode==17,result.stderr.decode()
    assert sum(r['group_key'] is not None for r in stored(engine))==500
    runner.run(**args)
    assert len(stored(engine))==501 and all(r['group_key'] is not None for r in stored(engine))


def test_postgres_native_backup_restore_evidence_and_identity_only_apply(engine,tmp_path):
    import subprocess
    seed(engine,3)
    runner=AnnouncementIdentityMigration(engine)
    state=tmp_path/'frozen.json'
    header=runner.run(mode='CHECK',start_id=1,end_id=3,state_path=state)
    tools=Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (tools/'pg_dump').is_file():pytest.skip('existing native PostgreSQL tools required, never install')
    backup=tmp_path/'announcements.dump'
    url=engine.url.render_as_string(hide_password=False).replace('postgresql+psycopg:','postgresql:')
    subprocess.run([str(tools/'pg_dump'),'--dbname',url,'--format=custom','--schema=raw_tushare','--file',str(backup)],check=True,capture_output=True,timeout=20)
    restore_name='anns_restore_'+uuid4().hex[:12]
    with create_engine(engine.url,isolation_level='AUTOCOMMIT').connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{restore_name}"'))
    restored=create_engine(engine.url.set(database=restore_name))
    restore_url=restored.url.render_as_string(hide_password=False).replace('postgresql+psycopg:','postgresql:')
    subprocess.run([str(tools/'pg_restore'),'--exit-on-error','--dbname',restore_url,str(backup)],check=True,capture_output=True,timeout=20)
    assert [business_bytes(r) for r in stored(restored)]==[business_bytes(r) for r in stored(engine)]
    restored.dispose()
    report=tmp_path/'recovery.json'
    report.write_text(json.dumps(dict(table='raw_tushare.anns_d',database=header['scope']['database'],start_id=1,end_id=3,
        backup_path=str(backup),backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),restore_verified_at=datetime.now(timezone.utc).isoformat())))
    runner.run(mode='APPLY',start_id=1,end_id=3,state_path=state,recovery_report_path=report,expected_state_digest=header['state_digest'])
    assert len(stored(engine))==3


def test_postgres_draft_cancel_not_executable_and_frozen_tampering_rejected(engine,tmp_path):
    seed(engine,501)
    runner=AnnouncementIdentityMigration(engine);state=tmp_path/'state'
    canceled=False
    def progress(value):
        nonlocal canceled
        if value.get('checked_rows')==500:canceled=True
    with pytest.raises(IngestionCanceledError):runner.run(mode='CHECK',start_id=1,end_id=501,state_path=state,cancel=lambda:canceled,progress=progress)
    assert not state.exists() and json.loads((tmp_path/'state.draft').read_text())['frozen'] is False
    header=runner.run(mode='CHECK',start_id=1,end_id=501,state_path=state)
    data=json.loads(state.read_text());data['count']=1;state.write_text(json.dumps(data))
    with pytest.raises(AnnouncementPersistenceError,match='摘要'):
        runner.run(mode='APPLY',start_id=1,end_id=501,state_path=state,expected_state_digest=header['state_digest'])
    assert all(r['group_key'] is None for r in stored(engine))


def test_remote_database_connection_rejected_before_business_read():
    engine=create_engine('postgresql+psycopg://example.invalid/db')
    with pytest.raises(AnnouncementPersistenceError,match='本机连接'):
        AnnouncementIdentityMigration(engine).run(mode='CHECK',start_id=1,end_id=1,state_path='/private/tmp/never-created-anns-state')
    engine.dispose()


def test_metadata_input_memory_is_bounded(tmp_path):
    path=tmp_path/'large-report';path.write_bytes(b'x'*(16*1024+1))
    with pytest.raises(AnnouncementPersistenceError,match='16KiB'):read_metadata(path)
