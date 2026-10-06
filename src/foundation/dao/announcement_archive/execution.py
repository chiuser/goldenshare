"""Short archive control transactions and bounded frozen-set persistence."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
from src.foundation.clients.announcement_archive.core import Blocked,timestamp
from src.foundation.clients.announcement_archive.budget import remaining
from .ledger import Ledger

TERMINAL = {'completed','partial_failed','cancelled','blocked','stopped','interrupted'}


def remote_recheck_satisfied(info):
    return (info.get('reason') not in {'http_403','challenge_page'}
            or (info.get('check_kind')=='remoteSource' and info.get('check_state')=='passed'))


def payload_hash(kind,payload):
    return hashlib.sha256(json.dumps([kind,payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def unresolved_sql():
    return """r.outcome='failed' AND NOT EXISTS (
      SELECT 1 FROM run_artifacts fixed
      WHERE fixed.run_id IN (SELECT run_id FROM runs WHERE parent_run_id=:root OR run_id=:root)
        AND fixed.artifact_key=r.artifact_key AND fixed.outcome IN ('succeeded','skipped'))"""


class ArchiveStore:
    def __init__(self,binding): self.binding=binding

    @contextmanager
    def open(self, *, write=False, missing_ok=False):
        value=self.binding.read();path=self.binding.ledger_path(value)
        if not path.exists() and not path.is_symlink() and missing_ok:
            yield None;return
        ledger=None
        try:
            ledger=Ledger(path,value['volumeUuid'],value['rootRelativePath'],read_only=True,read_timeout_seconds=remaining(4))
            version=ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0]
            if write:
                if version!=3: raise Blocked('archive_schema_requires_explicit_migration')
                ledger.close();ledger=None
                ledger=Ledger(path,value['volumeUuid'],value['rootRelativePath'])
            deadline=time.monotonic()+remaining(4)
            ledger.conn.execute('PRAGMA busy_timeout='+str(int(remaining(4)*1000)))
            ledger.conn.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
            ledger.conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield ledger
            if write: ledger.conn.commit()
        except sqlite3.Error:
            if ledger: ledger.conn.rollback()
            raise Blocked('archive_ledger_failed') from None
        finally:
            if ledger: ledger.close()

    def receipt(self,key,kind,payload):
        with self.open(missing_ok=True) as ledger:
            if ledger is None:return None
            if ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0]!=3:return None
            row=ledger.conn.execute('SELECT * FROM command_receipts WHERE key=?',(key,)).fetchone()
            if row and (row['kind']!=kind or row['payload_hash']!=payload_hash(kind,payload)):
                raise Blocked('command_payload_conflict')
            return row['result_run_id'] if row else None

    def stop(self,run):
        with self.open(write=True) as ledger:
            row=ledger.conn.execute('SELECT phase,check_state FROM runs WHERE run_id=?',(run,)).fetchone()
            if not row:raise Blocked('run_not_found')
            if row['phase'] not in TERMINAL or row['check_state']=='checking':
                now=timestamp()
                ledger.conn.execute('UPDATE runs SET stop_requested_at=COALESCE(stop_requested_at,?),phase=CASE WHEN check_state=\'checking\' THEN phase ELSE \'stopping\' END,revision=revision+1 WHERE run_id=?',(now,run))

    def heartbeat(self,run,owner,*,refresh=True):
        with self.open(write=refresh) as ledger:
            row=ledger.conn.execute('SELECT stop_requested_at,owner_token FROM runs WHERE run_id=?',(run,)).fetchone()
            if row is None or row['owner_token']!=owner:raise Blocked('archive_owner_changed')
            if refresh:
                now=timestamp()
                ledger.conn.execute('UPDATE runs SET heartbeat_at=? WHERE run_id=?',(now,run))
                ledger.conn.execute('UPDATE archive_execution SET heartbeat=? WHERE active_run_id=? AND owner_token=?',(now,run,owner))
            return bool(row['stop_requested_at'])


class ExecutionLedger:
    def __init__(self,ledger):self.ledger,self.conn=ledger,ledger.conn

    def record_receipt(self,key,kind,payload,run):
        self.conn.execute('INSERT INTO command_receipts VALUES(?,?,?,?,?,?)',(key,kind,payload_hash(kind,payload),run,'accepted',timestamp()))

    def receipt(self,key,kind,payload):
        row=self.conn.execute('SELECT * FROM command_receipts WHERE key=?',(key,)).fetchone()
        if row and (row['kind']!=kind or row['payload_hash']!=payload_hash(kind,payload)):
            raise Blocked('command_payload_conflict')
        return row['result_run_id'] if row else None

    def run(self,run):
        row=self.conn.execute('SELECT * FROM runs WHERE run_id=?',(run,)).fetchone()
        if row is None:raise Blocked('run_not_found')
        return dict(row)

    def recover_abandoned(self):
        # Caller owns the local execution lock: no heartbeat-based takeover.
        now=timestamp()
        with self.conn:
            self.conn.execute("UPDATE attempt_log SET ended_at=?,outcome='interrupted',reason='process_exit_recovered' WHERE ended_at IS NULL",(now,))
            self.conn.execute("UPDATE run_sessions SET ended_at=?,reason='process_exit_recovered' WHERE ended_at IS NULL",(now,))
            self.conn.execute("UPDATE run_source_days SET state='cancelled',reason='process_exit_recovered',updated_at=? WHERE state='reading'",(now,))
            self.conn.execute("UPDATE runs SET phase='interrupted',reason='process_exit_recovered',finished_at=?,owner_token=NULL,current_artifact_key=NULL,wait_kind=NULL,next_request_at=NULL,revision=revision+1 WHERE phase IN ('enumerating','downloading','stopping')",(now,))
            self.conn.execute("UPDATE runs SET check_state='unknown',check_code='process_exit_recovered',check_updated_at=?,owner_token=NULL WHERE check_state='checking'",(now,))
            self.conn.execute('UPDATE run_artifacts SET claimed_owner=NULL,claimed_at=NULL WHERE outcome IS NULL AND claimed_owner IS NOT NULL')
            self.conn.execute('UPDATE archive_execution SET active_run_id=NULL,owner_token=NULL,heartbeat=?,revision=revision+1 WHERE singleton=1',(now,))

    def claim(self,run,*,resume=False,command=None):
        now=timestamp()
        with self.conn:
            slot=self.conn.execute('SELECT active_run_id FROM archive_execution WHERE singleton=1').fetchone()[0]
            if slot:raise Blocked('archive_already_running')
            self.conn.execute("UPDATE runs SET owner_token=?,heartbeat_at=?,stop_requested_at=NULL,finished_at=NULL,reason=NULL,phase='downloading',resume_count=resume_count+?,revision=revision+1 WHERE run_id=?",(self.ledger.owner_token,now,int(resume),run))
            seq=self.conn.execute('SELECT COALESCE(MAX(session_seq),0)+1 FROM run_sessions WHERE run_id=?',(run,)).fetchone()[0]
            self.conn.execute('INSERT INTO run_sessions VALUES(?,?,?,NULL,?,NULL)',(run,seq,now,self.ledger.owner_token))
            self.conn.execute('UPDATE archive_execution SET active_run_id=?,owner_token=?,heartbeat=?,revision=revision+1 WHERE singleton=1',(run,self.ledger.owner_token,now))
            if command:self.record_receipt(*command,run)

    def unresolved(self,run,after='',key=None,limit=500):
        info=self.run(run);root=info['parent_run_id'] or run
        sql='SELECT r.artifact_key FROM run_artifacts r WHERE r.run_id=:run AND '+unresolved_sql()+' AND r.artifact_key>:after'
        params=dict(run=run,root=root,after=after,limit=min(limit,500))
        if key is not None:sql+=' AND r.artifact_key=:key';params['key']=key
        return [r[0] for r in self.conn.execute(sql+' ORDER BY r.artifact_key LIMIT :limit',params).fetchmany(500)]

    def copy_retry(self,run,keys):
        if len(keys)>500:raise ValueError('retry_batch_limit')
        with self.conn:
            self.conn.executemany('INSERT INTO run_artifacts(run_id,artifact_key,representative_record_key) SELECT ?,artifact_key,representative_record_key FROM artifacts WHERE artifact_key=?',((run,k) for k in keys))
            self.conn.execute('UPDATE runs SET artifacts_total=artifacts_total+?,business_updated_at=?,revision=revision+1 WHERE run_id=?',(len(keys),timestamp(),run))

    def seal_retry(self,run):
        with self.conn:
            self.conn.execute("UPDATE runs SET enumeration_sealed=1,phase='downloading',business_updated_at=?,revision=revision+1 WHERE run_id=?",(timestamp(),run))

    def observe(self,run,fields):
        allowed={'bytes_received','bytes_total','wait_kind','next_request_at'}
        if not set(fields)<=allowed:raise ValueError('invalid_run_observation')
        with self.conn:
            self.conn.execute('UPDATE runs SET '+','.join(k+'=?' for k in fields)+',business_updated_at=?,revision=revision+1 WHERE run_id=?',(*fields.values(),timestamp(),run))
