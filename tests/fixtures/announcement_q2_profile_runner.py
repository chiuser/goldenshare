"""Opt-in Q2 read-only Lake profile; PG is a caller-created disposable cluster.

No source site, formal PG, archive/Raw write, source SQLite rewrite, or dependency install.
"""
import json
import os
from pathlib import Path
import resource
import sys
import time
from dataclasses import replace
from datetime import date

from sqlalchemy import event
from fastapi import FastAPI,APIRouter
from fastapi.testclient import TestClient
from src.foundation.clients.announcement_archive.core import Control,DownloadPolicy,identity
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.clients.announcement_archive.source import RAW_ROOT
from src.foundation.clients.announcement_archive.names import NAME_ROOT
from src.foundation.clients.announcement_archive.direct_source import DirectSource,batches,days
from src.foundation.clients.announcement_archive.query_presence import QueryPresence
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy,DataCenterPolicy
from src.foundation.config.settings import Settings
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase
from src.foundation.dao.announcement_archive.pg_archive import register_archive
from src.foundation.dao.announcement_archive.query_controls import QueryControls
from src.foundation.clients.announcement_archive.migration_source import LegacyLedger,opened
from src.ops.runtime.announcement_archive.source_runtime import SourcePreparation
from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
from src.app.runtime.announcement_archive_lifespan import install_data_center,include_data_center
from src.app.auth.dependencies import get_current_user


