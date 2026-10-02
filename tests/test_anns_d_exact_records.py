"""Lossless source retention and bounded exact-duplicate insertion acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.foundation.dao.anns_d_dao import AnnsDDAO
from src.foundation.datasets.anns_d_contracts import AnnouncementPersistenceError, identity
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from tests.test_anns_d_stream import engine, raw, fake_source, run, action, counts
from src.foundation.ingestion.resolver import DatasetActionResolver
from unittest.mock import Mock


def normalize(rows):
    return DatasetNormalizer().normalize(definition=get_dataset_definition('anns_d'),
        fetch_result=SourceFetchResult(unit_id='exact', rows_raw=rows, request_count=1, retry_count=0, latency_ms=0))


def insert(session, rows):
    return AnnsDDAO(session).insert_ignore(rows, batch_rows=500, statement_timeout_seconds=25, lock_timeout_seconds=5)


def readback(engine):
    with engine.connect() as connection:
        return list(connection.execute(select(RawAnnsD.__table__).order_by(RawAnnsD.id)).mappings())


@pytest.mark.parametrize('field,value',[
    ('ann_date','2026-01-01'), ('ts_code','155162.sh'), ('name','债券 '),
    ('title','公告1 '), ('url',None), ('url',''), ('url',' https://example.org/1.pdf'),
    ('rec_time',''), ('rec_time','2026-01-01 09:00:00'), ('extra_field','source extension'),
])
def test_every_source_difference_has_distinct_identity(field,value):
    base=raw(1)
    variant={**base,field:value}
    batch=normalize([base,variant])
    assert batch.rows_rejected==0 and len(batch.rows_normalized)==2
    assert batch.rows_normalized[0]['row_key_hash']!=batch.rows_normalized[1]['row_key_hash']
    assert [json.loads(row['raw_payload']) for row in batch.rows_normalized]==[base,variant]


def test_original_time_text_not_normalized_for_equality():
    a={**raw(1),'rec_time':'2026-01-01 09:00:00+08:00'}
    b={**a,'rec_time':'2026-01-01 01:00:00+00:00'}
    rows=normalize([a,b]).rows_normalized
    assert rows[0]['rec_time']==rows[1]['rec_time']
    assert rows[0]['row_key_hash']!=rows[1]['row_key_hash']


def test_source_object_order_does_not_change_identity():
    a=raw(1); b=dict(reversed(list(a.items())))
    rows=normalize([a,b]).rows_normalized
    assert rows[0]['row_key_hash']==rows[1]['row_key_hash']


@pytest.mark.parametrize('source',[{}, {'ann_date':'invalid','ts_code':None,'title':None},
    {**raw(1),'name':'x'*129,'ts_code':'x'*33,'title':'a\x00b','rec_time':'invalid','url':'not a URL'}])
def test_missing_or_unprojectable_source_is_saved(engine,source):
    batch=normalize([source])
    assert batch.rows_rejected==0 and len(batch.rows_normalized)==1
    with Session(engine) as session:
        result=insert(session,batch.rows_normalized);session.commit()
    assert result.inserted==1
    assert json.loads(readback(engine)[0]['raw_payload'])==source


def test_invalid_non_json_source_stops_batch_instead_of_rejecting_or_collapsing():
    with pytest.raises(IngestionError) as error:
        normalize([raw(1),{**raw(2),'url':float('nan')}])
    assert error.value.structured_error.error_code=='anns_d.source_payload_invalid'


def test_exact_duplicates_ignore_local_metadata_and_keep_first_row(engine):
    a=normalize([raw(1)]).rows_normalized[0]
    with Session(engine) as session:
        first=insert(session,[a,a]);session.commit()
    saved=readback(engine)[0]
    b={**a,'fetched_at':datetime(2000,1,1,tzinfo=timezone.utc),'api_name':'local metadata'}
    with Session(engine) as session:
        replay=insert(session,[b]);session.commit()
    assert (first.processed,first.inserted,first.identical)==(2,1,1)
    assert (replay.processed,replay.inserted,replay.identical)==(1,0,1)
    assert dict(readback(engine)[0])==dict(saved)


def test_partials_and_distinct_variants_are_never_replaced(engine):
    sources=[{**raw(1),'url':None},raw(1),{**raw(1),'name':'另一个名称'},
             {**raw(1),'title':'公告1 '},{**raw(1),'extra':'extension'}]
    for source in sources+list(reversed(sources)):
        with Session(engine) as session:
            insert(session,normalize([source]).rows_normalized);session.commit()
    saved=readback(engine)
    assert len(saved)==len(sources)
    assert [json.loads(row['raw_payload']) for row in saved]==sources


def test_duplicate_across_page_boundary_has_exact_counts(engine,monkeypatch):
    sources=[raw(i) for i in range(2000)]+[raw(0),raw(2000)]
    calls=fake_source(monkeypatch,sources)
    result=run(engine,DatasetActionResolver(Mock()).build_plan(action()))
    assert result.rows_fetched==2002 and result.rows_committed==2002 and result.rows_rejected==0
    assert result.rows_deduplicated==1 and counts(engine)==(2001,1)
    assert [call['offset'] for call in calls]==[0,2000]


def test_concurrent_exact_inserts_keep_one_copy(engine):
    gate=Barrier(2)
    rows=normalize([raw(1),raw(2)]).rows_normalized
    def work(reverse):
        with Session(engine) as session:
            gate.wait(timeout=5)
            result=insert(session,list(reversed(rows)) if reverse else rows)
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(work,value) for value in (False,True)]
        results=[f.result(timeout=10) for f in futures]
    assert sum(r.inserted for r in results)==2 and sum(r.identical for r in results)==2
    assert len(readback(engine))==2


def test_hash_collision_rolls_back_new_additions(engine,monkeypatch):
    old=normalize([raw(1)]).rows_normalized[0]
    with Session(engine) as session:
        insert(session,[old]);session.commit()
    new=normalize([raw(2)]).rows_normalized[0]
    collision={**normalize([raw(3)]).rows_normalized[0],'row_key_hash':old['row_key_hash']}
    real_identity=identity
    monkeypatch.setattr('src.foundation.dao.anns_d_dao.identity',lambda payload:
        old['row_key_hash'] if json.loads(payload)['title']=='公告3' else real_identity(payload))
    with Session(engine) as session:
        with pytest.raises(AnnouncementPersistenceError,match='不同公告源载荷'):
            insert(session,[new,collision])
        session.commit()  # Savepoint must have removed every attempted addition.
    assert len(readback(engine))==1


def migration():
    spec=importlib.util.spec_from_file_location('exact_migration','alembic/versions/20261002_000183_anns_d_exact_source_records.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.down_revision=='20261002_000182'
    return module


def old_schema(connection):
    # ALTER only in a fresh task-owned database; no shared/production resources.
    connection.execute(text('ALTER TABLE raw_tushare.anns_d ADD COLUMN group_key VARCHAR(64)'))
    connection.execute(text('CREATE INDEX idx_raw_tushare_anns_d_group_key ON raw_tushare.anns_d(group_key)'))
    connection.execute(text('ALTER TABLE raw_tushare.anns_d ALTER COLUMN raw_payload DROP NOT NULL'))
    for field in ('ann_date','ts_code','title'):
        connection.execute(text(f'ALTER TABLE raw_tushare.anns_d ALTER COLUMN {field} SET NOT NULL'))
    connection.execute(text('CREATE SCHEMA core_serving_light'))
    connection.execute(text('CREATE VIEW core_serving_light.anns_d AS SELECT row_key_hash,ann_date,ts_code,name,title,url,rec_time,fetched_at FROM raw_tushare.anns_d'))


def test_schema_upgrade_empty_table_preserves_view_and_indexes(engine):
    with engine.begin() as connection:
        old_schema(connection)
        with Operations.context(MigrationContext.configure(connection)):migration().upgrade()
        assert connection.execute(text("SELECT to_regclass('raw_tushare.uq_raw_tushare_anns_d_row_key_hash')")).scalar()
        assert connection.execute(text("SELECT to_regclass('core_serving_light.anns_d')")).scalar()
    with Session(engine) as session:
        AnnsDDAO(session).require_storage_ready()
        insert(session,normalize([{}]).rows_normalized);session.commit()


def test_schema_upgrade_never_deletes_existing_business_rows(engine):
    with Session(engine) as session:
        insert(session,normalize([raw(1)]).rows_normalized);session.commit()
    with engine.begin() as connection:old_schema(connection)
    with pytest.raises(Exception,match='must be empty'):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):migration().upgrade()
    assert len(readback(engine))==1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT attname FROM pg_attribute WHERE attrelid='raw_tushare.anns_d'::regclass AND attname='group_key' AND NOT attisdropped")).scalar()=='group_key'


def test_actual_process_exit_keeps_commits_and_can_resume(engine,monkeypatch):
    import os
    import subprocess
    import sys
    plan=DatasetActionResolver(Mock()).build_plan(action())
    code='''import json, os
from unittest.mock import Mock
from sqlalchemy import create_engine
from src.foundation.ingestion.resolver import DatasetActionResolver
from tests.test_anns_d_stream import raw, action, run
import src.foundation.ingestion.source_client as client
rows=[raw(i) for i in range(2001)]
class Connector:
    def call_bounded(self, **kwargs):
        kwargs['check'](); kwargs['before_request']()
        params=kwargs['params']
        return rows[params['offset']:params['offset']+params['limit']]
client.create_source_connector=lambda key:Connector()
plan=DatasetActionResolver(Mock()).build_plan(action(json.loads(os.environ['ANNS_EXACT_EXECUTION'])))
def progress(snapshot,message):
    if snapshot.rows_committed==500: os._exit(17)
run(create_engine(os.environ['ANNS_EXACT_DATABASE']),plan,progress_reporter=progress)
'''
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,
        'ANNS_EXACT_DATABASE':engine.url.render_as_string(hide_password=False),
        'ANNS_EXACT_EXECUTION':json.dumps(plan.execution_context)},capture_output=True,timeout=20)
    assert result.returncode==17,result.stderr.decode()
    assert counts(engine)==(500,0)
    fake_source(monkeypatch,[raw(i) for i in range(2001)])
    result=run(engine,plan)
    assert result.rows_committed==2001 and result.rows_deduplicated==500
    assert counts(engine)==(2001,1)


def test_live_source_sample_normalize_insert_replay_readback(engine):
    import os
    from pathlib import Path
    path=os.environ.get('ANNS_EXACT_SOURCE_SAMPLE')
    if not path:pytest.skip('fresh tushareMcp sample not supplied')
    source=json.loads(Path(path).read_text())
    assert len(source)==2 and {row['url'] is None for row in source}=={True,False}
    batch=normalize(source)
    assert batch.rows_rejected==0 and len(batch.rows_normalized)==2
    with Session(engine) as session:
        first=insert(session,batch.rows_normalized);session.commit()
        replay=insert(session,batch.rows_normalized);session.commit()
    actual=[json.loads(row['raw_payload']) for row in readback(engine)]
    assert {json.dumps(row,sort_keys=True) for row in actual}=={json.dumps(row,sort_keys=True) for row in source}
    assert (first.inserted,first.identical,replay.inserted,replay.identical)==(2,0,0,2)
    Path('/private/tmp/anns-exact-live-acceptance-20261002.json').write_text(json.dumps({
        'source_rows':len(source),'normalized_rows':len(batch.rows_normalized),'rejected_rows':batch.rows_rejected,
        'first_inserted':first.inserted,'replay_inserted':replay.inserted,'replay_identical':replay.identical,
        'physical_rows':len(actual)},ensure_ascii=False,indent=2))


@pytest.mark.parametrize('field',['insert_batch_rows','insert_statement_timeout_seconds','insert_lock_timeout_seconds'])
@pytest.mark.parametrize('value',[0,-1,None,True])
def test_insert_budgets_require_positive_integers(monkeypatch,field,value):
    from dataclasses import replace
    from src.foundation.ingestion.linter import lint_all_dataset_definitions
    definition=get_dataset_definition('anns_d')
    broken=replace(definition,storage=replace(definition.storage,**{field:value}))
    monkeypatch.setattr('src.foundation.ingestion.linter.list_dataset_definitions',lambda:[broken])
    assert any(issue.code=='insert_ignore_budget_invalid' for issue in lint_all_dataset_definitions().issues)


def test_superseded_execution_contract_cannot_resume():
    from copy import deepcopy
    frozen=DatasetActionResolver(Mock()).build_plan(action()).execution_context
    assert frozen['policy_snapshot']['identity_contract']=='exact_source_record_v1'
    old=deepcopy(frozen)
    old['policy_snapshot']['identity_contract']='information_dominance_v1'
    with pytest.raises(IngestionError,match='恢复范围'):
        DatasetActionResolver(Mock()).build_plan(action(old))


def test_bad_hash_stops_without_persisting_any_row(engine):
    rows=normalize([raw(1),raw(2)]).rows_normalized
    rows[1]['row_key_hash']='0'*64
    with Session(engine) as session:
        with pytest.raises(AnnouncementPersistenceError):insert(session,rows)
        session.commit()
    assert len(readback(engine))==0
