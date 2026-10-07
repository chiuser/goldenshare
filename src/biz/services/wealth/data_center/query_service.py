"""Announcement query semantics. Prepared projections remain disposable caches."""
import json
import time
import uuid
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from src.foundation.clients.announcement_archive.core import Blocked,timestamp,DownloadOptions,identity
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.kernel.contracts.announcement_catalog import CatalogPreparationPort,ArchivePresencePort
from src.biz.queries.wealth.data_center.announcement_query import AnnouncementQuery
from src.biz.queries.wealth.data_center.company_query import CompanyQuery
from .errors import DataCenterError,mapped_error


class AnnouncementQueryService:
    def __init__(self,catalog,builder:CatalogPreparationPort,presence:ArchivePresencePort,policy=DataCenterPolicy(),wake=lambda:None):
        self.catalog,self.builder,self.presence,self.policy,self.wake=catalog,builder,presence,policy,wake
        self.rows=AnnouncementQuery(catalog,policy)
        self.company=CompanyQuery(catalog,policy)

    def conditions(self,request,now=None):
        today=(now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai')).date()
        start=request.startDate or today-timedelta(days=self.policy.query_days-1)
        end=request.endDate or today
        if end<start:
            raise DataCenterError('DC_REQUEST_INVALID','公告结束日期不能早于开始日期',422)
        return dict(startDate=start.isoformat(),endDate=end.isoformat(),tsCode=request.tsCode,
                    titleKeyword=request.titleKeyword,downloadStatus=request.downloadStatus)

    def create(self,request):
        conditions=self.conditions(request)
        query_id=identity([self.catalog.scope])[:16]+'-'+uuid.uuid4().hex
        self.catalog.create_query(query_id,conditions)
        self.wake()
        return self.preparing(self.catalog.query(query_id)),202

    def preparing(self,snapshot):
        stage=snapshot['preparation_stage']
        message=('正在统计匹配公告：'+str(snapshot['dates_counted'])+'/'+str(snapshot['dates_total'])+'个日期' if stage=='counting'
                 else '正在检查文件下载状态：已检查'+str(snapshot['artifacts_checked'])+'个文件' if stage=='checkingStatus'
                 else '正在准备公告索引')
        return dict(queryId=snapshot['query_id'],pageState=dict(status='preparing',code=None,message=message,asOfTime=snapshot['updated_at']),
            catalogRevision=snapshot['revision'],conditions=json.loads(snapshot['conditions']),items=[],total=None,page=1,
            pageSize=self.policy.page_size,hasPrevious=False,hasNext=False,downloadStatusAvailable=False,
            preparation=dict(datesScanned=snapshot['dates_scanned'],datesTotal=snapshot['dates_total'],recordsScanned=snapshot['records_scanned']))

    def prepare_next(self):
        """Called by the lifecycle-owned serial local preparation thread, never an HTTP request."""
        with self.catalog.connection() as conn:
            row=conn.execute("SELECT * FROM query_snapshots WHERE state='preparing' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            return False
        query_id=row['query_id'];conditions=json.loads(row['conditions'])
        try:
            with self.builder.preparation(query_id,conditions):
                revision=self.catalog.meta()['revision']
                available=True
                if conditions['downloadStatus']!='all':
                    self.catalog.reset_presence(query_id,self.builder.check)
                    after=''
                    while keys:=self.rows.keys(conditions,after):
                        self.builder.check()
                        present=self.presence.check(keys)
                        self.catalog.presence(query_id,present,checked_count=len(keys))
                        after=keys[-1]
                else:
                    try:
                        self.presence.check([])
                    except (Blocked,OSError):
                        available=False
                self.catalog.update_query(query_id,preparation_stage='counting')
                self.rows.prepare_counts(query_id,conditions,self.builder.check)
                if (revision!=self.catalog.meta()['revision'] or not self.builder.current(conditions['startDate'],conditions['endDate'])):
                    raise Blocked('query_context_changed')
                self.catalog.update_query(query_id,state='ready',revision=revision,archive_identity=self.presence.identity,
                                          checked_at=timestamp(),status_available=int(available))
        except Blocked as error:
            if str(error)=='archive_already_running':
                return False # Another process owns the single catalog writer; leave the intent pending.
            self.catalog.update_query(query_id,state='error',reason=str(error))
        except Exception:
            self.catalog.update_query(query_id,state='error',reason='catalog_build_failed')
        return True

    def read(self,query_id,page=1):
        snapshot=self.catalog.query(query_id)
        if snapshot is None and re.fullmatch(r'[0-9a-f]{16}-[0-9a-f]{32}',query_id) and not query_id.startswith(identity([self.catalog.scope])[:16]+'-'):
            raise mapped_error('query_context_changed')
        if snapshot is None:
            raise DataCenterError('DC_OBJECT_NOT_FOUND','公告查询不存在',404)
        if snapshot['expires_at'] is not None and snapshot['expires_at']<=time.time():
            raise mapped_error('query_context_changed')
        if snapshot['state']=='preparing':
            self.wake()
            return self.preparing(snapshot),202
        if snapshot['state']=='error':
            error=mapped_error(snapshot['reason'])
            result=self.preparing(snapshot)
            result.update(pageState=dict(status='error',code=error.code,message=error.message,asOfTime=snapshot['updated_at']),
                          page=page,preparation=None)
            return result,200
        conditions=json.loads(snapshot['conditions'])
        try:
            if (snapshot['revision']!=self.catalog.meta()['revision'] or
                    self.presence.identity!=snapshot['archive_identity'] or
                    not self.builder.current(conditions['startDate'],conditions['endDate'])):
                raise Blocked('query_context_changed')
            total,rows,cached=self.rows.page(query_id,conditions,page,snapshot['revision'])
        except Blocked as error:
            raise mapped_error(str(error)) from None
        keys=list({r['artifact_key'] for r in rows if r['artifact_key']})
        checked=timestamp()
        available=True
        try:
            present=self.presence.check(keys)
        except (Blocked,OSError):
            available=False;present=set()
        if conditions['downloadStatus']!='all':
            if not available:
                raise DataCenterError('DC_STATUS_UNAVAILABLE','文件下载状态暂无法核验')
            if present!=cached:
                raise mapped_error('query_context_changed')
        items=[dict(recordKey=r['record_key'],annDate=r['ann_date'],tsCode=r['ts_code'],
                    companyName=r['display_name'] or r['ts_code'] or '—',companyNameSource=r['name_source'] or 'code',
                    title=r['title'],sourceUrl=r['download_url'],downloadStatus=(
                        'downloaded' if r['artifact_key'] in present else 'undownloaded') if available else None,
                    statusCheckedAt=checked if available else None) for r in rows]
        return dict(queryId=query_id,pageState=dict(status='ready' if total else 'empty',code=None,message=None,asOfTime=snapshot['checked_at'] if conditions['downloadStatus']!='all' else timestamp()),
            catalogRevision=snapshot['revision'],conditions=conditions,items=items,total=total,page=page,pageSize=self.policy.page_size,
            hasPrevious=page>1,hasNext=page*self.policy.page_size<total,downloadStatusAvailable=available,preparation=None),200

    def companies(self,keyword,request):
        conditions=self.conditions(request)
        if not keyword.strip():
            return dict(keyword=keyword,items=[],hasMore=False),200
        try:
            if not self.builder.current(conditions['startDate'],conditions['endDate']):
                serialized=json.dumps(conditions,ensure_ascii=False)
                with self.catalog.connection() as conn:
                    snapshot=conn.execute("SELECT * FROM query_snapshots WHERE conditions=? AND state='preparing' AND (expires_at IS NULL OR expires_at>?) LIMIT 1",(serialized,time.time())).fetchone()
                if snapshot is None:
                    preparing,_=self.create(request)
                else:
                    preparing=self.preparing(dict(snapshot))
                return dict(keyword=keyword,items=[],hasMore=None,pageState=preparing['pageState'],
                            preparation=preparing['preparation'],queryId=preparing['queryId']),202
            return self.company.search(keyword,conditions['startDate'],conditions['endDate']),200
        except Blocked as error:
            raise mapped_error(str(error)) from None

    def validate_sources(self):
        self.builder.assert_source(full=True)
        self.presence.assert_valid(full=True)

    def context(self):
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
        source_ready=True;archive_ready=True
        try:
            self.builder.assert_source()
        except (Blocked,OSError):
            source_ready=False
        try:
            self.presence.check([])
        except (Blocked,OSError):
            archive_ready=False
        meta=self.catalog.meta()
        with self.catalog.connection() as conn:
            observed=conn.execute('SELECT MAX(ann_date) FROM catalog_days').fetchone()[0]
        return dict(moduleEnabled=True,archiveAvailability='ready' if archive_ready else 'unavailable',
            sourceAvailability='ready' if source_ready else 'unavailable',indexAvailability='ready' if meta['published_at'] else 'preparing',
            archiveLocation=str(DownloadOptions(today,today).output_root),currentRunId=self.presence.current_run(),
            queryDefaults=dict(startDate=(today-timedelta(days=self.policy.query_days-1)).isoformat(),endDate=today.isoformat(),downloadStatus='all'),
            downloadDefaults=dict(startDate=None,endDate=None,intervalSeconds=DownloadOptions(today,today).interval_seconds),
            policy=dict(pageSize=self.policy.page_size,companyLimit=self.policy.company_limit,pollSeconds=self.policy.poll_seconds),
            observedAnnDate=observed,lastIndexedAt=meta['published_at'],sourceUpdateSucceededAt=None)
