"""PG archive business facts; each public operation owns a short transaction."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
import json
import unicodedata
import uuid

from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import (
    SOURCE_CONTRACT_VERSION, Blocked, DownloadPolicy, identity, source_projection, timestamp,
)
from src.foundation.clients.announcement_archive.budget import remaining
from .pg_archive import ArchiveDAO, register_archive
from .pg_schema import VERSION, DDL_SHA256, validate_schema


class Ledger:
    def __init__(self, database, volume_uuid, relative_root, *, read_only=False, initialize=False):
        self.database, self.archive_id = database, identity([volume_uuid, relative_root])
        self.read_only, self.owner_token = read_only, uuid.uuid4().hex
        with database.transaction(read_only=not initialize) as conn:
            self.sql_budget(conn)
            validate_schema(conn)
            dao=ArchiveDAO(conn,self.archive_id,require_ready=False)
            if initialize and dao.get('archives',{}) is None:
                register_archive(conn,volume_uuid,relative_root)
            self.archive=dao.get('archives',{})
            if not self.archive:raise Blocked('archive_not_found')
            if (self.archive['volume_uuid'],self.archive['root_relative_path'])!=(volume_uuid,relative_root):
                raise Blocked('archive_identity_mismatch')
            if self.archive['import_state']!='ready':raise Blocked('archive_import_incomplete')

    @property
    def storage(self):
        return dict(kind='postgresql',database=self.database.policy.database,schema='announcement_archive',
                    archiveId=self.archive_id,schemaVersion=VERSION)

    @contextmanager
    def transaction(self, *, read_only=False):
        if self.read_only and not read_only:raise Blocked('archive_read_only')
        with self.database.transaction(read_only=read_only) as conn:
            self.sql_budget(conn)
            info=conn.execute(text('SELECT a.import_state,s.version,s.ddl_sha256 FROM announcement_archive.archives a '
                'CROSS JOIN announcement_archive.schema_info s WHERE a.archive_id=:a AND s.singleton=1'),{'a':self.archive_id}).first()
            if not info or tuple(info)!=('ready',VERSION,DDL_SHA256):raise Blocked('archive_schema_invalid')
            yield conn

    def sql_budget(self,conn):
        seconds=remaining(self.database.policy.statement_milliseconds/1000)
        conn.execute(text("SELECT set_config('statement_timeout',:ms,true)"),dict(ms=str(max(1,int(seconds*1000)))))

    def rows(self, sql, params=None, *, conn=None):
        """Native PG queries only. SQL at every call site includes its archive predicate."""
        remaining(self.database.policy.statement_milliseconds/1000)
        values=dict(params or {},a=self.archive_id)
        if conn is not None:return [dict(r) for r in conn.execute(text(sql),values).mappings()]
        with self.transaction(read_only=True) as connection:
            return self.rows(sql,params,conn=connection)

    def write(self, conn, sql, params=None):
        remaining(self.database.policy.statement_milliseconds/1000)
        return conn.execute(text(sql),dict(params or {},a=self.archive_id))

    def run(self, run, *, conn=None, lock=False):
        rows=self.rows('SELECT * FROM announcement_archive.runs WHERE archive_id=:a AND run_id=:run'
                       +(' FOR UPDATE' if lock else ''),dict(run=run),conn=conn)
        if not rows:raise Blocked('run_not_found')
        return rows[0]

    def active(self):
        return self.rows('SELECT active_run_id FROM announcement_archive.archive_execution WHERE archive_id=:a')[0]['active_run_id']

    def pending(self, run):
        return bool(self.rows('SELECT 1 FROM announcement_archive.run_artifacts WHERE archive_id=:a AND run_id=:run AND outcome IS NULL LIMIT 1',dict(run=run)))

    def begin_run(self, options, scope, policy=None, *, command=None, details=None):
        from .execution import ExecutionLedger
        run=uuid.uuid4().hex;now=timestamp()
        with self.transaction() as conn:
            slot=ArchiveDAO(conn,self.archive_id,require_ready=False).get('archive_execution',{},lock=True)
            if slot['active_run_id']:raise Blocked('archive_already_running')
            self.write(conn,'INSERT INTO announcement_archive.runs (archive_id,run_id,start_date,end_date,interval_seconds,source_scope,phase,updated_at,source_contract_version,source_policy,days_total,legacy_upper_id,legacy_after_id,created_at,started_at,owner_token,heartbeat_at,business_updated_at) '
                "VALUES(:a,:run,:start,:end,:interval,:scope,'enumerating',:now,:version,:policy,:days,NULL,NULL,:now,:now,:owner,:now,:now)",
                dict(run=run,start=options.start_date.isoformat(),end=options.end_date.isoformat(),interval=options.interval_seconds,scope=scope,now=now,version=SOURCE_CONTRACT_VERSION,policy=json.dumps(asdict(policy or DownloadPolicy()),sort_keys=True),days=(options.end_date-options.start_date).days+1,owner=self.owner_token))
            self.write(conn,'INSERT INTO announcement_archive.run_sessions(archive_id,run_id,session_seq,started_at,owner_token) VALUES(:a,:run,1,:now,:owner)',dict(run=run,now=now,owner=self.owner_token))
            self.write(conn,'UPDATE announcement_archive.archive_execution SET active_run_id=:run,owner_token=:owner,heartbeat=:now,revision=revision+1 WHERE archive_id=:a',dict(run=run,owner=self.owner_token,now=now))
            if details:
                if not set(details)<={'batch_kind','parent_run_id','retry_of_run_id','preview_id','actor_id','records_read','missing_url_count','days_total'}:raise ValueError('invalid_run_details')
                self.write(conn,'UPDATE announcement_archive.runs SET '+','.join(k+'=:'+k for k in details)+' WHERE archive_id=:a AND run_id=:run',dict(details,run=run))
            if command:
                key,kind,digest=command
                ExecutionLedger(self).record_receipt(key,kind,digest,run,conn=conn,hashed=True)
        return run

    def begin_day(self, run, day):
        with self.transaction() as conn:
            current=self.run(run,conn=conn,lock=True)
            if (current['phase']!='enumerating' or current['enumeration_sealed'] or current['days_completed']>=current['days_total'] or (date.fromisoformat(current['start_date'])+timedelta(days=current['days_completed'])).isoformat()!=day):raise Blocked('source_day_outside_enumeration')
            self.write(conn,"INSERT INTO announcement_archive.run_source_days(archive_id,run_id,ann_date,state,updated_at) VALUES(:a,:run,:day,'reading',:now)",dict(run=run,day=day,now=timestamp()))
            self.write(conn,'UPDATE announcement_archive.runs SET current_day=:day,updated_at=:now WHERE archive_id=:a AND run_id=:run',dict(run=run,day=day,now=timestamp()))

    def describe_day(self, run, day, facts):
        with self.transaction() as conn:
            self.write(conn,"UPDATE announcement_archive.run_source_days SET opened_dev=:opened_dev,opened_ino=:opened_ino,size=:size,sha256=:sha256,footer_count=:footer_count,updated_at=:now WHERE archive_id=:a AND run_id=:run AND ann_date=:day AND state='reading'",dict(facts,run=run,day=day,now=timestamp()))

    def ingest(self, run, scope, day, rows, batch_size=500):
        if len(rows)>min(batch_size,500):raise Blocked('source_batch_limit')
        with self.transaction() as conn:
            current=self.run(run,conn=conn,lock=True)
            units=self.rows('SELECT * FROM announcement_archive.run_source_days WHERE archive_id=:a AND run_id=:run AND ann_date=:day',dict(run=run,day=day),conn=conn)
            if current['phase']!='enumerating' or current['enumeration_sealed'] or current['source_scope']!=scope or not units or units[0]['state']!='reading':raise Blocked('source_batch_outside_enumeration')
            added=missing=0
            for row in rows:
                record_key,iso_day,key=source_projection(row,day)
                params=dict(run=run,scope=scope,record=record_key,key=key,day=iso_day,code=row['ts_code'],title=row['title'],url=(row['url'] or '').strip(),now=timestamp(),metadata=json.dumps(row,ensure_ascii=False,separators=(',',':')))
                previous=self.rows('SELECT last_seen_run FROM announcement_archive.source_records WHERE archive_id=:a AND source_scope=:scope AND record_key=:record',params,conn=conn)
                if previous and previous[0]['last_seen_run']==run:raise Blocked('source_duplicate_record')
                if key:
                    self.write(conn,'INSERT INTO announcement_archive.artifacts(archive_id,artifact_key,ann_date,ts_code,title,url,updated_at,created_run_id,representative_record_key) VALUES(:a,:key,:day,:code,:title,:url,:now,:run,:record) ON CONFLICT(archive_id,artifact_key) DO NOTHING',params)
                    self._representative(conn,run,key,record_key,row['title'])
                self.write(conn,'INSERT INTO announcement_archive.source_records(archive_id,source_scope,record_key,legacy_raw_id,metadata,artifact_key,first_seen_run,last_seen_run) VALUES(:a,:scope,:record,NULL,:metadata,:key,:run,:run) ON CONFLICT(archive_id,source_scope,record_key) DO UPDATE SET last_seen_run=excluded.last_seen_run',params)
                if key:
                    added+=self.write(conn,'INSERT INTO announcement_archive.run_artifacts(archive_id,run_id,artifact_key,representative_record_key) SELECT :a,:run,artifact_key,representative_record_key FROM announcement_archive.artifacts WHERE archive_id=:a AND artifact_key=:key ON CONFLICT DO NOTHING',params).rowcount
                else:missing+=1
            params=dict(run=run,day=day,count=len(rows),added=added,missing=missing,now=timestamp())
            self.write(conn,'UPDATE announcement_archive.runs SET records_read=records_read+:count,artifacts_total=artifacts_total+:added,missing_url_count=missing_url_count+:missing,updated_at=:now,business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run',params)
            self.write(conn,'UPDATE announcement_archive.run_source_days SET records_committed=records_committed+:count,updated_at=:now WHERE archive_id=:a AND run_id=:run AND ann_date=:day',params)

    def _representative(self, conn, run, key, record, title):
        from src.foundation.clients.announcement_archive.files import title_name
        from src.foundation.clients.announcement_archive.core import FileFailed
        current=self.artifact(key,conn=conn)
        if current['created_run_id']!=run or current['relative_path'] is not None:return
        def rank(value,record):
            try:title_name(value,'',DownloadPolicy.filename_bytes);return (0,record)
            except FileFailed:return (1,record)
        if rank(title,record)<rank(current['title'],current['representative_record_key']):
            self.write(conn,'UPDATE announcement_archive.artifacts SET title=:title,representative_record_key=:record WHERE archive_id=:a AND artifact_key=:key',dict(title=title,record=record,key=key))
            self.write(conn,'UPDATE announcement_archive.run_artifacts SET representative_record_key=:record WHERE archive_id=:a AND run_id=:run AND artifact_key=:key',dict(record=record,run=run,key=key))

    def complete_day(self, run, day, facts):
        with self.transaction() as conn:
            rows=self.rows('SELECT * FROM announcement_archive.run_source_days WHERE archive_id=:a AND run_id=:run AND ann_date=:day FOR UPDATE',dict(run=run,day=day),conn=conn)
            if not rows or rows[0]['state']!='reading' or rows[0]['records_committed']!=facts['footer_count'] or any(rows[0][k]!=facts[k] for k in ('opened_dev','opened_ino','size','sha256','footer_count')):raise Blocked('source_day_reconciliation')
            params=dict(run=run,day=day,now=timestamp())
            self.write(conn,"UPDATE announcement_archive.run_source_days SET state='completed',updated_at=:now WHERE archive_id=:a AND run_id=:run AND ann_date=:day",params)
            self.write(conn,'UPDATE announcement_archive.runs SET days_completed=days_completed+1,updated_at=:now,business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run',params)

    def seal(self, run):
        with self.transaction() as conn:
            info=self.run(run,conn=conn,lock=True)
            invalid=self.rows("SELECT 1 FROM announcement_archive.run_source_days WHERE archive_id=:a AND run_id=:run AND (state<>'completed' OR footer_count IS NULL OR records_committed<>footer_count) LIMIT 1",dict(run=run),conn=conn)
            if info['phase']!='enumerating' or info['days_completed']!=info['days_total'] or invalid:raise Blocked('source_enumeration_incomplete')
            self.write(conn,"UPDATE announcement_archive.runs SET enumeration_sealed=1,phase='downloading',updated_at=:now,business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run",dict(run=run,now=timestamp()))

    def phase(self, run, phase, reason=None):
        from .execution import TERMINAL
        with self.transaction() as conn:
            p=dict(run=run,phase=phase,reason=reason,now=timestamp())
            if phase in ('cancelled','blocked'):
                self.write(conn,"UPDATE announcement_archive.run_source_days SET state=:phase,reason=:reason,updated_at=:now WHERE archive_id=:a AND run_id=:run AND state='reading'",p)
            self.write(conn,'UPDATE announcement_archive.runs SET phase=:phase,reason=:reason,updated_at=:now WHERE archive_id=:a AND run_id=:run',p)
            if phase=='blocked' and reason in {'http_403','challenge_page'}:
                self.write(conn,'UPDATE announcement_archive.runs SET check_state=NULL,check_kind=NULL,check_code=NULL,check_updated_at=NULL WHERE archive_id=:a AND run_id=:run',p)
            if phase in TERMINAL:
                self.write(conn,"UPDATE announcement_archive.runs SET finished_at=:now,current_artifact_key=CASE WHEN phase='blocked' THEN current_artifact_key ELSE NULL END,wait_kind=NULL,next_request_at=NULL,revision=revision+1 WHERE archive_id=:a AND run_id=:run",p)
                self.write(conn,'UPDATE announcement_archive.attempt_log SET ended_at=:now,outcome=:phase,reason=:reason WHERE archive_id=:a AND run_id=:run AND ended_at IS NULL',p)
                self.write(conn,'UPDATE announcement_archive.run_sessions SET ended_at=:now,reason=:reason WHERE archive_id=:a AND run_id=:run AND ended_at IS NULL',dict(p,reason=reason or phase))
                self.write(conn,'UPDATE announcement_archive.archive_execution SET active_run_id=NULL,owner_token=NULL,heartbeat=:now,revision=revision+1 WHERE archive_id=:a AND active_run_id=:run',p)
                self.write(conn,'UPDATE announcement_archive.run_artifacts SET claimed_owner=NULL,claimed_at=NULL WHERE archive_id=:a AND run_id=:run AND outcome IS NULL',p)

    def next_task(self, run):
        with self.transaction() as conn:
            info=self.run(run,conn=conn,lock=True)
            if not info['enumeration_sealed'] or info['phase']!='downloading':raise Blocked('source_enumeration_not_sealed')
            rows=self.rows('SELECT a.* FROM announcement_archive.artifacts a JOIN announcement_archive.run_artifacts r USING(archive_id,artifact_key) WHERE r.archive_id=:a AND r.run_id=:run AND r.outcome IS NULL ORDER BY r.artifact_key LIMIT 1',dict(run=run),conn=conn)
            if not rows:return None
            task=rows[0];p=dict(run=run,key=task['artifact_key'],owner=self.owner_token,now=timestamp())
            self.write(conn,'UPDATE announcement_archive.run_artifacts SET claimed_owner=:owner,claimed_at=:now WHERE archive_id=:a AND run_id=:run AND artifact_key=:key AND outcome IS NULL',p)
            self.write(conn,'UPDATE announcement_archive.runs SET current_artifact_key=:key,attempt_number=0,bytes_received=0,bytes_total=NULL,wait_kind=NULL,next_request_at=NULL WHERE archive_id=:a AND run_id=:run',p)
            return task

    def artifact(self, key, *, conn=None):
        rows=self.rows('SELECT * FROM announcement_archive.artifacts WHERE archive_id=:a AND artifact_key=:key',dict(key=key),conn=conn)
        if not rows:raise Blocked('artifact_not_found')
        return rows[0]

    def assign_path(self, key, relative):
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.artifacts SET relative_path=:relative,path_fold=:fold,updated_at=:now WHERE archive_id=:a AND artifact_key=:key',dict(relative=relative,fold=unicodedata.normalize('NFC',relative).casefold() if relative else None,now=timestamp(),key=key))

    def path_taken(self, relative):
        return bool(self.rows('SELECT 1 FROM announcement_archive.artifacts WHERE archive_id=:a AND path_fold=:fold',dict(fold=unicodedata.normalize('NFC',relative).casefold())))

    def state(self, key, state, error=None):
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.artifacts SET state=:state,error=:error,updated_at=:now WHERE archive_id=:a AND artifact_key=:key',dict(key=key,state=state,error=error,now=timestamp()))

    def attempt(self, run, key):
        with self.transaction() as conn:
            self.run(run,conn=conn,lock=True)
            p=dict(run=run,key=key,now=timestamp())
            self.write(conn,'UPDATE announcement_archive.artifacts SET attempts=attempts+1,updated_at=:now WHERE archive_id=:a AND artifact_key=:key',p)
            self.write(conn,'UPDATE announcement_archive.run_artifacts SET attempts=attempts+1 WHERE archive_id=:a AND run_id=:run AND artifact_key=:key',p)
            seq=self.rows('SELECT COALESCE(MAX(attempt_seq),0)+1 AS seq FROM announcement_archive.attempt_log WHERE archive_id=:a AND run_id=:run AND artifact_key=:key',p,conn=conn)[0]['seq']
            session=self.rows('SELECT MAX(session_seq) AS seq FROM announcement_archive.run_sessions WHERE archive_id=:a AND run_id=:run',p,conn=conn)[0]['seq']
            self.write(conn,'INSERT INTO announcement_archive.attempt_log(archive_id,run_id,artifact_key,attempt_seq,session_seq,started_at) VALUES(:a,:run,:key,:seq,:session,:now)',dict(p,seq=seq,session=session))
            self.write(conn,'UPDATE announcement_archive.runs SET attempt_number=(SELECT COUNT(*) FROM announcement_archive.attempt_log WHERE archive_id=:a AND run_id=:run AND artifact_key=:key AND session_seq=:session) WHERE archive_id=:a AND run_id=:run',dict(p,session=session))

    def finish_attempt(self, run, key, outcome, reason=None, http_status=None, received=0):
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.attempt_log SET ended_at=:now,outcome=:outcome,reason=:reason,http_status=:status,bytes=:bytes WHERE archive_id=:a AND run_id=:run AND artifact_key=:key AND ended_at IS NULL',dict(run=run,key=key,outcome=outcome,reason=reason,status=http_status,bytes=received,now=timestamp()))

    def attempted_success(self, run, key):
        return bool(self.rows("SELECT 1 FROM announcement_archive.attempt_log WHERE archive_id=:a AND run_id=:run AND artifact_key=:key AND outcome='succeeded' AND ended_at IS NOT NULL LIMIT 1",dict(run=run,key=key)))

    def prepared(self, key, size, digest):
        with self.transaction() as conn:
            self.write(conn,"UPDATE announcement_archive.artifacts SET state='prepared',size=:size,sha256=:digest,error=NULL,updated_at=:now WHERE archive_id=:a AND artifact_key=:key",dict(key=key,size=size,digest=digest,now=timestamp()))

    def result(self, run, key, outcome):
        column={'succeeded':'succeeded_count','skipped':'skipped_count','failed':'failed_count'}[outcome]
        with self.transaction() as conn:
            self.run(run,conn=conn,lock=True)
            p=dict(run=run,key=key,outcome=outcome,now=timestamp())
            previous=self.rows('SELECT outcome FROM announcement_archive.run_artifacts WHERE archive_id=:a AND run_id=:run AND artifact_key=:key FOR UPDATE',p,conn=conn)[0]['outcome']
            if previous==outcome:return
            if previous:raise Blocked('run_result_already_final')
            self.write(conn,'UPDATE announcement_archive.run_artifacts SET outcome=:outcome,claimed_owner=NULL,claimed_at=NULL WHERE archive_id=:a AND run_id=:run AND artifact_key=:key',p)
            self.write(conn,f'UPDATE announcement_archive.runs SET {column}={column}+1,completed_count=completed_count+1,updated_at=:now,business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run',p)

    def file_failure(self, run, key, reason):
        with self.transaction() as conn:
            self.run(run,conn=conn,lock=True)
            p=dict(run=run,key=key,reason=reason,now=timestamp())
            session=self.rows('SELECT MAX(session_seq) AS seq FROM announcement_archive.run_sessions WHERE archive_id=:a AND run_id=:run',p,conn=conn)[0]['seq'];p['session']=session
            if not self.rows('SELECT 1 FROM announcement_archive.attempt_log WHERE archive_id=:a AND run_id=:run AND artifact_key=:key AND session_seq=:session AND reason=:reason',p,conn=conn):
                seq=self.rows('SELECT COALESCE(MAX(attempt_seq),0)+1 AS seq FROM announcement_archive.attempt_log WHERE archive_id=:a AND run_id=:run AND artifact_key=:key',p,conn=conn)[0]['seq']
                self.write(conn,"INSERT INTO announcement_archive.attempt_log(archive_id,run_id,artifact_key,attempt_seq,session_seq,started_at,ended_at,outcome,reason,bytes) VALUES(:a,:run,:key,:seq,:session,:now,:now,'failed',:reason,0)",dict(p,seq=seq))

    def stats(self, run):
        c=self.run(run);total,done=c['artifacts_total'],c['completed_count']
        return dict(records=c['records_read'],total=total,completed=done,succeeded=c['succeeded_count'],skipped=c['skipped_count'],failed=c['failed_count'],percent=(round(100*done/total,2) if total else 100) if c['enumeration_sealed'] else None,skipped_missing_url=c['missing_url_count'],current_day=c['current_day'],days_total=c['days_total'],days_completed=c['days_completed'])

    def cooldown(self):
        return self.rows('SELECT * FROM announcement_archive.cooldown WHERE archive_id=:a')[0]

    def request_started(self):
        # This committed write is the gate before every HTTP request (including redirects/probes).
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.cooldown SET request_in_flight=1 WHERE archive_id=:a')

    def request_finished(self, now, until, reason):
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.cooldown SET last_request_finished_at=:now,next_request_not_before=greatest(next_request_not_before,:until),request_in_flight=0,reason=:reason WHERE archive_id=:a',dict(now=now,until=until,reason=reason))

    def defer(self, until, reason):
        with self.transaction() as conn:
            self.write(conn,'UPDATE announcement_archive.cooldown SET next_request_not_before=greatest(next_request_not_before,:until),reason=:reason WHERE archive_id=:a',dict(until=until,reason=reason))

    def close(self):
        # Connections belong to each completed transaction, the composition root owns the pool.
        pass
