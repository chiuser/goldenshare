"""Temporary Parquet, SQLite and archive files; no formal writes or HTTP."""
import json
import os
import time
from datetime import date,datetime,timezone
from dataclasses import replace
from pathlib import Path

import pytest

from test_announcement_download_cli import archive,row as legacy_row,run
from test_announcement_download_dg import write_day,raw_root,make_source
from src.foundation.clients.announcement_archive.core import ANNOUNCEMENT_FIELDS,Blocked,Control,identity
from src.foundation.clients.announcement_archive.names import NameInitials,NameSnapshot
from src.foundation.clients.announcement_archive.presence import ArchivePresence
from src.foundation.clients.announcement_archive.source import Source
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.dao.announcement_archive.catalog import Catalog
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.ops.runtime.announcement_archive.catalog_builder import CatalogBuilder
from src.biz.schemas.wealth.data_center.announcements import AnnouncementQueryRequest
from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
from src.biz.services.wealth.data_center.errors import DataCenterError


def row(*args,**kwargs):
    extra={k:kwargs.pop(k) for k in ('name','rec_time','ts_code') if k in kwargs}
    result=legacy_row(*args,**kwargs)
    result.update(extra)
    return result


@pytest.fixture
def query_archive(archive,tmp_path):
    raw_root(archive).mkdir(parents=True,exist_ok=True)
    source=make_source(archive,policy=replace(archive[3],batch_size=500))
    names_root=raw_root(archive).parent
    import duckdb
    for kind,columns,rows in [
        ('stock_basic',('ts_code','name','cnspell'),[
            ('000001.SZ','平安银行','PAYH'),('600036.SH','招商银行','ZSYH'),
            ('600000.SH','浦发银行','PFYH'),('000002.SZ','退市样本','TSYB')]),
        ('namechange',('ts_code','name'),[('000001.SZ','深发展A'),('000002.SZ','旧简称')])]:
        path=names_root/kind/'full/part-000.parquet';path.parent.mkdir(parents=True,exist_ok=True)
        with duckdb.connect(':memory:') as conn:
            conn.execute('CREATE TABLE n('+','.join(c+' VARCHAR' for c in columns)+')')
            conn.executemany('INSERT INTO n VALUES('+','.join('?' for c in columns)+')',rows)
            conn.execute('COPY n TO ? (FORMAT PARQUET)',[str(path)])
    volume=SourceVolume(names_root,source.policy,archive[0].inspector)
    names_source=Source(source.options,source.policy,source.control,volume).open()
    catalog=Catalog(tmp_path/'catalog/catalog.sqlite',source.scope)
    with catalog.connection(write=True,initialize=True):pass
    builder=CatalogBuilder(catalog,source,names_source,NameInitials())
    presence=ArchivePresence(archive[0],archive[1].path if hasattr(archive[1],'path') else tmp_path/'local-state/downloads.sqlite',archive[0].relative_root)
    service=AnnouncementQueryService(catalog,builder,presence)
    yield service,archive,source
    builder.close()


def request(**kw):
    return AnnouncementQueryRequest(startDate='2026-09-30',endDate='2026-09-30',**kw)


def execute(service,**kw):
    pending,status=service.create(request(**kw))
    assert status==202 and pending['total'] is None
    assert service.prepare_next()
    return service.read(pending['queryId'])[0]


def assert_failed_query(service,query_id,code):
    from src.biz.schemas.wealth.data_center.announcements import QueryResultDto
    result,status=service.read(query_id)
    QueryResultDto.model_validate(result)
    assert status==200 and result['pageState']['status']=='error'
    assert result['pageState']['code']==code
    assert result['total'] is None and result['items']==[]
    assert not result['downloadStatusAvailable'] and result['preparation'] is None
    return result


def test_six_fields_records_nulls_and_one_file(query_archive):
    service,archive,_=query_archive
    original=row();changed=dict(original,name='历史公告名',rec_time=None)
    missing=dict(original,url=None,title=None);empty=dict(original,url='',name=None)
    write_day(raw_root(archive),'2026-09-30',[original,changed,missing,empty])
    result=execute(service)
    assert result['total']==4 and len(result['items'])==4
    assert len({r['recordKey'] for r in result['items']})==4
    assert {r['companyName'] for r in result['items']}=={'浦发银行'}
    assert sum(r['sourceUrl'] is None for r in result['items'])==2
    assert all(r['downloadStatus']=='undownloaded' for r in result['items'])
    with service.catalog.connection() as conn:
        rows=conn.execute('SELECT * FROM catalog_records').fetchall()
        assert len({r['artifact_key'] for r in rows if r['artifact_key']})==1
        assert any(r['rec_time'] is None for r in rows)
        assert any(r['url']=='' for r in rows)


