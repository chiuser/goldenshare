from __future__ import annotations

from datetime import date
from dataclasses import replace
from itertools import permutations
import json
import os
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import Session

from src.foundation.dao.anns_d_dao import AnnsDDAO
from src.foundation.datasets.anns_d_contracts import content, covers, identity, maximal
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.row_transforms import _anns_d_row_transform
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from src.scripts.plan_announcement_identity_migration import plan


def row(**kwargs):
    raw = dict(ann_date=date(2023, 6, 9), ts_code='155162.SH', name='19津投04',
               title='关于19津投04（155162）盘中临时停牌的公告', url=None, rec_time=None)
    raw.update(kwargs)
    return _anns_d_row_transform(raw)


def normalize(rows):
    return DatasetNormalizer().normalize(definition=get_dataset_definition('anns_d'),
        fetch_result=SourceFetchResult(unit_id='test',request_count=1,retry_count=0,latency_ms=1,rows_raw=rows))


@pytest.mark.parametrize('url,recorded', [(None,None),('',None),('http://x/a.pdf',None),(None,'bad-time')])
def test_optional_fields_are_preserved_with_quality(url, recorded):
    raw=dict(ann_date='20230609',ts_code='S1649.SZ',title='公告',url=url,rec_time=recorded)
    batch=normalize([raw])
    assert batch.rows_rejected==0
    assert batch.rows_normalized[0]['rec_time'] is None
    assert json.loads(batch.rows_normalized[0]['raw_payload'])==raw
    assert batch.quality_counts['quality.missing_rec_time']==1
    if recorded=='bad-time':
        assert batch.quality_counts['quality.invalid_rec_time']==1


@pytest.mark.parametrize('missing', ['ann_date','ts_code','title'])
def test_required_fields_still_rejected(missing):
    raw=dict(ann_date='20230609',ts_code='600000.SH',title='公告',url=None,rec_time=None)
    raw[missing]=None
    batch=normalize([raw])
    assert batch.rows_rejected==1
    assert not batch.rows_normalized


def test_optional_nonfinite_time_does_not_reject_source_row():
    batch = normalize([dict(ann_date='20230609', ts_code='S1649.SZ', title='公告',
                            url=None, rec_time=float('nan'))])
    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]['rec_time'] is None
    assert json.loads(batch.rows_normalized[0]['raw_payload'])['rec_time'] == 'nan'


@pytest.mark.parametrize('field,value', [
    ('reconciliation_batch_rows', 0),
    ('reconciliation_max_group_versions', -1),
    ('reconciliation_statement_timeout_seconds', None),
    ('reconciliation_lock_timeout_seconds', True),
])
def test_invalid_reconciliation_budgets_fail_definition_lint(monkeypatch, field, value):
    from src.foundation.ingestion import linter
    definition = get_dataset_definition('anns_d')
    changed = replace(definition, storage=replace(definition.storage, **{field: value}))
    definitions = linter.list_dataset_definitions()
    monkeypatch.setattr(linter, 'list_dataset_definitions',
                        lambda: [changed if x.dataset_key == 'anns_d' else x for x in definitions])
    assert any(x.code == 'reconciliation_budget_invalid' for x in linter.lint_all_dataset_definitions().issues)


def test_reconciliation_requires_original_payload(monkeypatch):
    from src.foundation.ingestion import linter
    definition = get_dataset_definition('anns_d')
    changed = replace(definition, normalization=replace(definition.normalization, preserve_raw_payload=False))
    definitions = linter.list_dataset_definitions()
    monkeypatch.setattr(linter, 'list_dataset_definitions',
                        lambda: [changed if x.dataset_key == 'anns_d' else x for x in definitions])
    assert any(x.code == 'reconciliation_storage_invalid' for x in linter.lint_all_dataset_definitions().issues)


def test_identity_includes_name_null_types_and_equivalent_timezones():
    assert identity(row(name='A'))!=identity(row(name='B'))
    assert identity(row(url=None))!=identity(row(url='null'))
    assert identity(row(rec_time='2023-06-09T08:00:00+08:00'))==identity(row(rec_time='2023-06-09T00:00:00+00:00'))
    assert not covers(row(ann_date=date(2023,6,10),url='U'),row())
    assert not covers(row(title='别的标题',url='U'),row())