def main():
    config=json.loads(Path(sys.argv[1]).read_text());scenario=config['scenario']
    if not config['database'].startswith('q1_') or config['port']==5432:raise ValueError('disposable PG required')
    database=ArchiveDatabase(config['url'],replace(ArchiveDatabasePolicy(),database=config['database'],port=config['port']))
    timings=[]
    @event.listens_for(database.engine,'before_cursor_execute')
    def before(conn,*_):conn.info['q2_start']=time.monotonic()
    @event.listens_for(database.engine,'after_cursor_execute')
    def after(conn,*_):timings.append(time.monotonic()-conn.info.pop('q2_start'))
    policy=DataCenterPolicy();control=Control(DownloadPolicy(),emit=lambda _:None)
    volumes=[SourceVolume(path,control.policy).open() for path in (RAW_ROOT,NAME_ROOT,Path('/Volumes/datasource'))]
    aid=identity([volumes[2].volume_uuid,'announcements'])
    with database.transaction() as conn:register_archive(conn,volumes[2].volume_uuid,'announcements')
    source=DirectSource(*volumes[:2],control,policy);store=QueryControls(database,aid,source.scope)
    # Explicit isolated success facts; no formal ledger is changed/migrated.
    legacy_path=Path.home()/'Library/Application Support/Goldenshare/announcement-download'/aid/'downloads.sqlite'
    ledger_before=None
    if scenario in {'downloaded','undownloaded'} and legacy_path.is_file():
        with opened(LegacyLedger(legacy_path,control)) as old:
            ledger_before=old.sha256;after_key=''
            while rows:=old.query("SELECT * FROM artifacts WHERE state='succeeded' AND artifact_key>? ORDER BY artifact_key LIMIT 500",(after_key,)):
                values=[dict(r) for r in rows]
                with store.transaction() as conn:
                    for batch in batches(values,500):store.insert(conn,'artifacts',batch,ignore=True)
                after_key=rows[-1]['artifact_key']
            old.assert_unchanged()
    presence=QueryPresence(volumes[2],store,'announcements');service=AnnouncementQueryService(store,source,presence)
    prep=SourcePreparation(source,store,presence,policy)
    if scenario=='historyManifest':
        dirs=[]
        with os.scandir(volumes[0].root_fd) as entries:
            for entry in entries:
                if entry.name.startswith('ann_date=') and entry.is_dir(follow_symlinks=False):dirs.append(entry.name[9:])
        dirs.sort();start=time.monotonic();counts=byte_count=files=row_groups=0
        for batch in batches(dirs,policy.file_batch_size):
            with source.session(),source.pinned('anns_d',batch) as (paths,facts):
                counts+=sum(r['footer_count'] for r in facts);byte_count+=sum(r['size'] for r in facts);files+=len(facts)
                row_groups+=source.sql('SELECT count(DISTINCT (file_name,row_group_id)) FROM parquet_metadata(?)',[paths],1)[0][0]
        result=dict(kind=scenario,files=files,records=counts,bytes=byte_count,rowGroups=row_groups,seconds=time.monotonic()-start)
    else:
        import src.biz.api.wealth.data_center.home as home
        import src.biz.api.wealth.data_center.announcements as announcements
        import src.biz.api.wealth.data_center.downloads as downloads
        settings=Settings(APP_ENV='local',WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED=True)
        home.get_settings=announcements.get_settings=downloads.get_settings=lambda:settings
        app=FastAPI();install_data_center(app);router=APIRouter(prefix='/api/v1');include_data_center(router);app.include_router(router)
        app.dependency_overrides[get_current_user]=lambda:object()
        from types import SimpleNamespace
        app.state.announcement_source=SimpleNamespace(service=lambda:service)
        client=TestClient(app);prefix='/api/v1/wealth/data-center/announcements'
        condition=dict(startDate='2026-05-04',endDate='2026-10-05',tsCode='002245.SZ' if scenario=='stock155' else None,
            titleKeyword='',downloadStatus=scenario if scenario in {'downloaded','undownloaded'} else 'all')
        if scenario=='default30':condition.update(startDate='2026-09-07',endDate='2026-10-06')
        initial=time.monotonic();response=client.post(prefix+'/queries',json=condition);assert response.status_code==202,response.text
        qid=response.json()['queryId'];units=[];last=0;progress=[]
        while store.query(qid)['state']=='preparing':
            unit=time.monotonic();assert prep.next_unit();units.append(time.monotonic()-unit)
            row=store.query(qid);progress.append(dict(stage=row['preparation_stage'],dates=row['dates_scanned'],records=row['records_scanned'],artifacts=row['artifacts_checked']))
        preparation_seconds=time.monotonic()-initial
        gets=[];last_response=None
        for _ in range(6):
            now=time.monotonic();response=client.get(prefix+'/queries/'+qid);gets.append(time.monotonic()-now)
            assert response.status_code==200,response.text
            last_response=response.json();assert last_response['pageState']['status'] in {'ready','empty'},last_response
        manifests=[r for batch in store.files(qid) for r in batch if r['source_kind']=='anns_d']
        row_groups=0
        for group in batches(manifests,32):
            with source.session(),source.pinned('anns_d',[r['partition'] for r in group]) as (paths,_):
                row_groups+=source.sql('SELECT count(DISTINCT (file_name,row_group_id)) FROM parquet_metadata(?)',[paths],1)[0][0]
        verified=0
        if scenario=='stock155':
            expected=[]
            for group in batches(manifests,32):
                with source.session(),source.pinned('anns_d',[r['partition'] for r in group]) as (paths,_):
                    rows=source.sql('SELECT ann_date,ts_code,name,title,url,rec_time FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?',[paths,'002245.SZ'],501)
                    assert len(rows)<=500
                    for row in rows:
                        key=identity(['dg-anns-d-v1',*row])
                        expected.append((row[0],row[1],key,row[3],row[4].strip() if row[4] else None))
            expected.sort(key=lambda r: (-int(r[0]),r[1],r[2]))
            actual=[(r['recordKey'],r['title'],r['sourceUrl']) for r in last_response['items']]
            assert actual==[(r[2],r[3],r[4]) for r in expected]
            assert len(expected)==last_response['total']==36
            verified=len(expected)
        result=dict(kind=scenario,identityVerifiedRows=verified,files=len(manifests),records=sum(r['footer_count'] for r in manifests),bytes=sum(r['size'] for r in manifests),
            rowGroups=row_groups,resultRows=len(last_response['items']),total=last_response['total'],preparationSeconds=preparation_seconds,
            coldGetSeconds=gets[0],warmGetSeconds=gets[1:],getP95Seconds=sorted(gets)[-1],unitMaxSeconds=max(units),progress=progress)
    result.update(pid=os.getpid(),sqlMaxSeconds=max([source.sql_max_seconds,*timings]),pgSqlCalls=len(timings),duckSqlCalls=source.sql_calls,
        announcementFdPeak=source.fd_peak,processFdCount=len(os.listdir('/dev/fd')),rssMiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024),
        sourceHttpRequests=0,formalPgWrites=0,formalLakeWrites=0,formalPdfWrites=0,osCacheFlushed=False)
    prep.close();source.close();presence.close();database.close()
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