def test_names_codes_aliases_initials_and_unknown_name(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row(ts_code='155162.SH',name='重庆银行'),row(2,ts_code='919999.BJ',name=None)])
    execute(service)
    for keyword,code,kind in [('payh','000001.SZ','initials'),('平安','000001.SZ','name'),
                              ('SFZA','000001.SZ','alias'),('旧简称','000002.SZ','alias'),
                              ('155','155162.SH','codePrefix'),('CQYH','155162.SH','initials'),
                              ('919999','919999.BJ','exactCode')]:
        result,status=service.companies(keyword,request())
        assert status==200 and result['items'][0]['tsCode']==code
        assert result['items'][0]['matchKind']==kind
    alias,_=service.companies('SFZA',request())
    assert alias['items'][0]['matchedAlias']=='深发展A'
    assert alias['items'][0]['name']=='平安银行'
    assert service.companies('退市样本',request())[0]['items'][0]['tsCode']=='000002.SZ'
    assert service.companies('%_',request())[0]['items']==[]


def test_initials_normalization_dictionary_source_priority(tmp_path):
    convert=NameInitials()
    assert [convert(s) for s in ['平安银行','招商银行','深发展A','重庆银行','ST平安银行']]==['PAYH','ZSYH','SFZA','CQYH','STPAYH']
    assert convert('重-庆 银行','155162.SH','rawSpell')=='RAWSPELL'
    assert convert('ＳＴ平安银行')=='PAYH' # Non-ASCII symbols are excluded, not transliterated.
    path=tmp_path/'names.json';path.write_text(json.dumps({'version':2,'overrides':[{'name':'重庆银行','tsCode':'1.SH','initials':'TEST'}]}))
    changed=NameInitials(path)
    assert changed('重庆银行','1.SH')=='TEST' and changed.version!=convert.version


def test_status_filters_whole_scope_then_page_deletion_recheck(query_archive):
    service,archive,_=query_archive
    rows=[row(i,title='公告'+str(i)) for i in range(1,123)]
    write_day(raw_root(archive),'2026-09-30',rows)
    # Only a late result is downloaded, outside the first 50 source records.
    run(archive,[rows[-1]])
    filtered=execute(service,downloadStatus='downloaded')
    assert filtered['total']==1 and filtered['items'][0]['title']=='公告122'
    remaining=execute(service,downloadStatus='undownloaded')
    assert remaining['total']==121 and len(remaining['items'])==50 and remaining['hasNext']
    all_rows=execute(service)
    second=service.read(all_rows['queryId'],2)[0]
    assert not {r['recordKey'] for r in all_rows['items']} & {r['recordKey'] for r in second['items']}
    task=archive[1].conn.execute("SELECT * FROM artifacts WHERE state='succeeded'").fetchone()
    (archive[0].output/task['relative_path']).unlink()
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):
        service.read(filtered['queryId'])
    again=execute(service,downloadStatus='downloaded')
    assert again['total']==0 and again['pageState']['status']=='empty'
    assert service.presence.stat_count>0


def test_literal_title_stable_order_unknown_status(query_archive,monkeypatch):
    service,archive,_=query_archive
    rows=[row(1,title='A%_B',name=None,ts_code=None),row(2,title='AxxB'),row(3,title='A%_B')]
    write_day(raw_root(archive),'2026-09-30',rows)
    result=execute(service,titleKeyword='%_')
    assert result['total']==2 and result['items'][-1]['tsCode'] is None
    assert result['items'][-1]['companyName']=='—'
    monkeypatch.setattr(service.presence,'check',lambda _:(_ for _ in ()).throw(Blocked('archive_presence_unavailable')))
    unavailable=service.read(result['queryId'])[0]
    assert not unavailable['downloadStatusAvailable']
    assert all(r['downloadStatus'] is None for r in unavailable['items'])
    pending,_=service.create(request(downloadStatus='undownloaded'));service.prepare_next()
    assert_failed_query(service,pending['queryId'],'DC_STATUS_UNAVAILABLE')