def test_conservative_maxima_all_permutations_and_replay():
    rows=[row(),row(url='U'),row(rec_time='2023-06-09T08:00:00+08:00'),row(url='U',rec_time='2023-06-09T08:00:00+08:00'),row(url='V')]
    expected={content(x) for x in maximal(rows)}
    for sequence in permutations(rows):
        stored=[]
        for source in sequence+sequence:
            stored=maximal(stored+[source])
        assert {content(x) for x in stored}==expected
    complementary=[row(url='U'),row(rec_time='2023-06-09T08:00:00+08:00')]
    assert len(maximal(complementary))==2
    for changed in [row(url='V'),row(url='U',name='changed'),row(url='U',rec_time='2023-06-09T09:00:00+08:00')]:
        assert len(maximal([row(url='U',rec_time='2023-06-09T08:00:00+08:00'),changed]))==2


@pytest.fixture(scope='module')
def pg_engine():
    url=os.environ.get('ANNS_P1_TEST_DATABASE_URL')
    if not url:
        pytest.skip('isolated PostgreSQL fixture requires ANNS_P1_TEST_DATABASE_URL')
    # This integration fixture cannot point at a network/production database.
    assert '/private/tmp/anns-p1-pg-socket-' in url and 'host=' in url
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS raw_tushare'))
        RawAnnsD.__table__.create(conn,checkfirst=True)
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS core_serving_light'))
        conn.execute(text("""CREATE OR REPLACE VIEW core_serving_light.anns_d AS
            SELECT row_key_hash,ann_date,ts_code,name,title,url,rec_time,'tushare'::varchar AS source,fetched_at
            FROM raw_tushare.anns_d"""))
    yield engine
    engine.dispose()


