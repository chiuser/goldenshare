"""Q2 isolated PG + temporary Parquet/PDF acceptance. Never formal writes/HTTP."""
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import time

import duckdb
import pytest
from sqlalchemy import text

from test_announcement_pg_migration import pg,pg_cluster
from test_announcement_download_dg import write_day
from src.foundation.clients.announcement_archive.core import ANNOUNCEMENT_FIELDS,Blocked,Control,DownloadPolicy,identity,timestamp
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.clients.announcement_archive.direct_source import DirectSource,days,batches,URL_WHITESPACE
from src.foundation.clients.announcement_archive.query_presence import QueryPresence
from src.foundation.dao.announcement_archive.pg_schema import install_schema
from src.foundation.dao.announcement_archive.pg_archive import register_archive
from src.foundation.dao.announcement_archive.query_controls import QueryControls
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.ops.runtime.announcement_archive.source_runtime import SourcePreparation
from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
from src.biz.services.wealth.data_center.download_service import AnnouncementDownloadService
from src.biz.schemas.wealth.data_center.announcements import AnnouncementQueryRequest,QueryResultDto
from src.biz.schemas.wealth.data_center.downloads import PreviewRequest,PreviewDto
from src.biz.services.wealth.data_center.errors import DataCenterError


def row(title='公告',**values):
    return dict(ann_date='20260930',ts_code='600000.SH',name='公告旧名',title=title,url='https://ann.example/1.pdf',rec_time=None,**values)


def write_names(root,kind,columns,rows):
    path=root/kind/'full/part-000.parquet';path.parent.mkdir(parents=True,exist_ok=True)
    with duckdb.connect() as conn:
        conn.execute('CREATE TABLE n('+','.join(c+' VARCHAR' for c in columns)+')')
        if rows:conn.executemany('INSERT INTO n VALUES('+','.join('?' for _ in columns)+')',rows)
        conn.execute('COPY n TO ? (FORMAT PARQUET)',[str(path)])
    return path


@pytest.fixture
def direct(pg,tmp_path,monkeypatch):
    from src.foundation.clients.announcement_archive import volume as module
    mount=tmp_path/'disk';root=mount/'data_lake/raw/tushare';raw=root/'anns_d';raw.mkdir(parents=True)
    output=mount/'announcements';output.mkdir()
    monkeypatch.setattr(module.sys,'platform','darwin')
    monkeypatch.setattr(module.os.path,'ismount',lambda p:Path(p)==mount)
    info=dict(MountPoint=str(mount),VolumeUUID='q2-volume',DeviceIdentifier='fixture-device',WritableVolume=True,Internal=False,VirtualOrPhysical='Physical')
    policy=DataCenterPolicy();control=Control(DownloadPolicy(),emit=lambda _:None)
    volumes=[SourceVolume(path,control.policy,lambda _:info).open() for path in (raw,root,mount)]
    write_names(root,'stock_basic',('ts_code','name','cnspell'),[('600000.SH','浦发银行','PFYH'),('000002.SZ','退市样本','TSYB')])
    write_names(root,'namechange',('ts_code','name'),[('600000.SH','旧简称'),('000002.SZ','老退市名')])
    write_day(raw,'2026-09-30',[row()])
    with pg.transaction() as conn:
        install_schema(conn);register_archive(conn,'q2-volume','announcements')
    aid=identity(['q2-volume','announcements'])
    source=DirectSource(*volumes[:2],control,policy)
    controls=QueryControls(pg,aid,source.scope,policy)
    presence=QueryPresence(volumes[2],controls,'announcements')
    service=AnnouncementQueryService(controls,source,presence)
    preparation=SourcePreparation(source,controls,presence,policy)
    downloads=AnnouncementDownloadService(None,None,lambda:controls,lambda:aid,lambda:None)
    yield service,preparation,downloads,raw,root,output
    preparation.close();source.close();presence.close()


def request(**kw):return AnnouncementQueryRequest(**{'startDate':'2026-09-30','endDate':'2026-09-30',**kw})


def prepare(service,preparation,body=None):
    pending,status=service.create(body or request());assert status==202
    QueryResultDto.model_validate(pending)
    for _ in range(10000):
        if service.controls.query(pending['queryId'])['state']!='preparing':break
        assert preparation.next_unit()
    result,status=service.read(pending['queryId']);QueryResultDto.model_validate(result)
    return result