def test_atomic_publish_failures_duplicate_and_source_change(query_archive,monkeypatch,tmp_path):
    service,archive,_=query_archive
    original=[row(1),row(2)]
    path=write_day(raw_root(archive),'2026-09-30',original)
    first=execute(service);old=service.catalog.day('2026-09-30')
    replacement=write_day(tmp_path/'replacement','2026-09-30',[row(3),row(3)])
    os.replace(replacement,path)
    pending,_=service.create(request());service.prepare_next()
    assert_failed_query(service,pending['queryId'],'DC_SOURCE_CONTRACT_MISMATCH')
    assert service.catalog.day('2026-09-30')['active_generation']==old['active_generation']
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):service.read(first['queryId'])
    replacement=write_day(tmp_path/'replacement2','2026-09-30',[row(4)])
    os.replace(replacement,path)
    result=execute(service)
    assert result['total']==1 and service.catalog.meta()['revision']>first['catalogRevision']


def test_missing_day_not_empty_but_complete_zero_day_is(query_archive):
    service,archive,_=query_archive
    pending,_=service.create(request());service.prepare_next()
    failed=assert_failed_query(service,pending['queryId'],'DC_SOURCE_UNAVAILABLE')
    assert '2026-09-30' in failed['pageState']['message']
    write_day(raw_root(archive),'2026-09-30',[])
    assert not service.prepare_next()
    assert service.read(pending['queryId'])[0]==failed
    fresh=execute(service)
    assert fresh['queryId']!=pending['queryId'] and fresh['pageState']['status']=='empty'


def test_dictionary_version_rebuild_and_query_ttl(query_archive,tmp_path):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row(1,name='重庆银行',ts_code='155162.SH')])
    first=execute(service)
    path=tmp_path/'dictionary.json';path.write_text(json.dumps({'version':2,'overrides':[{'name':'重庆银行','initials':'NEW'}]}))
    service.builder.initials=NameInitials(path)
    result=execute(service)
    candidates,_=service.companies('NEW',request())
    assert candidates['items'][0]['tsCode']=='155162.SH'
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):service.read(first['queryId'])
    with service.catalog.connection(write=True) as conn:
        conn.execute('UPDATE query_snapshots SET expires_at=0 WHERE query_id=?',(result['queryId'],))
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):service.read(result['queryId'])


def test_schema_permissions_default_dates_and_no_mutation(query_archive):
    service,archive,_=query_archive
    catalog=service.catalog
    assert catalog.path.stat().st_mode & 0o777==0o600
    assert catalog.path.parent.stat().st_mode & 0o777==0o700
    before=archive[1].conn.execute('SELECT * FROM archive').fetchall()
    with catalog.connection() as conn:
        with pytest.raises(Exception):conn.execute('DELETE FROM catalog_meta')
    now=datetime(2026,9,30,16,1,tzinfo=timezone.utc)
    conditions=service.conditions(AnnouncementQueryRequest(),now)
    assert conditions['startDate']=='2026-09-02' and conditions['endDate']=='2026-10-01'
    assert archive[1].conn.execute('SELECT * FROM archive').fetchall()==before
    with catalog.connection(write=True) as conn:conn.execute('ALTER TABLE catalog_meta ADD COLUMN rogue TEXT')
    with pytest.raises(Blocked,match='catalog_schema_invalid'):
        with catalog.connection(write=True,initialize=True):pass


def test_inplace_change_stop_and_restart_unpublished_generation(query_archive,tmp_path,monkeypatch):
    service,archive,source=query_archive
    path=write_day(raw_root(archive),'2026-09-30',[row(1)])
    result=execute(service);old=service.catalog.day('2026-09-30')
    # Touching the same inode is forbidden, rather than treating it as a DG atomic publication.
    os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1_000_000))
    pending,_=service.create(request());service.prepare_next()
    assert_failed_query(service,pending['queryId'],'DC_SOURCE_CONTRACT_MISMATCH')
    assert service.catalog.day('2026-09-30')['active_generation']==old['active_generation']
    replacement=write_day(tmp_path/'new','2026-09-30',[row(i) for i in range(1,1101)])
    os.replace(replacement,path)
    original=service.catalog.add_records
    def stop_after_commit(*args):
        original(*args);source.control.stop.set()
    monkeypatch.setattr(service.catalog,'add_records',stop_after_commit)
    pending,_=service.create(request());service.prepare_next()
    assert service.catalog.query(pending['queryId'])['state']=='error'
    assert service.catalog.day('2026-09-30')['active_generation']==old['active_generation']
    source.control.stop.clear();monkeypatch.setattr(service.catalog,'add_records',original)
    restored=execute(service)
    assert restored['total']==1100
    with service.catalog.connection() as conn:
        # An incomplete generation remains evidence/cache, never participates in the published count.
        assert conn.execute('SELECT COUNT(DISTINCT generation) FROM catalog_records').fetchone()[0]>=3


