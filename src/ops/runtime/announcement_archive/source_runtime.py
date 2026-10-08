"""One lifecycle-owned source loop: query/preview units and bounded control GC.

Execution/HTTP is separate. Claims use PG session locks, not heartbeat leases.
"""
import json
import threading
import time
from datetime import date

from src.foundation.clients.announcement_archive.budget import read_budget
from src.foundation.clients.announcement_archive.core import Blocked,Cancelled,timestamp
from src.foundation.clients.announcement_archive.direct_source import batches,days,source_version,effective_conditions


class SourcePreparation:
    def __init__(self,source,controls,presence,policy):
        self.source,self.controls,self.presence,self.policy=source,controls,presence,policy
        self.active=None

    def check(self,kind,object_id,owner,connection):
        self.source.control.check();self.controls.check_claim(connection,kind,object_id,owner)

    def next_unit(self):
        if self.active is None:
            pending=self.controls.pending()
            if not pending:return False
            self.active=self.prepare(*pending)
        try:next(self.active)
        except StopIteration:self.active=None
        return True

    def prepare(self,kind,row):
        key='query_id' if kind=='query' else 'preview_id';object_id=row[key]
        with self.controls.claim(kind,object_id) as claim:
            if claim is None:return
            owner,connection=claim
            check=lambda:self.check(kind,object_id,owner,connection)
            try:
                if kind=='query':yield from self.query(row,owner,check)
                else:yield from self.preview(row,owner,check)
            except Cancelled:
                # Shutdown is restartable; connection loss releases claim. No new unit.
                return
            except Exception as error:
                reason=str(error) if isinstance(error,Blocked) else 'query_prepare_failed'
                if reason=='preview_cancelled':return
                self.controls.finish(kind,object_id,owner,state='error',reason=reason)

    def query(self,row,owner,check):
        source,controls=self.source,self.controls
        object_id=row['query_id'];conditions=json.loads(row['conditions']);checked=0
        check()
        with source.session(),read_budget(self.policy.sql_seconds):
            latest=source.latest_date(conditions['endDate'])
            if latest is None:raise Blocked('source_day_missing:'+conditions['startDate'])
            conditions['effectiveEndDate']=min(conditions['endDate'],latest)
            names=source.prepare_names()
        serialized=json.dumps(conditions,ensure_ascii=False)
        conditions=effective_conditions(conditions)
        date_count=max(0,(date.fromisoformat(conditions['endDate'])-date.fromisoformat(conditions['startDate'])).days+1)
        controls.save_unit('query',object_id,owner,{'query_files':[dict(query_id=object_id,**r) for r in names]},
            dict(preparation_stage='readingSource',conditions=serialized,dates_total=date_count))
        yield
        if conditions['downloadStatus']!='all':
            after=''
            while rows:=controls.successful(conditions,after):
                check()
                with read_budget(self.policy.sql_seconds):present=self.presence.check_rows(rows)
                checked+=len(rows)
                controls.save_unit('query',object_id,owner,{'query_presence':[dict(query_id=object_id,artifact_key=k,checked_at=timestamp()) for k in sorted(present)]},
                    dict(preparation_stage='checkingStatus',artifacts_checked=checked))
                after=rows[-1]['artifact_key'];yield
        scanned=records=total=0
        # One-day status units bound relevant key temp relation; all can vectorize 32 files.
        size=1 if conditions['downloadStatus']!='all' else self.policy.file_batch_size
        for parts in batches(days(conditions['startDate'],conditions['endDate']),size):
            check()
            with source.session(),read_budget(self.policy.sql_seconds):
                if conditions['downloadStatus']!='all':
                    def keys():
                        after=''
                        while values:=controls.presence_keys(object_id,after,day=parts[0],code=conditions['tsCode']):
                            yield values;after=values[-1]['artifact_key']
                    source.set_presence(keys())
                facts,counts=source.count_unit(parts,conditions)
            scanned+=len(facts);records+=sum(r['footer_count'] for r in facts);total+=sum(n for _,n in counts)
            controls.save_unit('query',object_id,owner,dict(query_files=[dict(query_id=object_id,**r) for r in facts],
                query_day_counts=[dict(query_id=object_id,ann_date=day,match_count=n) for day,n in counts]),
                dict(preparation_stage='counting',dates_scanned=scanned,records_scanned=records,artifacts_checked=checked))
            yield
        check()
        with source.session(),read_budget(self.policy.sql_seconds):source.validate_manifest(controls.files(object_id))
        version=source_version(source.scope,source.initials.version,controls.files(object_id))
        available=True
        try:self.presence.check([])
        except (Blocked,OSError):available=False
        if conditions['downloadStatus']!='all' and not available:raise Blocked('archive_presence_unavailable')
        controls.finish('query',object_id,owner,state='ready',source_version=version,total=total,checked_at=timestamp(),status_available=int(available))

    def preview(self,row,owner,check):
        source,controls=self.source,self.controls;object_id=row['preview_id']
        conditions=dict(startDate=row['start_date'],endDate=row['end_date'],tsCode=None,titleKeyword='',downloadStatus='all')
        with source.session(),read_budget(self.policy.sql_seconds):names=source.prepare_names()
        yield
        stats=dict(recordCount=0,artifactCount=0,missingUrlCount=0,reusableEstimate=0,downloadEstimate=0,reason=None)
        scanned=0
        for day in days(row['start_date'],row['end_date']):
            check()
            with source.session(),read_budget(self.policy.sql_seconds):facts,missing=source.preview_start(day,conditions)
            after=''
            yield
            while True:
                check()
                with source.session(),read_budget(self.policy.sql_seconds):values=source.preview_keys(day,conditions,after,facts)
                if not values:break
                with controls.transaction() as conn:
                    inserted=controls.insert(conn,'preview_artifacts',[dict(preview_id=object_id,artifact_key=k) for k in values],ignore=True)
                with read_budget(self.policy.sql_seconds):reusable=len(self.presence.check([r['artifact_key'] for r in inserted]))
                stats['artifactCount']+=len(inserted);stats['reusableEstimate']+=reusable
                stats['downloadEstimate']=stats['artifactCount']-stats['reusableEstimate']
                controls.save_unit('preview',object_id,owner,{},dict(statistics=json.dumps(stats),records_scanned=stats['recordCount']+facts['footer_count']))
                after=values[-1];yield
            check()
            with source.session(),read_budget(self.policy.sql_seconds):source.preview_start(day,conditions,facts)
            stats['recordCount']+=facts['footer_count'];stats['missingUrlCount']+=missing;scanned+=1
            controls.save_unit('preview',object_id,owner,{'preview_days':[dict(preview_id=object_id,ann_date=day,source_facts=json.dumps(facts))]},
                dict(statistics=json.dumps(stats),dates_scanned=scanned,records_scanned=stats['recordCount']))
            yield
        check()
        with source.session(),read_budget(self.policy.sql_seconds):
            source.validate_manifest([names]);self.presence.assert_valid(full=True)
            for manifest in self.preview_manifest(object_id):source.validate_manifest([manifest])
        version=source_version(source.scope,source.initials.version,self.preview_manifest(object_id,names))
        controls.finish('preview',object_id,owner,state='ready' if stats['artifactCount'] else 'empty',source_version=version,statistics=json.dumps(stats))

    def preview_manifest(self,object_id,names=()):
        after=''
        while rows:=self.controls.rows('preview_days','AND preview_id=:id AND ann_date>:after',dict(id=object_id,after=after),order='ann_date'):
            yield [json.loads(r['source_facts']) for r in rows];after=rows[-1]['ann_date']
        if names:yield sorted(names,key=lambda r:(r['source_kind'],r['partition']))

    def validate_preview(self,object_id):
        row=self.controls.preview(object_id)
        if not row or row['state']!='ready' or not row['expires_at'] or row['expires_at']<=time.time():raise Blocked('preview_stale')
        with self.source.session(),read_budget(self.policy.sql_seconds):
            names=self.source.prepare_names()
            for batch in self.preview_manifest(object_id):self.source.validate_manifest([batch])
            version=source_version(self.source.scope,self.source.initials.version,self.preview_manifest(object_id,names))
        if version!=row['source_version']:raise Blocked('preview_stale')
        return row

    def close(self):
        if self.active:self.active.close();self.active=None


