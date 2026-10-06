"""Task facts and bounded history/file pages from the read-only local ledger."""
import json
from datetime import datetime,timezone
from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.dao.announcement_archive.execution import TERMINAL,unresolved_sql,remote_recheck_satisfied
from src.biz.services.wealth.data_center.errors import mapped_download_error


class RunQuery:
    def __init__(self,store):self.store=store

    def _info(self,ledger,run):
        row=ledger.conn.execute('SELECT * FROM runs WHERE run_id=?',(run,)).fetchone()
        if row is None:raise Blocked('run_not_found')
        return dict(row)

    def _active(self,ledger,version):
        return ledger.conn.execute('SELECT active_run_id FROM archive_execution WHERE singleton=1').fetchone()[0] if version==3 else None

    def _unresolved(self,ledger,info,version):
        if version<3:return 0
        return ledger.conn.execute('SELECT COUNT(*) FROM run_artifacts r WHERE r.run_id=:run AND '+unresolved_sql(),dict(run=info['run_id'],root=info.get('parent_run_id') or info['run_id'])).fetchone()[0]

    def _file(self,ledger,info,row,version,active=None):
        value=dict(row);key=value['artifact_key'];code=value['ts_code'];name=code or '未知公司'
        if version>=3 and value.get('representative_record_key'):
            source=ledger.conn.execute('SELECT metadata FROM source_records WHERE source_scope=? AND record_key=?',(info['source_scope'],value['representative_record_key'])).fetchone()
            if source:
                try:name=json.loads(source[0]).get('name') or name
                except (ValueError,TypeError):raise Blocked('archive_ledger_failed') from None
        attempt=None
        if version==3:
            attempt=ledger.conn.execute('SELECT reason,http_status FROM attempt_log WHERE run_id=? AND artifact_key=? AND reason IS NOT NULL ORDER BY attempt_seq DESC LIMIT 1',(info['run_id'],key)).fetchone()
        error=attempt['reason'] if attempt else value.get('error')
        last=None
        if value['outcome']=='failed':
            public=mapped_download_error(error or 'file_failed')
            last=dict(code=public.code,message=public.message,httpStatus=attempt['http_status'] if attempt else None)
        result={'skipped':'reused'}.get(value['outcome'],value['outcome']) or ('processing' if value.get('claimed_owner') and active==info['run_id'] else 'pending')
        unresolved=False
        if version==3 and value['outcome']=='failed':
            unresolved=bool(ledger.conn.execute('SELECT 1 FROM run_artifacts r WHERE r.run_id=:run AND r.artifact_key=:key AND '+unresolved_sql(),dict(run=info['run_id'],key=key,root=info.get('parent_run_id') or info['run_id'])).fetchone())
        return dict(artifactKey=key,representativeRecordKey=value.get('representative_record_key'),annDate=value['ann_date'],tsCode=code,companyName=name,title=value['title'],result=result,attempts=value['run_attempts'],lastError=last,canRetry=version==3 and active is None and info['phase'] in TERMINAL and bool(info.get('enumeration_sealed')) and info.get('source_contract_version')==1 and unresolved)

    def _task(self,ledger,info,version,active):
        info=dict(info);run=info['run_id'];root=info.get('parent_run_id') or run
        phase={'enumerating':'preparing'}.get(info['phase'],info['phase'])
        if phase not in {'preparing','downloading','stopping','completed','partial_failed','cancelled','blocked','stopped','interrupted'}:phase='interrupted'
        sealed=bool(info.get('enumeration_sealed'));total=info['artifacts_total'] if sealed else None
        done=info['completed_count'];remaining=total-done if total is not None else None
        if remaining is not None and remaining<0:raise Blocked('archive_ledger_failed')
        failures=self._unresolved(ledger,info,version)
        complete=sealed and version==3 and bool(info.get('source_policy')) and info.get('source_contract_version')==1 and info.get('source_kind')=='dg_raw_parquet' and (info.get('batch_kind')=='retry' or info.get('days_completed')==info.get('days_total'))
        pending=bool(ledger.conn.execute('SELECT 1 FROM run_artifacts WHERE run_id=? AND outcome IS NULL LIMIT 1',(run,)).fetchone())
        current=None
        if version==3 and info.get('current_artifact_key'):
            row=ledger.conn.execute('SELECT a.*,r.outcome,r.attempts AS run_attempts,r.representative_record_key,r.claimed_owner FROM artifacts a JOIN run_artifacts r USING(artifact_key) WHERE r.run_id=? AND r.artifact_key=?',(run,info['current_artifact_key'])).fetchone()
            if row:
                file=self._file(ledger,info,row,version,active)
                current=dict(artifactKey=file['artifactKey'],annDate=file['annDate'],tsCode=file['tsCode'],companyName=file['companyName'],title=file['title'],attemptNumber=info['attempt_number'],maxAttempts=3,bytesReceived=info['bytes_received'],bytesTotal=info['bytes_total'],transferState='verifying' if info['wait_kind']=='verifying' or row['state']=='prepared' else 'receiving')
        wait=None
        if info.get('wait_kind') in {'interval','backoff','cooldown'} and info.get('next_request_at'):
            wait=dict(kind=info['wait_kind'],until=datetime.fromtimestamp(info['next_request_at'],timezone.utc).isoformat())
        check=None
        if info.get('check_state'):
            public=mapped_download_error(info['check_code']) if info.get('check_code') else None
            check=dict(state=info['check_state'],kind=info['check_kind'],code=public.code if public else None,updatedAt=info['check_updated_at'])
        reason=mapped_download_error(info['reason']) if phase=='blocked' and info.get('reason') else None
        return dict(runId=run,rootRunId=root,retryOfRunId=info.get('retry_of_run_id'),batchKind=info.get('batch_kind','date'),phase=phase,revision=info.get('revision',0),startDate=info['start_date'] or '',endDate=info['end_date'] or '',intervalSeconds=info['interval_seconds'] or 0,archiveLocation=str(self.store.binding.output),createdAt=info.get('created_at') or info.get('updated_at') or '',startedAt=info.get('started_at'),finishedAt=info.get('finished_at'),recordCount=info['records_read'],missingUrlCount=info.get('missing_url_count',0),total=total,processed=done,succeeded=info['succeeded_count'],reused=info['skipped_count'],failed=info['failed_count'],remaining=remaining,percent=(round(100*done/total,2) if total else 100) if total is not None else None,unresolvedFailureCount=failures,preparation=dict(datesScanned=info.get('days_completed',0),datesTotal=info.get('days_total') or 0,currentDate=info.get('current_day')),current=current,wait=wait,businessUpdatedAt=info.get('business_updated_at') or info.get('updated_at') or '',heartbeatAt=info.get('heartbeat_at') or info.get('updated_at') or '',etaSeconds=None,blockedReason=dict(code=reason.code,message=reason.message) if reason else None,actions=dict(canStop=active==run and (phase in {'preparing','downloading','stopping'} or info.get('check_state')=='checking'),canContinue=active is None and complete and pending and remote_recheck_satisfied(info) and phase in {'stopped','blocked','interrupted'},canRetryFailed=active is None and complete and failures>0 and phase in TERMINAL,canCreateNew=active is None,canRecheck=version==3 and active is None and phase=='blocked',reason=None if complete else '历史任务不支持精确恢复，可新建日期下载'),check=check)

    def task(self,run):
        with self.store.open() as ledger:
            version=ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0]
            return self._task(ledger,self._info(ledger,run),version,self._active(ledger,version))

    def history(self,cursor=None,limit=20,related_to=None):
        with self.store.open(missing_ok=True) as ledger:
            if ledger is None:return dict(currentRunId=None,items=[],nextCursor=None)
            version=ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0];active=self._active(ledger,version)
            values=[int(cursor) if cursor else 9223372036854775807]
            related=''
            if related_to:
                info=self._info(ledger,related_to);root=info.get('parent_run_id') or related_to
                if version==3:related=' AND (parent_run_id=? OR run_id=?)';values.extend([root,root])
                else:related=' AND run_id=?';values.append(related_to)
            rows=ledger.conn.execute('SELECT rowid AS ledger_rowid,* FROM runs WHERE rowid<?'+related+' ORDER BY rowid DESC LIMIT ?',(*values,limit+1)).fetchmany(limit+1)
            # History reads counters only; per-run failure qualification belongs to the selected detail.
            items=[dict(runId=r['run_id'],startDate=r['start_date'],endDate=r['end_date'],phase={'enumerating':'preparing'}.get(r['phase'],r['phase']),createdAt=dict(r).get('created_at') or r['updated_at'],total=r['artifacts_total'],succeeded=r['succeeded_count'],reused=r['skipped_count'],failed=r['failed_count'],rootRunId=dict(r).get('parent_run_id') or r['run_id'],retryOfRunId=dict(r).get('retry_of_run_id')) for r in rows[:limit]]
            return dict(currentRunId=active,items=items,nextCursor=str(rows[limit-1]['ledger_rowid']) if len(rows)>limit else None)

    def files(self,run,result='all',cursor=None,limit=50):
        with self.store.open() as ledger:
            version=ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0];info=self._info(ledger,run);active=self._active(ledger,version)
            fields=',r.representative_record_key,r.claimed_owner' if version==3 else ''
            sql='SELECT a.*,r.outcome,r.attempts AS run_attempts'+fields+' FROM run_artifacts r JOIN artifacts a USING(artifact_key) WHERE r.run_id=? AND r.artifact_key>?'
            args=[run,cursor or '']
            if result!='all':
                outcome={'reused':'skipped'}.get(result,result)
                if result=='pending':sql+=' AND r.outcome IS NULL'
                else:sql+=' AND r.outcome=?';args.append(outcome)
            rows=ledger.conn.execute(sql+' ORDER BY r.artifact_key LIMIT ?',(*args,limit+1)).fetchmany(limit+1)
            return dict(runId=run,items=[self._file(ledger,info,r,version,active) for r in rows[:limit]],nextCursor=rows[limit-1]['artifact_key'] if len(rows)>limit else None)