def test_presence_never_hashes_untracked_files_are_not_downloaded(query_archive,monkeypatch):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row()])
    from src.foundation.clients.announcement_archive.files import Files
    monkeypatch.setattr(Files,'fingerprint',lambda *_:(_ for _ in ()).throw(AssertionError('query must not hash')))
    stray=archive[0].output/'untracked.pdf';stray.write_bytes(b'%PDF-1.7')
    result=execute(service)
    assert result['items'][0]['downloadStatus']=='undownloaded'
    with service.catalog.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM catalog_builds').fetchone()[0]==1


def test_same_artifact_all_rows_share_status_and_no_ledger_write(query_archive):
    service,archive,_=query_archive
    first=row();second=dict(first,title='不同标题',name=None,rec_time=None)
    write_day(raw_root(archive),'2026-09-30',[first,second])
    run(archive,[first])
    before=archive[1].conn.execute('SELECT * FROM artifacts').fetchall()
    result=execute(service,downloadStatus='downloaded')
    assert result['total']==2
    assert all(r['downloadStatus']=='downloaded' for r in result['items'])
    assert archive[1].conn.execute('SELECT * FROM artifacts').fetchall()==before


def test_missing_names_do_not_fallback_and_volume_errors_are_unknown(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row()])
    namepath=raw_root(archive).parent/'namechange/full/part-000.parquet'
    namepath.unlink()
    pending,_=service.create(request());service.prepare_next()
    failed=assert_failed_query(service,pending['queryId'],'DC_SOURCE_UNAVAILABLE')
    assert failed['pageState']['message']=='所需本地公告数据尚不可读取'
    assert service.catalog.meta()['name_generation'] is None


@pytest.mark.parametrize('suffix',['20260930','2026-02-30','/private/tmp/secret','2026-09-30:secret'])
def test_missing_day_message_does_not_expose_invalid_private_reason(suffix):
    from src.biz.services.wealth.data_center.errors import mapped_error
    error=mapped_error('source_day_missing:'+suffix)
    assert error.code=='DC_SOURCE_UNAVAILABLE'
    assert error.message=='所需本地公告数据尚不可读取'


def test_catalog_writer_contention_is_pending(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row()])
    from src.foundation.clients.announcement_archive.locking import ExecutionLock
    lock=ExecutionLock(service.catalog.path.parent/'catalog-writer.lock').open()
    try:
        pending,_=service.create(request())
        assert service.prepare_next() is False
        assert service.read(pending['queryId'])[1]==202
    finally:lock.close()
    assert service.prepare_next()
    assert service.read(pending['queryId'])[0]['total']==1


def test_day_soft_budget_and_sql_deadline_are_errors_not_truncated(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row(i) for i in range(1,1101)])
    service.builder.policy=replace(service.builder.policy,catalog_unit_seconds=0)
    pending,_=service.create(request());service.prepare_next()
    assert_failed_query(service,pending['queryId'],'DC_INDEX_FAILED')
    assert service.catalog.day('2026-09-30') is None
    service.builder.policy=DataCenterPolicy()
    assert execute(service)['total']==1100
    service.catalog.policy=replace(service.catalog.policy,sql_seconds=.00001)
    with pytest.raises(Blocked):
        with service.catalog.connection() as conn:
            conn.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000) SELECT SUM(x) FROM n').fetchone()


def test_name_snapshot_fixed_contract_from_current_dg_paths():
    import ast
    path=Path(__file__).parents[1]/'lake_console/orchestrator/src/orchestrator/defs/paths.py'
    parsed=ast.parse(path.read_text())
    for symbol,kind in [('raw_stock_basic_path','stock_basic'),('raw_namechange_path','namechange')]:
        fn=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name==symbol)
        call=fn.body[0].value
        assert [ast.literal_eval(v) for v in call.args[2:]]==['tushare',kind,'full','part-000.parquet']


def test_source_scope_change_invalidates_old_query_id(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row()])
    result=execute(service)
    old_scope=service.catalog.scope;service.catalog.scope='changed-volume'
    # The id carries the source scope, so remounting a different volume cannot retrieve an unrelated query.
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):
        # Use another temporary schema with the new identity, not a mutation of the old DB.
        old=service.catalog;new=Catalog(old.path.parent/'different.sqlite','changed-volume')
        with new.connection(write=True,initialize=True):pass
        service.catalog=new
        try:service.read(result['queryId'])
        finally:service.catalog=old;old.scope=old_scope


