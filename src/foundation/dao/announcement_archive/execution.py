"""Archive-scoped PG execution control and bounded frozen-set persistence."""
from contextlib import contextmanager
import hashlib
import json

from src.foundation.clients.announcement_archive.core import Blocked, timestamp
from .ledger import Ledger
from .pg_archive import ArchiveDAO

TERMINAL={'completed','partial_failed','cancelled','blocked','stopped','interrupted'}


def remote_recheck_satisfied(info):
    return info.get('reason') not in {'http_403','challenge_page'} or (info.get('check_kind')=='remoteSource' and info.get('check_state')=='passed')


def payload_hash(kind,payload):
    return hashlib.sha256(json.dumps([kind,payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def unresolved_sql():
    return """r.outcome='failed' AND NOT EXISTS (
      SELECT 1 FROM announcement_archive.run_artifacts fixed
      JOIN announcement_archive.runs family ON family.archive_id=fixed.archive_id AND family.run_id=fixed.run_id
      WHERE fixed.archive_id=r.archive_id AND (family.parent_run_id=:root OR family.run_id=:root)
        AND fixed.artifact_key=r.artifact_key AND fixed.outcome IN ('succeeded','skipped'))"""


class ArchiveStore:
    def __init__(self,binding,database):self.binding,self.database=binding,database

    @contextmanager
    def open(self, *, write=False, missing_ok=False):
        try:
            value=self.binding.read()
            ledger=Ledger(self.database,value['volumeUuid'],value['rootRelativePath'],read_only=not write)
        except Blocked as error:
            if not missing_ok or str(error) not in {'archive_binding_missing','archive_not_found'}:raise
            yield None;return
        try:yield ledger
        finally:ledger.close()

    def receipt(self,key,kind,payload):
        with self.open(missing_ok=True) as ledger:
            return ExecutionLedger(ledger).receipt(key,kind,payload) if ledger else None

    def stop(self,run):
        with self.open(write=True) as ledger,ledger.transaction() as conn:
            row=ledger.run(run,conn=conn,lock=True)
            if row['phase'] not in TERMINAL or row['check_state']=='checking':
                ledger.write(conn,"UPDATE announcement_archive.runs SET stop_requested_at=COALESCE(stop_requested_at,:now),phase=CASE WHEN check_state='checking' THEN phase ELSE 'stopping' END,revision=revision+1 WHERE archive_id=:a AND run_id=:run",dict(now=timestamp(),run=run))

    def heartbeat(self,run,owner,*,refresh=True):
        with self.open(write=refresh) as ledger,ledger.transaction(read_only=not refresh) as conn:
            row=ledger.run(run,conn=conn)
            if row['owner_token']!=owner:raise Blocked('archive_owner_changed')
            if refresh:
                p=dict(run=run,owner=owner,now=timestamp())
                ledger.write(conn,'UPDATE announcement_archive.runs SET heartbeat_at=:now WHERE archive_id=:a AND run_id=:run AND owner_token=:owner',p)
                ledger.write(conn,'UPDATE announcement_archive.archive_execution SET heartbeat=:now WHERE archive_id=:a AND active_run_id=:run AND owner_token=:owner',p)
            return bool(row['stop_requested_at'])


class ExecutionLedger:
    def __init__(self,ledger):self.ledger=ledger

    def record_receipt(self,key,kind,payload,run,*,conn=None,hashed=False):
        if key is None:return
        if conn is None:
            with self.ledger.transaction() as connection:
                return self.record_receipt(key,kind,payload,run,conn=connection,hashed=hashed)
        self.ledger.write(conn,"INSERT INTO announcement_archive.command_receipts(archive_id,key,kind,payload_hash,result_run_id,state,created_at) VALUES(:a,:key,:kind,:digest,:run,'accepted',:now)",dict(key=key,kind=kind,digest=payload if hashed else payload_hash(kind,payload),run=run,now=timestamp()))

    def receipt(self,key,kind,payload):
        if key is None:return None
        rows=self.ledger.rows('SELECT * FROM announcement_archive.command_receipts WHERE archive_id=:a AND key=:key',dict(key=key))
        if rows and (rows[0]['kind']!=kind or rows[0]['payload_hash']!=payload_hash(kind,payload)):raise Blocked('command_payload_conflict')
        return rows[0]['result_run_id'] if rows else None

    def run(self,run):return self.ledger.run(run)

    def recover_abandoned(self):
        # Caller owns volume + local execution lock. Heartbeat is never a takeover signal.
        l=self.ledger
        with l.transaction() as conn:
            ArchiveDAO(conn,l.archive_id,require_ready=False).get('archive_execution',{},lock=True)
            p=dict(now=timestamp())
            l.write(conn,"UPDATE announcement_archive.attempt_log SET ended_at=:now,outcome='interrupted',reason='process_exit_recovered' WHERE archive_id=:a AND ended_at IS NULL",p)
            l.write(conn,"UPDATE announcement_archive.run_sessions SET ended_at=:now,reason='process_exit_recovered' WHERE archive_id=:a AND ended_at IS NULL",p)
            l.write(conn,"UPDATE announcement_archive.run_source_days SET state='cancelled',reason='process_exit_recovered',updated_at=:now WHERE archive_id=:a AND state='reading'",p)
            l.write(conn,"UPDATE announcement_archive.runs SET phase='interrupted',reason='process_exit_recovered',finished_at=:now,owner_token=NULL,current_artifact_key=NULL,wait_kind=NULL,next_request_at=NULL,revision=revision+1 WHERE archive_id=:a AND phase IN ('enumerating','downloading','stopping')",p)
            l.write(conn,"UPDATE announcement_archive.runs SET check_state='unknown',check_code='process_exit_recovered',check_updated_at=:now,owner_token=NULL WHERE archive_id=:a AND check_state='checking'",p)
            l.write(conn,'UPDATE announcement_archive.run_artifacts SET claimed_owner=NULL,claimed_at=NULL WHERE archive_id=:a AND outcome IS NULL AND claimed_owner IS NOT NULL')
            l.write(conn,'UPDATE announcement_archive.archive_execution SET active_run_id=NULL,owner_token=NULL,heartbeat=:now,revision=revision+1 WHERE archive_id=:a',p)

    def claim(self,run,*,resume=False,command=None):
        l=self.ledger;now=timestamp()
        with l.transaction() as conn:
            ArchiveDAO(conn,l.archive_id,require_ready=False).claim_run(run,l.owner_token)
            p=dict(run=run,now=now,owner=l.owner_token,resume=int(resume))
            l.write(conn,"UPDATE announcement_archive.runs SET owner_token=:owner,heartbeat_at=:now,stop_requested_at=NULL,finished_at=NULL,reason=NULL,phase='downloading',resume_count=resume_count+:resume,revision=revision+1 WHERE archive_id=:a AND run_id=:run",p)
            seq=l.rows('SELECT COALESCE(MAX(session_seq),0)+1 AS seq FROM announcement_archive.run_sessions WHERE archive_id=:a AND run_id=:run',p,conn=conn)[0]['seq']
            l.write(conn,'INSERT INTO announcement_archive.run_sessions(archive_id,run_id,session_seq,started_at,owner_token) VALUES(:a,:run,:seq,:now,:owner)',dict(p,seq=seq))
            if command:self.record_receipt(*command,run,conn=conn)

    def unresolved(self,run,after='',key=None,limit=500):
        info=self.run(run);p=dict(run=run,root=info['parent_run_id'] or run,after=after,limit=min(limit,500),key=key)
        sql='SELECT r.artifact_key FROM announcement_archive.run_artifacts r WHERE r.archive_id=:a AND r.run_id=:run AND '+unresolved_sql()+' AND r.artifact_key>:after'
        if key is not None:sql+=' AND r.artifact_key=:key'
        return [r['artifact_key'] for r in self.ledger.rows(sql+' ORDER BY r.artifact_key LIMIT :limit',p)]

    def copy_retry(self,run,keys):
        if len(keys)>500:raise ValueError('retry_batch_limit')
        l=self.ledger
        with l.transaction() as conn:
            added=0
            for key in keys:
                added+=l.write(conn,'INSERT INTO announcement_archive.run_artifacts(archive_id,run_id,artifact_key,representative_record_key) SELECT :a,:run,artifact_key,representative_record_key FROM announcement_archive.artifacts WHERE archive_id=:a AND artifact_key=:key ON CONFLICT DO NOTHING',dict(run=run,key=key)).rowcount
            l.write(conn,'UPDATE announcement_archive.runs SET artifacts_total=artifacts_total+:count,business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run',dict(run=run,count=added,now=timestamp()))

    def seal_retry(self,run):
        with self.ledger.transaction() as conn:
            self.ledger.write(conn,"UPDATE announcement_archive.runs SET enumeration_sealed=1,phase='downloading',business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run",dict(run=run,now=timestamp()))

    def observe(self,run,fields):
        if not fields or not set(fields)<={'bytes_received','bytes_total','wait_kind','next_request_at'}:raise ValueError('invalid_run_observation')
        with self.ledger.transaction() as conn:
            self.ledger.write(conn,'UPDATE announcement_archive.runs SET '+','.join(k+'=:'+k for k in fields)+',business_updated_at=:now,revision=revision+1 WHERE archive_id=:a AND run_id=:run AND owner_token=:owner',dict(fields,now=timestamp(),run=run,owner=self.ledger.owner_token))

    def begin_check(self,run,kind):
        l=self.ledger
        with l.transaction() as conn:
            ArchiveDAO(conn,l.archive_id,require_ready=False).claim_run(run,l.owner_token)
            l.write(conn,"UPDATE announcement_archive.runs SET check_state='checking',check_kind=:kind,check_code=NULL,check_updated_at=:now,owner_token=:owner,stop_requested_at=NULL WHERE archive_id=:a AND run_id=:run",dict(run=run,kind=kind,now=timestamp(),owner=l.owner_token))

    def finish_check(self,run,outcome,reason):
        l=self.ledger
        with l.transaction() as conn:
            p=dict(run=run,outcome=outcome,reason=reason,now=timestamp(),owner=l.owner_token)
            l.write(conn,'UPDATE announcement_archive.runs SET check_state=:outcome,check_code=:reason,check_updated_at=:now,owner_token=NULL,wait_kind=NULL,next_request_at=NULL WHERE archive_id=:a AND run_id=:run AND owner_token=:owner',p)
            l.write(conn,'UPDATE announcement_archive.archive_execution SET active_run_id=NULL,owner_token=NULL,revision=revision+1 WHERE archive_id=:a AND active_run_id=:run AND owner_token=:owner',p)