class AnnouncementSourceRuntime:
    def __init__(self,factory,policy):
        self.factory,self.policy=factory,policy;self.stop=threading.Event();self.wake=threading.Event()
        self.resources=None;self.error='archive_database_config_missing';self.last_gc=0;self.last_checked=0
        self.thread=threading.Thread(target=self._run,name='announcement-source',daemon=True)

    def start(self):self.thread.start();return self

    def _run(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                if self.resources is None:self.resources=self.factory(self.wake.set)
                service,preparation=self.resources
                if time.monotonic()-self.last_checked>=self.policy.source_check_seconds:
                    self.last_checked=time.monotonic();service.source.assert_valid(full=True)
                if time.monotonic()-self.last_gc>=self.policy.gc_seconds:
                    service.controls.gc();self.last_gc=time.monotonic()
                if preparation.next_unit():continue
            except (Blocked,OSError) as error:self.error=str(error)
            except Exception:self.error='query_prepare_failed'
            self.wake.wait(self.policy.control_poll_seconds if self.resources else self.policy.source_check_seconds)
        if self.resources:
            self.resources[1].close();self.resources[0].close()

    def service(self):
        if self.resources is None:raise Blocked(self.error)
        return self.resources[0]

    def close(self):
        self.stop.set();self.wake.set()
        if self.resources:self.resources[0].source.control.stop.set()
        self.thread.join(timeout=self.policy.sql_seconds+self.policy.api_seconds+1)