@pytest.fixture
def session(pg_engine):
    with pg_engine.connect() as connection:
        tx=connection.begin()
        with Session(bind=connection,join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def apply(session, rows, **budgets):
    policy=get_dataset_definition('anns_d').storage
    return AnnsDDAO(session).reconcile(rows,batch_rows=budgets.get('batch_rows',policy.reconciliation_batch_rows),
        max_group_versions=budgets.get('max_group_versions',policy.reconciliation_max_group_versions),
        statement_timeout_seconds=policy.reconciliation_statement_timeout_seconds,
        lock_timeout_seconds=policy.reconciliation_lock_timeout_seconds)


def read(session):
    return list(session.execute(select(RawAnnsD.__table__).order_by(RawAnnsD.id)).mappings())


def test_postgres_cross_batch_physical_replacement_replay_and_identity(session):
    apply(session,[row()]); partial_id=read(session)[0]['id']
    result=apply(session,[row(url='U')]);session.commit()
    current=read(session)
    assert len(current)==1 and current[0]['url']=='U' and current[0]['id']!=partial_id
    assert result.deleted==1 and result.inserted==1
    survivor=current[0]['id']
    result=apply(session,[row(),row(url='U'),row(url='U')])
    assert result.covered==1 and result.identical==2 and result.inserted==0
    assert read(session)[0]['id']==survivor
    assert len(read(session))==1


def test_postgres_order_splits_and_non_stock_codes(session):
    # Distinct groups keep permutations independent inside this transactional fixture.
    originals=[dict(url=None,rec_time=None),dict(url='U',rec_time=None),dict(url='U',rec_time='2023-06-09T08:00:00+08:00')]
    for i, order in enumerate(permutations(originals)):
        for source in order:
            apply(session,[row(title=f'公告-{i}',ts_code='S1649.SZ',**source)])
        own=[x for x in read(session) if x['title']==f'公告-{i}']
        assert len(own)==1 and own[0]['url']=='U' and own[0]['rec_time'] is not None


def test_postgres_keeps_conflicts_and_never_synthesizes(session):
    apply(session,[row(url='U'),row(rec_time='2023-06-09T08:00:00+08:00')])
    assert len(read(session))==2
    apply(session,[row(url='U',rec_time='2023-06-09T08:00:00+08:00')])
    assert len(read(session))==1
    apply(session,[row(url='V'),row(url='U',name='不同名称'),row(url='U',rec_time='2023-06-09T09:00:00+08:00')])
    assert len(read(session))==4


def test_postgres_failure_after_delete_rolls_back_and_limits_prevent_delete(session,monkeypatch):
    apply(session,[row()]); before=read(session)[0]['id']
    execute=session.execute
    def failure(statement,*args,**kwargs):
        if getattr(statement,'is_insert',False):
            raise RuntimeError('injected insert failure')
        return execute(statement,*args,**kwargs)
    monkeypatch.setattr(session,'execute',failure)
    with pytest.raises(RuntimeError): apply(session,[row(url='U')])
    monkeypatch.setattr(session,'execute',execute)
    assert read(session)[0]['id']==before and read(session)[0]['url'] is None
    with pytest.raises(Exception,match='版本上限'):
        apply(session,[row(url='U'),row(url='V')],max_group_versions=1)
    assert len(read(session))==1


def test_postgres_hash_mismatch_rejected_without_write(session):
    bad=row(url='U');bad['row_key_hash']='0'*64
    with pytest.raises(Exception,match='身份'): apply(session,[bad])
    assert not read(session)


def test_writer_reports_no_quality_rejects_or_key_rejects(session):
    batch=normalize([dict(ann_date='20230609',ts_code='155162.SH',name='19津投04',title='公告',url=None,rec_time=None)]*2)
    result=DatasetWriter(session).write(definition=get_dataset_definition('anns_d'),batch=batch)
    assert result.rows_rejected==0 and result.rows_written==2
    counters=result.persistence_diagnostics['announcement_reconciliation']
    assert counters['inserted']==1 and counters['identical']==1
    assert counters['quality_counts']['quality.missing_url']==2
    assert len(read(session))==1


def test_offline_migration_plan_removes_duplicates_and_covered_payloads(tmp_path):
    records=[]
    for i, source in enumerate([row(),row(url='U'),row(url='U'),row(url='V')],1):
        records.append(dict(id=i,ann_date='2023-06-09',ts_code=source['ts_code'],name=source['name'],title=source['title'],url=source['url'],rec_time=None,row_key_hash=f'old-{i}'))
    path=tmp_path/'input.jsonl';path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records))
    output=tmp_path/'plan.sqlite';header=plan(path,output)
    assert (header['candidate_count'],header['keep_count'],header['delete_count'])==(4,2,2)
    with sqlite3.connect(output) as conn:
        assert conn.execute('SELECT action FROM candidates WHERE raw_id=1').fetchone()[0]=='delete_covered'
        assert conn.execute('SELECT action FROM candidates WHERE raw_id=3').fetchone()[0]=='delete_identical'
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='input_rows'").fetchone() is None
    with pytest.raises(FileExistsError): plan(path,output)


def test_invalid_url_is_a_quality_warning_not_a_rejection():
    batch=normalize([dict(ann_date='20230609',ts_code='155162.SH',title='公告',url='file:///tmp/a',rec_time=None)])
    assert batch.rows_rejected==0
    assert batch.rows_normalized[0]['url']=='file:///tmp/a'
    assert batch.quality_counts['quality.invalid_url']==1


def test_frozen_plan_detects_tampering(tmp_path):
    from src.scripts.plan_announcement_identity_migration import verify_plan
    original=dict(id=1,ann_date='2023-06-09',ts_code='155162.SH',title='公告',url=None,rec_time=None,row_key_hash='old')
    path=tmp_path/'input.jsonl';path.write_text(json.dumps(original)+'\n')
    output=tmp_path/'plan.sqlite';header=plan(path,output)
    assert verify_plan(output,expected_manifest_digest=header['manifest_digest'])==header
    with sqlite3.connect(output) as conn:
        conn.execute("UPDATE candidates SET old_hash='tampered'")
    with pytest.raises(ValueError,match='digest'):
        verify_plan(output,expected_manifest_digest=header['manifest_digest'])