def test_name_snapshot_mutation_rejected_and_dictionary_file_hot_change(query_archive,tmp_path):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row(1,ts_code='155162.SH',name='重庆银行')])
    dictionary=tmp_path/'dictionary.json'
    dictionary.write_text(json.dumps({'version':1,'overrides':[]}))
    service.builder.initials=NameInitials(dictionary)
    first=execute(service)
    dictionary.write_text(json.dumps({'version':2,'overrides':[{'name':'重庆银行','initials':'NEW'}]}))
    changed=execute(service)
    assert service.companies('NEW',request())[0]['items'][0]['tsCode']=='155162.SH'
    path=raw_root(archive).parent/'stock_basic/full/part-000.parquet'
    os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1_000_000))
    pending,_=service.create(request());service.prepare_next()
    assert_failed_query(service,pending['queryId'],'DC_SOURCE_CONTRACT_MISMATCH')


def test_large_day_true_source_projection_bounded_batches(query_archive,monkeypatch):
    service,archive,_=query_archive
    rows=[row(i,title='large sample '+str(i)) for i in range(1,50001)]
    write_day(raw_root(archive),'2026-09-30',rows)
    sizes=[];original=service.catalog.add_records
    def observe(day,generation,values,names):
        sizes.append(len(values));return original(day,generation,values,names)
    monkeypatch.setattr(service.catalog,'add_records',observe)
    started=time.monotonic();result=execute(service)
    assert result['total']==50000 and len(result['items'])==50
    assert max(sizes)==500 and len(sizes)==100
    assert time.monotonic()-started<service.builder.policy.catalog_unit_seconds
    second=service.read(result['queryId'],1000)[0]
    assert len(second['items'])==50 and not second['hasNext']


def test_ready_counts_corruption_is_not_empty_and_pending_ttl_not_consumed(query_archive):
    service,archive,_=query_archive
    write_day(raw_root(archive),'2026-09-30',[row()])
    pending,_=service.create(request())
    snapshot=service.catalog.query(pending['queryId'])
    assert snapshot['expires_at'] is None
    assert service.read(pending['queryId'])[1]==202
    service.prepare_next();result,_=service.read(pending['queryId'])
    snapshot=service.catalog.query(pending['queryId'])
    assert snapshot['expires_at']>time.time()+service.policy.ttl_seconds-2
    with service.catalog.connection(write=True) as conn:
        conn.execute('DELETE FROM query_day_counts WHERE query_id=?',(pending['queryId'],))
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):service.read(result['queryId'])


def test_restarted_presence_discards_old_deleted_positive(query_archive):
    service,archive,_=query_archive
    item=row();write_day(raw_root(archive),'2026-09-30',[item]);run(archive,[item])
    pending,_=service.create(request(downloadStatus='downloaded'))
    key=archive[1].conn.execute("SELECT artifact_key FROM artifacts").fetchone()[0]
    service.catalog.presence(pending['queryId'],[key]) # Persisted interrupted preparation.
    task=archive[1].conn.execute('SELECT relative_path FROM artifacts').fetchone()[0]
    (archive[0].output/task).unlink()
    service.prepare_next()
    result,_=service.read(pending['queryId'])
    assert result['total']==0 and result['pageState']['status']=='empty'


def test_count_progress_persisted_and_page_crosses_day_boundaries(query_archive):
    service,archive,source=query_archive
    first=date(2026,9,29);last=date(2026,9,30)
    write_day(raw_root(archive),first.isoformat(),[row(i,day=first) for i in range(1,39)])
    write_day(raw_root(archive),last.isoformat(),[row(i,day=last) for i in range(1,24)])
    pending,_=service.create(AnnouncementQueryRequest(startDate=first,endDate=last))
    service.prepare_next();result,_=service.read(pending['queryId'])
    assert result['total']==61 and len(result['items'])==50
    assert sum(r['annDate']==last.isoformat() for r in result['items'])==23
    second,_=service.read(pending['queryId'],2)
    assert len(second['items'])==11 and not second['hasNext']
    snapshot=service.catalog.query(pending['queryId'])
    assert snapshot['dates_counted']==2 and snapshot['preparation_stage']=='counting'


def test_read_budget_shared_across_stat_and_sql_and_reset(query_archive):
    from src.foundation.clients.announcement_archive.budget import read_budget,remaining
    service,archive,_=query_archive
    with pytest.raises(Blocked,match='catalog_sql_timeout'):
        with read_budget(.005):
            time.sleep(.01)
            with service.catalog.connection():pass
    # The expired HTTP scope does not poison the background preparation thread or a later read.
    assert remaining(4)==4
    with service.catalog.connection() as conn:assert conn.execute('SELECT 1').fetchone()[0]==1