def artifact(service,output,item,state='succeeded'):
    key=identity(['2026-09-30',item['ts_code'],item['url'].strip()])
    relative=key+'.pdf';(output/relative).write_bytes(b'pdf')
    with service.controls.transaction() as conn:
        service.controls.insert(conn,'artifacts',[dict(artifact_key=key,ann_date='2026-09-30',ts_code=item['ts_code'],title=item['title'],url=item['url'],relative_path=relative,path_fold=relative,state=state,size=3)])
    return key,output/relative


def test_direct_rows_and_new_contract(direct):
    service,prep,_,raw,*_=direct
    original=row();rows=[original,dict(original,name=None,rec_time=''),dict(original,url=None,title=None),dict(original,url='',name='')]
    write_day(raw,'2026-09-30',rows)
    result=prepare(service,prep)
    assert result['total']==4 and len(result['items'])==4
    assert len({r['recordKey'] for r in result['items']})==4
    assert {r['companyName'] for r in result['items']}=={'浦发银行'}
    assert sum(r['sourceUrl'] is None for r in result['items'])==2
    assert len(result['sourceVersion'])==64 and 'catalogRevision' not in result
    context=service.context()
    assert context['ledgerAvailability']=='ready' and context['sourceUpdateSucceededAt'] is None
    assert not {'indexAvailability','lastIndexedAt'} & set(context)


@pytest.mark.parametrize('value',['中文','"\\\t\n\r\x00\x01','𠀀😀',None,'','\u2028\u2029','\u007f'])
def test_identity_goldens(direct,value):
    service,_,_,raw,*_=direct
    item=dict(row(),name=value,title=value,rec_time=value)
    write_day(raw,'2026-09-30',[item])
    with service.source.session(),service.source.pinned('anns_d',['2026-09-30']) as (paths,_):
        sql,args=service.source.projection(paths,['2026-09-30'],service.conditions(request()))
        keys=service.source.sql(sql+' SELECT record_key,artifact_key FROM projected',args,1)[0]
    assert keys==(identity(['dg-anns-d-v1',*(item[c] for c in ANNOUNCEMENT_FIELDS)]),identity(['2026-09-30',item['ts_code'],item['url'].strip()]))


@pytest.mark.parametrize('whitespace',[URL_WHITESPACE,'\t\n','\u00a0','\u3000','\x1c',''])
def test_url_strip_identity(direct,whitespace):
    service,prep,_,raw,*_=direct
    item=dict(row(),url=whitespace+'https://ann.example/x.pdf'+whitespace)
    write_day(raw,'2026-09-30',[item])
    result=prepare(service,prep)
    assert result['total']==1
    assert result['items'][0]['sourceUrl']==item['url'].strip()
    with service.source.session(),service.source.pinned('anns_d',['2026-09-30']) as (paths,_):
        sql,args=service.source.projection(paths,['2026-09-30'],service.conditions(request()))
        assert service.source.sql(sql+' SELECT artifact_key FROM projected',args,1)[0][0]==identity(['2026-09-30','600000.SH',item['url'].strip()])


def test_missing_and_empty_are_distinct_terminal(direct):
    service,prep,_,raw,*_=direct
    (raw/'ann_date=2026-09-30/part-000.parquet').unlink()
    failed=prepare(service,prep)
    assert failed['pageState']['status']=='error' and failed['pageState']['code']=='DC_SOURCE_UNAVAILABLE'
    assert '2026-09-30' in failed['pageState']['message'] and failed['total'] is None
    write_day(raw,'2026-09-30',[])
    empty=prepare(service,prep)
    assert empty['pageState']['status']=='empty' and empty['total']==0


@pytest.mark.parametrize('status',['all','downloaded','undownloaded'])
def test_tail_adjustment_zero_day_and_requested_conditions(direct,status):
    service,prep,_,raw,*_=direct
    write_day(raw,'2026-10-01',[])
    result=prepare(service,prep,request(endDate=date(2026,10,8),downloadStatus=status))
    assert result['effectiveEndDate']=='2026-10-01'
    assert result['conditions']['endDate']=='2026-10-08'
    assert result['total']==(0 if status=='downloaded' else 1)
    assert result['pageState']['status']==('empty' if status=='downloaded' else 'ready')
    assert '2026-10-01' in result['pageState']['message']
    saved=service.controls.query(result['queryId'])
    assert saved['dates_total']==saved['dates_scanned']==2
    future=prepare(service,prep,request(startDate=date(2026,10,2),endDate=date(2026,10,8),downloadStatus=status))
    assert future['pageState']['status']=='empty' and future['total']==0
    assert future['effectiveEndDate']=='2026-10-01' and future['items']==[]
    assert '所选区间暂无已同步公告' in future['pageState']['message']
    assert service.controls.query(future['queryId'])['dates_total']==0


