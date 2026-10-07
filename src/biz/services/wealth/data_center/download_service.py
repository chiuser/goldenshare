"""Public local archive use cases, with execution delegated through a Foundation port."""
import json
import time
import uuid
from datetime import date,datetime,timezone
from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.kernel.contracts.announcement_execution import ArchiveExecutionPort
from src.biz.queries.wealth.data_center.run_query import RunQuery
from .errors import mapped_download_error


class AnnouncementDownloadService:
    def __init__(self,execution:ArchiveExecutionPort,store,controls_provider,identity_provider,wake_preview):
        self.execution,self.store=execution,store
        self.controls_provider,self.identity_provider,self.wake_preview=controls_provider,identity_provider,wake_preview
        self._runs=RunQuery(store) if store else None

    @property
    def runs(self):
        if self._runs is None:raise Blocked('archive_execution_not_ready')
        return self._runs

    def create_preview(self,body):
        controls=self.controls_provider();identity=self.identity_provider()
        preview=uuid.uuid4().hex
        controls.create_preview(preview,body.startDate.isoformat(),body.endDate.isoformat(),body.intervalSeconds,identity)
        self.wake_preview()
        return self.preview(preview)

    def preview(self,preview):
        controls=self.controls_provider();row=controls.preview(preview)
        if row is None:raise Blocked('preview_not_found')
        stats=json.loads(row['statistics']) if row['statistics'] else {};snapshot=row
        reason=row['reason'] or stats.get('reason')
        error=mapped_download_error(reason) if reason else None
        can_start=row['state']=='ready' and bool(row['expires_at'] and row['expires_at']>time.time())
        return dict(previewId=preview,state='error' if row['state']=='expired' else row['state'],startDate=row['start_date'],endDate=row['end_date'],intervalSeconds=row['interval_seconds'],recordCount=stats.get('recordCount') if row['state'] in {'ready','empty'} else None,artifactCount=stats.get('artifactCount') if row['state'] in {'ready','empty'} else None,missingUrlCount=stats.get('missingUrlCount') if row['state'] in {'ready','empty'} else None,reusableEstimate=stats.get('reusableEstimate') if row['state'] in {'ready','empty'} else None,downloadEstimate=stats.get('downloadEstimate') if row['state'] in {'ready','empty'} else None,canStart=can_start,expiresAt=datetime.fromtimestamp(row['expires_at'],timezone.utc).isoformat() if row['expires_at'] else None,preparation=dict(datesScanned=snapshot['dates_scanned'],datesTotal=snapshot['dates_total'],recordsScanned=snapshot['records_scanned']),error=dict(code=error.code,message=error.message) if error else None),202 if row['state']=='preparing' else 200

    def stop_preview(self,preview):
        self.controls_provider().cancel_preview(preview)
        return self.preview(preview)

    def command(self,kind,payload,key=None,actor=None):
        if self.execution is None:raise Blocked('archive_execution_not_ready')
        run=self.execution.submit(kind,payload,key,actor)
        return self.runs.task(run),202

    def stop(self,run):
        if self.store is None:raise Blocked('archive_execution_not_ready')
        self.store.stop(run)
        return self.runs.task(run),202
