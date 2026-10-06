"""Serial local-only previews; bounded daily counts and file checks, no PDF requests."""
import json
import threading
from datetime import date
from src.foundation.clients.announcement_archive.core import Blocked,Cancelled,Control,DownloadPolicy
from src.foundation.config.announcement_archive import DataCenterPolicy


class PreviewControl(Control):
    def __init__(self,catalog,preview_id):
        super().__init__(DownloadPolicy(),emit=lambda _:None)
        self.catalog,self.preview_id=catalog,preview_id

    def check(self):
        super().check()
        value=self.catalog.preview(self.preview_id)
        if value is None:raise Blocked('preview_not_found')
        if value['state']=='cancelled':
            self.stop.set();super().check()


class PreviewRuntime:
    def __init__(self,factory,catalog_provider,policy=DataCenterPolicy()):
        self.factory,self.catalog_provider,self.policy=factory,catalog_provider,policy
        self.stop=threading.Event();self.wake=threading.Event();self.control=None
        self.thread=threading.Thread(target=self._run,name='announcement-preview',daemon=True)

    def start(self):self.thread.start();return self

    def _run(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                catalog=self.catalog_provider()
                if self.prepare_next(catalog):continue
            except (Blocked,OSError):pass
            self.wake.wait(self.policy.control_poll_seconds)

    def prepare_next(self,catalog):
        preview_id=catalog.preview_pending()
        if not preview_id:return False
        value=catalog.preview(preview_id)
        control=self.control=PreviewControl(catalog,preview_id)
        watcher_stop=threading.Event()
        def watch():
            while not watcher_stop.wait(self.policy.control_poll_seconds):
                try:
                    if self.stop.is_set() or catalog.preview(preview_id)['state']=='cancelled':control.stop.set()
                except (Blocked,OSError):control.stop.set()
        watcher=threading.Thread(target=watch,name='preview-stop-watch',daemon=True);watcher.start()
        builder=presence=None
        try:
            builder,presence=self.factory(control)
            if catalog.scope!=builder.catalog.scope or presence.identity!=value['archive_identity']:
                raise Blocked('preview_stale')
            conditions=dict(startDate=value['start_date'],endDate=value['end_date'],tsCode=None,titleKeyword='',downloadStatus='all')
            with builder.preparation(preview_id,conditions):
                counts=self.summarize(catalog,preview_id,value,presence,control.check)
                control.check();presence.assert_valid(full=True)
                if not builder.current(value['start_date'],value['end_date']):raise Blocked('preview_stale')
                expected=(date.fromisoformat(value['end_date'])-date.fromisoformat(value['start_date'])).days+1
                with catalog.connection() as conn:
                    actual=conn.execute('SELECT COUNT(*) FROM preview_days WHERE preview_id=?',(preview_id,)).fetchone()[0]
                if actual!=expected:raise Blocked('preview_stale')
                catalog.update_preview(preview_id,state='ready' if counts['artifactCount'] else 'empty',statistics=counts,ready=True)
        except Cancelled:
            if not self.stop.is_set():catalog.cancel_preview(preview_id)
            # Process shutdown leaves a local-only pending preview restartable; never starts HTTP.
        except Blocked as error:
            if str(error)=='archive_already_running':return False
            catalog.update_preview(preview_id,state='error',statistics=dict(reason=str(error)),ready=True)
        except Exception:
            catalog.update_preview(preview_id,state='error',statistics=dict(reason='catalog_build_failed'),ready=True)
        finally:
            watcher_stop.set();watcher.join(timeout=1)
            if builder:builder.close()
            if presence:presence.close()
            self.control=None
        return True

    @staticmethod
    def summarize(catalog,preview_id,value,presence,check):
        counts=dict(recordCount=0,artifactCount=0,missingUrlCount=0,reusableEstimate=0,downloadEstimate=0,reason=None)
        after='';presence.assert_valid(full=True)
        catalog.reset_preview_keys(preview_id,check)
        while days:=catalog.days_after(value['start_date'],value['end_date'],after):
            for day in days:
                check();check()
                with catalog.connection() as conn:
                    missing=conn.execute('SELECT COUNT(*) FROM catalog_records WHERE ann_date=? AND generation=? AND artifact_key IS NULL',(day['ann_date'],day['active_generation'])).fetchone()[0]
                counts['recordCount']+=day['footer_count'];counts['missingUrlCount']+=missing
                record_after=''
                while True:
                    check()
                    with catalog.connection() as conn:
                        records=conn.execute('SELECT record_key,artifact_key FROM catalog_records WHERE ann_date=? AND generation=? AND record_key>? ORDER BY record_key LIMIT 500',(day['ann_date'],day['active_generation'],record_after)).fetchmany(500)
                    if not records:break
                    keys=catalog.add_preview_keys(preview_id,sorted({r['artifact_key'] for r in records if r['artifact_key']}))
                    reusable=len(presence.check(keys))
                    counts['artifactCount']+=len(keys);counts['reusableEstimate']+=reusable
                    counts['downloadEstimate']=counts['artifactCount']-counts['reusableEstimate']
                    catalog.update_preview(preview_id,statistics=counts)
                    record_after=records[-1]['record_key']
                catalog.put_preview_day(preview_id,day)
            after=days[-1]['ann_date']
        return counts

    def close(self):
        self.stop.set();self.wake.set()
        if self.control:self.control.stop.set()
        self.thread.join(timeout=DownloadPolicy().source_query_timeout_seconds+self.policy.sql_seconds+1)