def test_tail_query_pagination_frozen_and_refresh_reads_new_day(direct):
    service,prep,_,raw,*_=direct
    write_day(raw,'2026-09-30',[dict(row(f'公告{i:03}'),url=f'https://ann.example/{i}.pdf') for i in range(51)])
    body=request(endDate=date(2026,10,2))
    first=prepare(service,prep,body)
    assert first['total']==51 and first['effectiveEndDate']=='2026-09-30'
    write_day(raw,'2026-10-01',[])
    write_day(raw,'2026-10-02',[dict(row('新公告'),ann_date='20261002')])
    second,_=service.read(first['queryId'],2)
    assert len(second['items'])==1 and second['total']==51
    assert second['effectiveEndDate']==first['effectiveEndDate'] and second['conditions']==first['conditions']
    fresh=prepare(service,prep,body)
    assert fresh['total']==52 and fresh['effectiveEndDate']=='2026-10-02'
    assert fresh['pageState']['message'] is None


def test_adjustment_never_skips_middle_gap_or_damaged_latest_partition(direct):
    service,prep,_,raw,*_=direct
    path=write_day(raw,'2026-10-02',[])
    result=prepare(service,prep,request(endDate=date(2026,10,8)))
    assert result['pageState']['status']=='error' and '2026-10-01' in result['pageState']['message']
    path.write_bytes(b'broken parquet')
    result=prepare(service,prep,request(endDate=date(2026,10,8)))
    assert result['pageState']['status']=='error' and result['total'] is None


def test_damage_after_requested_range_does_not_block_history(direct):
    service,prep,_,raw,*_=direct
    path=write_day(raw,'2026-10-02',[])
    path.write_bytes(b'broken parquet')
    result=prepare(service,prep)
    assert result['pageState']['status']=='ready' and result['total']==1
    assert result['effectiveEndDate']=='2026-09-30' and result['pageState']['message'] is None


def test_download_preview_does_not_shorten_requested_tail(direct):
    service,prep,downloads,raw,*_=direct
    result=prepare(service,prep,request(endDate='2026-10-01'))
    assert result['pageState']['status']=='ready' and result['effectiveEndDate']=='2026-09-30'
    preview,_=downloads.create_preview(PreviewRequest(startDate='2026-09-30',endDate='2026-10-01'))
    object_id=preview['previewId']
    while service.controls.preview(object_id)['state']=='preparing':assert prep.next_unit()
    result,_=downloads.preview(object_id)
    assert result['state']=='error' and result['endDate']=='2026-10-01'
    assert not result['canStart'] and result['error']['code']=='DC_SOURCE_UNAVAILABLE'


@pytest.mark.parametrize('mutation',['replace','inplace','names','dictionary','volume'])
def test_source_changes_invalidate_complete_query(direct,mutation,monkeypatch):
    service,prep,_,raw,root,_=direct
    result=prepare(service,prep);path=raw/'ann_date=2026-09-30/part-000.parquet'
    if mutation=='replace':
        other=raw/'candidate';candidate=write_day(other,'2026-09-30',[row('新公告')]);os.replace(candidate,path)
    elif mutation=='inplace':os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1))
    elif mutation=='names':
        path=root/'stock_basic/full/part-000.parquet';os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1))
    elif mutation=='dictionary':monkeypatch.setattr(service.source.initials,'version','changed')
    else:monkeypatch.setattr(service.source.volume,'assert_valid',lambda **_:(_ for _ in ()).throw(Blocked('volume_disconnected_or_changed')))
    with pytest.raises(DataCenterError):service.read(result['queryId'])


def test_pinned_old_inode_never_reopens_path(direct):
    service,_,_,raw,*_=direct;path=raw/'ann_date=2026-09-30/part-000.parquet'
    with service.source.session(),service.source.pinned('anns_d',['2026-09-30']) as (paths,_):
        other=raw/'candidate';candidate=write_day(other,'2026-09-30',[row('替换后')]);os.replace(candidate,path)
        assert service.source.sql('SELECT title FROM read_parquet(?,hive_partitioning=false)',[paths],1)==[('公告',)]


def test_stable_deep_page_and_title_filter(direct):
    service,prep,_,raw,*_=direct
    items=[dict(row(f'标题{i:03}'),url=f'https://ann.example/{i}.pdf') for i in range(125)]
    write_day(raw,'2026-09-30',items)
    result=prepare(service,prep)
    pages=[service.read(result['queryId'],page)[0] for page in (1,2,3)]
    keys=[r['recordKey'] for p in pages for r in p['items']]
    assert len(keys)==len(set(keys))==125 and keys==sorted(keys)
    title=prepare(service,prep,request(titleKeyword='标题1'))
    assert title['total']==25