def test_postgres_concurrent_writers_share_empty_group_lock(pg_engine):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    title='并发合并独立测试'
    locked=threading.Event(); contender=threading.Event()
    def first():
        with Session(pg_engine) as session:
            apply(session,[row(title=title)])
            locked.set()
            assert contender.wait(3)
            session.commit()
    def second():
        assert locked.wait(3)
        with Session(pg_engine) as session:
            contender.set()
            apply(session,[row(title=title,url='U')])
            session.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(first),pool.submit(second)]
            for future in futures: future.result(timeout=10)
        with Session(pg_engine) as session:
            rows=list(session.execute(select(RawAnnsD.__table__).where(RawAnnsD.title==title)).mappings())
            assert len(rows)==1 and rows[0]['url']=='U'
    finally:
        # Only fixture-owned rows in the explicit /private/tmp cluster are removed.
        from sqlalchemy import delete
        with pg_engine.begin() as connection:
            connection.execute(delete(RawAnnsD).where(RawAnnsD.title==title))


def test_real_expand_migration_and_not_ready_guard(pg_engine):
    import importlib.util
    import uuid
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    name='anns_p1_expand_'+uuid.uuid4().hex[:12]
    with pg_engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.execute(text(f'CREATE DATABASE {name}'))
    isolated=create_engine(pg_engine.url.set(database=name))
    try:
        with isolated.begin() as conn:
            conn.execute(text('CREATE SCHEMA raw_tushare'))
            conn.execute(text('''CREATE TABLE raw_tushare.anns_d(
                id BIGSERIAL PRIMARY KEY, ann_date DATE NOT NULL, ts_code VARCHAR(32) NOT NULL,
                name VARCHAR(128),title TEXT NOT NULL,url TEXT NOT NULL,rec_time TIMESTAMPTZ NOT NULL,
                row_key_hash VARCHAR(64) NOT NULL UNIQUE,api_name VARCHAR(32) DEFAULT 'anns_d' NOT NULL,
                fetched_at TIMESTAMPTZ DEFAULT now() NOT NULL,raw_payload TEXT)'''))
            path=Path('alembic/versions/20261002_000181_prepare_anns_d_reconciliation.py')
            spec=importlib.util.spec_from_file_location('anns_expand',path)
            migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            assert migration.down_revision=='20260916_000180'
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            assert conn.execute(text("SELECT attnotnull FROM pg_attribute WHERE attrelid='raw_tushare.anns_d'::regclass AND attname='url'")).scalar() is False
            assert conn.execute(text("SELECT attnotnull FROM pg_attribute WHERE attrelid='raw_tushare.anns_d'::regclass AND attname='rec_time'")).scalar() is False
            assert conn.execute(text("SELECT to_regclass('raw_tushare.anns_d_identity_migration')")).scalar() is not None
        with Session(isolated) as session:
            with pytest.raises(Exception,match='身份迁移未完成'):
                apply(session,[row(url='U')])
            assert not read(session)
        with pytest.raises(RuntimeError,match='禁止自动降级'):
            migration.downgrade()
    finally:
        isolated.dispose()
    # Database is disposable task-local evidence. Cluster stops after all tests.



def test_real_tushare_sample_end_to_end_in_isolated_postgres(session):
    # Exact two rows re-verified via tushareMcp on 2026-10-02 for this P1 run.
    rows=[dict(ann_date='20230609',ts_code='155162.SH',name='19津投04',
               title='关于19津投04（155162）盘中临时停牌的公告',url=url,rec_time=None)
          for url in (None,'http://dataclouds.cninfo.com.cn/sjother/regulatory_announcement/sse/7d5d3210069711eeb155fa163ebe0297.pdf')]
    batch=normalize(rows)
    assert len(batch.rows_normalized)==2 and batch.rows_rejected==0
    result=DatasetWriter(session).write(definition=get_dataset_definition('anns_d'),batch=batch)
    session.commit()
    physical=read(session)
    serving=list(session.execute(text('SELECT title,url,rec_time FROM core_serving_light.anns_d')).mappings())
    assert len(physical)==len(serving)==1 and physical[0]['url']==rows[1]['url']
    assert physical[0]['rec_time'] is None
    assert json.loads(physical[0]['raw_payload'])==rows[1]
    counters=result.persistence_diagnostics['announcement_reconciliation']
    assert (counters['processed'],counters['inserted'],counters['covered'],counters['identical'])==(2,1,1,0)
