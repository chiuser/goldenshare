"""One explicitly accepted local execution; no download queue or automatic HTTP recovery."""
import json
import threading
import time
from datetime import date
from src.foundation.clients.announcement_archive.core import Blocked,Cancelled,DownloadOptions,DownloadPolicy,Control,identity,timestamp
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.clients.announcement_archive.files import Files
from src.foundation.clients.announcement_archive.http import Downloader
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.dao.announcement_archive.execution import ArchiveStore,ExecutionLedger,TERMINAL,payload_hash,remote_recheck_satisfied
from .executor import execute_run
from .control import WebControl


def recoverable(info):
    return (info['source_kind']=='dg_raw_parquet' and info['source_contract_version']==1
            and bool(info['enumeration_sealed']) and bool(info.get('source_policy'))
            and (info['batch_kind']=='retry' or info['days_completed']==info['days_total']))


class ArchiveSupervisor:
    def __init__(self,binding,resource_factory,catalog_provider,*,policy=DownloadPolicy(),data_policy=DataCenterPolicy(),client_factory=None,bootstrap=None):
        self.binding,self.store=binding,ArchiveStore(binding)
        self.resource_factory,self.catalog_provider=resource_factory,catalog_provider
        self.policy,self.data_policy=policy,data_policy
        self.client_factory,self.bootstrap=client_factory,bootstrap
        self.admission=threading.Lock();self.thread=None;self.control=None;self.closed=False
        self.last_error=None

    def start(self):
        def recover():
            try:
                if self.bootstrap:self.bootstrap()
            except (Blocked,OSError):pass
            try:self.recover()
            except (Blocked,OSError):pass
        self.recovery_thread=threading.Thread(target=recover,name='archive-recovery',daemon=True)
        self.recovery_thread.start();return self

    def recover(self):
        value=self.binding.read();path=self.binding.ledger_path(value)
        if not path.exists():return
        lock=ExecutionLock(path.parent/'execution.lock').open()
        try:
            with self.store.open() as ledger:
                if ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0]!=3:return
            with self.store.open(write=True) as ledger:ExecutionLedger(ledger).recover_abandoned()
        finally:lock.close()

    def submit(self,kind,payload,key=None,actor=None):
        if self.closed:raise Blocked('archive_shutdown')
        if key:
            try:
                existing=self.store.receipt(key,kind,payload)
                if existing:return existing
            except Blocked as error:
                if str(error) not in {'archive_binding_missing','archive_ledger_missing'}:raise
        if not self.admission.acquire(blocking=False):raise Blocked('archive_already_running')
        ready=threading.Event();abandon=threading.Event();answer={}
        self.thread=threading.Thread(target=self._worker,args=(kind,payload,key,actor,ready,abandon,answer),name='announcement-download',daemon=True)
        try:self.thread.start()
        except RuntimeError:
            self.admission.release();raise Blocked('archive_execution_failed') from None
        if not ready.wait(max(.01,self.data_policy.api_seconds-.5)):
            abandon.set();raise Blocked('command_acceptance_timeout')
        if 'error' in answer:raise Blocked(answer['error'])
        return answer['run']

    def _preview(self,catalog,preview_id,source,volume):
        value=catalog.preview(preview_id)
        if not value:raise Blocked('preview_not_found')
        if (value['state']!='ready' or not value['expires_at'] or value['expires_at']<=time.time()
                or value['source_scope']!=source.scope or value['archive_identity']!=identity([volume.volume_uuid,volume.relative_root])):
            raise Blocked('preview_stale')
        if not json.loads(value['statistics'])['artifactCount']:raise Blocked('preview_empty')
        return value

    def _validate_range(self,catalog,preview,source):
        # Bounded per-day facts, never an unbounded list or full candidate JSON.
        from .catalog_builder import CatalogBuilder,signature
        after='';count=0
        while days:=catalog.days_after(preview['start_date'],preview['end_date'],after):
            for day in days:
                source.control.check();saved=catalog.preview_day(preview['preview_id'],day['ann_date'])
                if not saved or saved['generation']!=day['active_generation']:raise Blocked('preview_stale')
                facts=json.loads(saved['source_facts'])
                if signature(CatalogBuilder.file_stat(source.volume,'ann_date='+day['ann_date']))!=tuple(facts[k] for k in ('opened_dev','opened_ino','size','mtime_ns')):
                    raise Blocked('preview_stale')
                count+=1
            after=days[-1]['ann_date']
        if count!=(date.fromisoformat(preview['end_date'])-date.fromisoformat(preview['start_date'])).days+1:raise Blocked('preview_stale')

    def _worker(self,kind,payload,key,actor,ready,abandon,answer):
        ledger=volume=source=control=client=None;run=None;accepted=False
        try:
            execution_policy=self.policy
            preliminary=Control(execution_policy,emit=lambda _:None)
            if kind=='create':
                catalog=self.catalog_provider();preview=catalog.preview(payload['previewId'])
                if not preview:raise Blocked('preview_not_found')
                options=DownloadOptions(date.fromisoformat(preview['start_date']),date.fromisoformat(preview['end_date']),preview['interval_seconds'],self.binding.output)
            else:
                with self.store.open() as existing:
                    info=ExecutionLedger(existing).run(payload['runId'])
                    version=existing.conn.execute('SELECT schema_version FROM archive').fetchone()[0]
                if version!=3:raise Blocked('run_not_recoverable')
                if kind in {'continue','retry'} and not recoverable(info):raise Blocked('run_not_recoverable')
                if kind=='continue' and info['phase'] not in {'stopped','blocked','interrupted'}:raise Blocked('run_not_recoverable')
                if kind=='continue' and not remote_recheck_satisfied(info):raise Blocked('run_not_recoverable')
                if kind=='retry' and info['phase'] not in TERMINAL:raise Blocked('run_not_recoverable')
                if kind=='recheck' and info['phase']!='blocked':raise Blocked('run_not_recoverable')
                if kind=='recheck' and payload['kind']=='remoteSource' and info['reason'] not in {'http_403','challenge_page'}:raise Blocked('recheck_scope_invalid')
                if not info.get('source_policy'):raise Blocked('run_not_recoverable')
                try:execution_policy=DownloadPolicy(**json.loads(info['source_policy']))
                except (ValueError,TypeError):raise Blocked('run_not_recoverable') from None
                preliminary.policy=execution_policy
                options=DownloadOptions(date.fromisoformat(info['start_date']),date.fromisoformat(info['end_date']),info['interval_seconds'],self.binding.output)
            volume,ledger,source=self.resource_factory(options,preliminary,source_required=not(kind=='recheck' and payload['kind']=='volume'))
            if kind!='create' and self.binding.read()['volumeUuid']!=volume.volume_uuid:raise Blocked('archive_identity_mismatch')
            self.binding.remember(volume)
            state=ExecutionLedger(ledger)
            if key:
                previous=state.receipt(key,kind,payload)
                if previous:answer['run']=previous;ready.set();return
            state.recover_abandoned()
            if abandon.is_set() or self.closed:raise Blocked('command_acceptance_timeout')
            if kind=='create':
                preview=self._preview(catalog,payload['previewId'],source,volume)
                self._validate_range(catalog,preview,source)
                if abandon.is_set():raise Blocked('command_acceptance_timeout')
                run=ledger.begin_run(options,source.scope,execution_policy,command=(key,kind,payload_hash(kind,payload)),details=dict(preview_id=payload['previewId'],actor_id=actor))
            else:
                info=state.run(payload['runId'])
                if source is not None and info['source_scope']!=source.scope:raise Blocked('source_scope_changed')
                if kind=='continue':
                    if not recoverable(info) or not remote_recheck_satisfied(info) or info['phase'] not in {'stopped','blocked','interrupted'} or not ledger.conn.execute('SELECT 1 FROM run_artifacts WHERE run_id=? AND outcome IS NULL LIMIT 1',(info['run_id'],)).fetchone():
                        raise Blocked('run_not_recoverable')
                    run=info['run_id'];state.claim(run,resume=True,command=(key,kind,payload))
                elif kind=='retry':
                    if info['phase'] not in TERMINAL or not recoverable(info):raise Blocked('run_not_recoverable')
                    single=payload.get('artifactKey') if payload['scope']=='singleFailed' else None
                    if not state.unresolved(info['run_id'],key=single,limit=1):raise Blocked('retry_scope_invalid')
                    run=ledger.begin_run(options,source.scope,execution_policy,command=(key,kind,payload_hash(kind,payload)),details=dict(batch_kind='retry',parent_run_id=info['parent_run_id'] or info['run_id'],retry_of_run_id=info['run_id'],actor_id=actor,records_read=info['records_read'],missing_url_count=info['missing_url_count'],days_total=0))
                elif kind=='recheck':
                    if info['phase']!='blocked':raise Blocked('run_not_recoverable')
                    if payload['kind']=='remoteSource' and info['reason'] not in {'http_403','challenge_page'}:raise Blocked('recheck_scope_invalid')
                    run=info['run_id']
                    with ledger.conn:
                        ledger.conn.execute("UPDATE runs SET check_state='checking',check_kind=?,check_code=NULL,check_updated_at=?,owner_token=?,stop_requested_at=NULL WHERE run_id=?",(payload['kind'],timestamp(),ledger.owner_token,run))
                        ledger.conn.execute('UPDATE archive_execution SET active_run_id=?,owner_token=?,heartbeat=?,revision=revision+1 WHERE singleton=1',(run,ledger.owner_token,timestamp()))
                else:raise Blocked('command_invalid')
            accepted=True;answer['run']=run
            control=self.control=WebControl(execution_policy,self.store,ledger,run)
            if source:source.control=control
            control.start();ready.set()
            if kind=='retry':
                after=''
                while keys:=state.unresolved(info['run_id'],after,key=single):
                    control.check();state.copy_retry(run,keys);after=keys[-1]
                control.check();state.seal_retry(run)
            client=self.client_factory() if self.client_factory else None
            if kind=='recheck':
                self._recheck(payload['kind'],run,ledger,volume,source,control,options,client)
            else:
                def validate_day(day):
                    saved=catalog.preview_day(preview['preview_id'],day.day);facts=json.loads(saved['source_facts']) if saved else {}
                    if any(day.facts[k]!=facts.get(k) for k in ('opened_dev','opened_ino','size','sha256','footer_count')):
                        raise Blocked('preview_stale')
                    from .catalog_builder import CatalogBuilder,signature
                    if signature(CatalogBuilder.file_stat(source.volume,'ann_date='+day.day))!=tuple(facts[k] for k in ('opened_dev','opened_ino','size','mtime_ns')):raise Blocked('preview_stale')
                execute_run(run,options,execution_policy,control,volume,ledger,source,source.scope,client,
                    enumerate_source=kind=='create',validate_day=validate_day if kind=='create' else None,web=True)
        except BaseException as error:
            reason=str(error) if isinstance(error,Blocked) else 'process_exit' if isinstance(error,Cancelled) else 'archive_execution_failed'
            self.last_error=reason
            if not accepted:answer['error']=reason
            elif ledger and run:
                try:
                    if isinstance(error,Cancelled):
                        info=state.run(run);phase='cancelled' if not info['enumeration_sealed'] else 'stopped' if info['stop_requested_at'] else 'interrupted'
                    else:phase='blocked'
                    if state.run(run)['phase'] not in {'completed','partial_failed','stopped','cancelled'}:ledger.phase(run,phase,reason)
                except Exception:pass
        finally:
            ready.set()
            if control:control.close()
            if client:client.close()
            if source:source.close()
            if ledger:ledger.close()
            if volume:volume.close()
            self.control=None;self.admission.release()

    def _recheck(self,kind,run,ledger,volume,source,control,options,client):
        downloader=None;outcome='passed';reason=None
        try:
            control.check()
            if kind=='volume':volume.assert_valid(full=True);volume.check_space(policy_file=True)
            elif kind=='localSource':source.assert_valid(full=True)
            else:
                info=ExecutionLedger(ledger).run(run)
                if not info['current_artifact_key']:raise Blocked('recheck_scope_invalid')
                task=ledger.artifact(info['current_artifact_key'])
                downloader=Downloader(ledger,Files(volume,ledger,control.policy,control),volume,options,control.policy,control,client=client)
                downloader.probe(task)
        except Cancelled:outcome='cancelled';reason='user_cancelled'
        except Exception as error:
            outcome='blocked';reason=str(error) if isinstance(error,Blocked) else 'remote_check_failed'
        finally:
            if downloader:downloader.close()
            elif client:client.close()
            with ledger.conn:
                ledger.conn.execute('UPDATE runs SET check_state=?,check_code=?,check_updated_at=?,owner_token=NULL,wait_kind=NULL,next_request_at=NULL WHERE run_id=?',(outcome,reason,timestamp(),run))
                ledger.conn.execute('UPDATE archive_execution SET active_run_id=NULL,owner_token=NULL,revision=revision+1 WHERE active_run_id=? AND owner_token=?',(run,ledger.owner_token))

    def close(self):
        self.closed=True
        if self.control:self.control.stop.set()
        if self.thread:self.thread.join(timeout=30)
        if hasattr(self,'recovery_thread'):self.recovery_thread.join(timeout=5)