def test_status_full_range_count_deleted_file_and_size(direct):
    service,prep,_,raw,_,output=direct
    rows=[dict(row(f'公告{i}'),url=f'https://ann.example/{i}.pdf') for i in range(85)]
    write_day(raw,'2026-09-30',rows)
    succeeded=[artifact(service,output,item) for item in rows[:60]]
    succeeded[1][1].unlink();succeeded[2][1].write_bytes(b'wrong size')
    downloaded=prepare(service,prep,request(downloadStatus='downloaded'))
    undownloaded=prepare(service,prep,request(downloadStatus='undownloaded'))
    assert downloaded['total']==58 and undownloaded['total']==27, (service.controls.query(downloaded['queryId']),service.controls.query(undownloaded['queryId']))
    assert len(service.read(downloaded['queryId'],2)[0]['items'])==8
    succeeded[0][1].unlink()
    with pytest.raises(DataCenterError,match='DC_QUERY_CONTEXT_CHANGED'):service.read(downloaded['queryId'])
    all_rows=prepare(service,prep)
    assert all_rows['total']==85


def test_search_current_history_delisted_missing_and_fallback(direct):
    service,prep,_,raw,*_=direct
    write_day(raw,'2026-09-30',[dict(row(),ts_code='999999.SH',name='缺主表'),dict(row(),ts_code='999998.SH',name=None)])
    prepare(service,prep)
    for keyword,code,kind in [('浦发','600000.SH','name'),('旧简称','600000.SH','alias'),('TSYB','000002.SZ','initials'),('缺主表','999999.SH','name'),('999998','999998.SH','exactCode')]:
        result,status=service.companies(keyword,request())
        assert status==200 and result['items'][0]['tsCode']==code and result['items'][0]['matchKind']==kind
    page=prepare(service,prep)
    assert {r['companyName'] for r in page['items']}=={'缺主表','999998.SH'}


def test_preview_sha_cancel_gc_no_http(direct):
    service,prep,downloads,raw,*_=direct
    write_day(raw,'2026-09-30',[row(),dict(row(),name='另一公告'),dict(row(),url=None)])
    result,status=downloads.create_preview(PreviewRequest(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=2))
    object_id=result['previewId'];assert status==202;PreviewDto.model_validate(result)
    while service.controls.preview(object_id)['state']=='preparing':assert prep.next_unit()
    result,status=downloads.preview(object_id);PreviewDto.model_validate(result)
    assert result['artifactCount']==1 and result['recordCount']==3 and result['missingUrlCount']==1
    facts=json.loads(service.controls.preview_day(object_id,'2026-09-30')['source_facts'])
    assert len(facts['sha256'])==64 and prep.validate_preview(object_id)['state']=='ready'
    with service.controls.transaction() as conn:
        service.controls.update(conn,'preview',object_id,dict(expires_at=time.time()-1))
    assert service.controls.gc()>=3 and service.controls.preview(object_id) is None
    result,_=downloads.create_preview(PreviewRequest(startDate='2026-09-30',endDate='2026-09-30'))
    downloads.stop_preview(result['previewId'])
    assert service.controls.preview(result['previewId'])['state']=='cancelled'
    with pytest.raises(Blocked,match='archive_execution_not_ready'):downloads.command('create',{'previewId':object_id})


def test_gc_batched_resume_and_preserve_ledger(direct):
    service,prep,_,_,_,output=direct;key,_=artifact(service,output,row())
    result=prepare(service,prep);qid=result['queryId']
    for offset in (0,500,1000):
        with service.controls.transaction() as conn:
            service.controls.insert(conn,'query_presence',[dict(query_id=qid,artifact_key=f'gc-{i}',checked_at=timestamp()) for i in range(offset,min(offset+500,1200))])
    with service.controls.transaction() as conn:service.controls.update(conn,'query',qid,dict(expires_at=time.time()-1))
    calls=0
    def stop():
        nonlocal calls
        calls+=1
        if calls==4:raise Blocked('fixture_stop')
    with pytest.raises(Blocked):service.controls.gc(stop)
    assert service.controls.query(qid)['state']=='expired'
    assert service.controls.gc()>0 and service.controls.query(qid) is None
    assert service.controls.artifact_rows([key])[0]['state']=='succeeded'


def test_session_lock_restart_unsealed_and_no_ddl(direct):
    service,prep,*_=direct;result,_=service.create(request());qid=result['queryId']
    assert prep.next_unit() # names facts persisted, owner + advisory lock retained
    assert service.controls.rows('query_files','AND query_id=:id',{'id':qid})
    with service.controls.claim('query',qid) as other:assert other is None
    prep.close() # releases session lock, unpublished controls can restart
    restarted=SourcePreparation(service.source,service.controls,service.presence,service.policy)
    while service.controls.query(qid)['state']=='preparing':assert restarted.next_unit()
    assert service.read(qid)[0]['total']==1
    with service.controls.transaction(read_only=True) as conn:
        tables=set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='announcement_archive'")).scalars())
    assert 'anns_d' not in tables and 'catalog_records' not in tables


def test_file_bound_sql_timeout_and_source_schema(direct):
    service,prep,_,raw,*_=direct
    with service.source.session():
        with pytest.raises(ValueError,match='source_file_batch_limit'):
            with service.source.pinned('anns_d',['2026-09-30']*33):pass
    write_day(raw,'2026-09-30',[row()],columns=ANNOUNCEMENT_FIELDS[:-1])
    result=prepare(service,prep)
    assert result['pageState']['code']=='DC_SOURCE_CONTRACT_MISMATCH'


def test_sql_deadline_interrupts_and_connection_remains_usable(direct):
    from src.foundation.clients.announcement_archive.budget import read_budget
    service,*_=direct
    with service.source.session():
        with pytest.raises(Blocked,match='query_sql_timeout'),read_budget(.03):
            service.source.sql('SELECT sum(i*j) FROM range(1000000) a(i),range(1000000) b(j)')
        assert service.source.sql('SELECT 1')==[(1,)]


def test_partial_prepare_does_not_seal_changed_names(direct):
    service,prep,_,_,root,_=direct
    pending,_=service.create(request());qid=pending['queryId']
    assert prep.next_unit()
    path=root/'stock_basic/full/part-000.parquet'
    os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1))
    while service.controls.query(qid)['state']=='preparing':assert prep.next_unit()
    result,_=service.read(qid)
    assert result['total'] is None and result['sourceVersion'] is None
    assert result['pageState']['code']=='DC_QUERY_CONTEXT_CHANGED'


def test_untracked_file_and_null_code_are_not_downloaded(direct):
    service,prep,_,raw,_,output=direct
    (output/'untracked.pdf').write_bytes(b'pdf')
    write_day(raw,'2026-09-30',[dict(row(),ts_code=None,url=None)])
    result=prepare(service,prep,request(downloadStatus='undownloaded'))
    assert result['total']==1 and result['items'][0]['tsCode'] is None
    assert result['items'][0]['downloadStatus']=='undownloaded'
    with service.controls.transaction(read_only=True) as conn:
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.artifacts'))==0


def test_process_exit_releases_query_claim_and_rebuilds_unsealed_controls(direct,tmp_path):
    import subprocess
    import sys
    service,prep,*_=direct
    pending,_=service.create(request());qid=pending['queryId'];database=service.controls.database
    config=tmp_path/'claim.json'
    config.write_text(json.dumps(dict(url=database.engine.url.render_as_string(hide_password=False),database=database.policy.database,port=database.policy.port,archive=service.controls.archive_id,scope=service.controls.scope,qid=qid)))
    program='''
import json,os,sys
from dataclasses import replace
from pathlib import Path
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase
from src.foundation.dao.announcement_archive.query_controls import QueryControls
c=json.loads(Path(sys.argv[1]).read_text())
assert c['database'].startswith('q1_') and c['port']!=5432
db=ArchiveDatabase(c['url'],replace(ArchiveDatabasePolicy(),database=c['database'],port=c['port']))
store=QueryControls(db,c['archive'],c['scope'])
with store.claim('query',c['qid']) as claimed:
    assert claimed is not None
    owner,_=claimed
    store.save_unit('query',c['qid'],owner,{'query_presence':[dict(query_id=c['qid'],artifact_key='unpublished',checked_at='fixture')]},dict(records_scanned=99))
    os._exit(87)
'''
    result=subprocess.run([sys.executable,'-c',program,str(config)],capture_output=True,text=True,timeout=15)
    assert result.returncode==87,result.stderr
    assert service.controls.query(qid)['state']=='preparing'
    while service.controls.query(qid)['state']=='preparing':assert prep.next_unit()
    assert service.read(qid)[0]['total']==1
    assert service.controls.presence_keys(qid)==[]
