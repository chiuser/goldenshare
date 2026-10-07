"""Announcement use cases over pinned Raw reads and small PG controls."""
import json
import re
import time
import uuid
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from src.foundation.clients.announcement_archive.core import Blocked,timestamp,DownloadOptions,identity
from src.foundation.clients.announcement_archive.company_source import CompanySource
from src.foundation.config.announcement_archive import DataCenterPolicy
from .errors import DataCenterError,mapped_error


class AnnouncementQueryService:
    def __init__(self,controls,source,presence,policy=DataCenterPolicy(),wake=lambda:None):
        self.controls,self.source,self.presence,self.policy,self.wake=controls,source,presence,policy,wake
        self.company=CompanySource(source)

    def conditions(self,request,now=None):
        today=(now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai')).date()
        start=request.startDate or today-timedelta(days=self.policy.query_days-1);end=request.endDate or today
        if end<start:raise DataCenterError('DC_REQUEST_INVALID','公告结束日期不能早于开始日期',422)
        return dict(startDate=start.isoformat(),endDate=end.isoformat(),tsCode=request.tsCode,titleKeyword=request.titleKeyword,downloadStatus=request.downloadStatus)

    def create(self,request):
        query_id=identity([self.controls.scope])[:16]+'-'+uuid.uuid4().hex
        self.controls.create_query(query_id,self.conditions(request));self.wake()
        return self.preparing(self.controls.query(query_id)),202

    def preparing(self,row):
        messages={'readingSource':'正在读取本地公告来源','checkingStatus':'正在检查文件下载状态','counting':'正在统计匹配公告'}
        return dict(queryId=row['query_id'],pageState=dict(status='preparing',code=None,message=messages[row['preparation_stage']],asOfTime=row['updated_at']),
            sourceVersion=row['source_version'],conditions=json.loads(row['conditions']),items=[],total=None,page=1,pageSize=self.policy.page_size,
            hasPrevious=False,hasNext=False,downloadStatusAvailable=False,preparation=dict(stage=row['preparation_stage'],
                datesScanned=row['dates_scanned'],datesTotal=row['dates_total'],recordsScanned=row['records_scanned'],artifactsChecked=row['artifacts_checked']))

    def snapshot(self,query_id):
        row=self.controls.query(query_id)
        if row is None:
            if re.fullmatch(r'[0-9a-f]{16}-[0-9a-f]{32}',query_id) and not query_id.startswith(identity([self.controls.scope])[:16]+'-'):
                raise mapped_error('query_context_changed')
            raise DataCenterError('DC_OBJECT_NOT_FOUND','公告查询不存在',404)
        if row['source_scope']!=self.controls.scope or row['state']=='expired' or row['expires_at'] is not None and row['expires_at']<=time.time():
            raise mapped_error('query_context_changed')
        return row

    def check_version(self,row):
        from src.foundation.clients.announcement_archive.direct_source import source_version
        self.controls.validate_counts(row['query_id'],row['dates_total'],row['total'])
        self.source.validate_manifest(self.controls.files(row['query_id']))
        version=source_version(self.source.scope,self.source.initials.version,self.controls.files(row['query_id']))
        if version!=row['source_version']:raise Blocked('query_context_changed')

    def unit_presence(self,query_id,day,code):
        after=''
        while batch:=self.controls.presence_keys(query_id,after,day=day,code=code):
            yield batch;after=batch[-1]['artifact_key']

    def check_filtered_presence(self,row,conditions):
        """A status snapshot is invalid when any relevant positive changes."""
        query_id=row['query_id'];after='';actual_count=0
        while rows:=self.controls.successful(conditions,after):
            present=self.presence.check_rows(rows)
            with self.controls.transaction(read_only=True) as conn:
                from sqlalchemy import text
                if present:
                    frozen=set(conn.execute(text('SELECT artifact_key FROM announcement_archive.query_presence WHERE archive_id=:a '
                        'AND query_id=:id AND artifact_key=ANY(:keys)'),dict(a=self.controls.archive_id,id=query_id,keys=list(present))).scalars())
                    if frozen!=present:raise Blocked('query_context_changed')
            actual_count+=len(present);after=rows[-1]['artifact_key']
        with self.controls.transaction(read_only=True) as conn:
            from sqlalchemy import text
            count=conn.scalar(text('SELECT count(*) FROM announcement_archive.query_presence WHERE archive_id=:a AND query_id=:id'),dict(a=self.controls.archive_id,id=query_id))
        if count!=actual_count:raise Blocked('query_context_changed')

    def page_rows(self,row,conditions,page):
        query_id=row['query_id'];offset=(page-1)*self.policy.page_size;take=self.policy.page_size;result=[]
        for batch in self.controls.day_counts(query_id):
            for day in batch:
                count=day['match_count']
                if offset>=count:offset-=count;continue
                limit=min(take,count-offset)
                facts=self.controls.rows('query_files','AND query_id=:id AND source_kind=\'anns_d\' AND partition=:day',dict(id=query_id,day=day['ann_date']),limit=1)[0]
                if conditions['downloadStatus']!='all':self.source.set_presence(self.unit_presence(query_id,day['ann_date'],conditions['tsCode']))
                result.extend(self.source.page_day(day['ann_date'],conditions,offset,limit,facts))
                take-=limit;offset=0
                if not take:return result
        return result

    def read(self,query_id,page=1):
        row=self.snapshot(query_id)
        if row['state']=='preparing':return self.preparing(row),202
        if row['state']=='error':
            error=mapped_error(row['reason']);result=self.preparing(row)
            result.update(pageState=dict(status='error',code=error.code,message=error.message,asOfTime=row['updated_at']),page=page,preparation=None)
            return result,200
        conditions=json.loads(row['conditions']);available=True;checked=timestamp()
        try:
            if conditions['downloadStatus']!='all':self.check_filtered_presence(row,conditions)
            with self.source.session():
                self.check_version(row)
                self.company.prepare(self.controls,query_id,conditions,row['source_version'])
                rows=self.page_rows(row,conditions,page)
                keys=sorted({r['artifact_key'] for r in rows if r['artifact_key']})
                try:present=self.presence.check(keys)
                except (Blocked,OSError) as error:
                    if isinstance(error,Blocked) and str(error).startswith(('archive_database','archive_schema','archive_import','archive_not_found')):raise
                    if conditions['downloadStatus']!='all':raise
                    available=False;present=set()
                self.check_version(row)
        except Blocked as error:raise mapped_error(str(error)) from None
        items=[dict(recordKey=r['record_key'],annDate=r['ann_date'],tsCode=r['ts_code'],companyName=r['display_name'] or r['ts_code'] or '—',
            companyNameSource=r['name_source'] or 'code',title=r['title'],sourceUrl=r['url'].strip() if r['url'] else None,
            downloadStatus=('downloaded' if r['artifact_key'] in present else 'undownloaded') if available else None,statusCheckedAt=checked if available else None) for r in rows]
        total=row['total']
        return dict(queryId=query_id,pageState=dict(status='ready' if total else 'empty',code=None,message=None,asOfTime=row['checked_at']),
            sourceVersion=row['source_version'],conditions=conditions,items=items,total=total,page=page,pageSize=self.policy.page_size,
            hasPrevious=page>1,hasNext=page*self.policy.page_size<total,downloadStatusAvailable=available,preparation=None),200

    def companies(self,keyword,request):
        conditions=self.conditions(request)
        if not keyword.strip():return dict(keyword=keyword,items=[],hasMore=False),200
        serialized=json.dumps(conditions,ensure_ascii=False)
        rows=self.controls.rows('query_snapshots','AND conditions=:conditions AND source_scope=:scope AND (expires_at IS NULL OR expires_at>:now) '
            'AND state IN (\'preparing\',\'ready\',\'error\')',dict(conditions=serialized,scope=self.controls.scope,now=time.time()),order='created_at DESC',limit=1)
        if not rows:
            result,status=self.create(request)
            return dict(keyword=keyword,items=[],hasMore=None,pageState=result['pageState'],preparation=result['preparation'],queryId=result['queryId']),status
        row=rows[0]
        if row['state'] in {'preparing','error'}:
            result,status=self.read(row['query_id'])
            return dict(keyword=keyword,items=[],hasMore=None,pageState=result['pageState'],preparation=result['preparation'],queryId=row['query_id']),status
        try:
            with self.source.session():
                self.check_version(row);self.company.prepare(self.controls,row['query_id'],conditions,row['source_version'])
                result=self.company.search(keyword,self.policy.company_limit);self.check_version(row)
            return result,200
        except Blocked as error:raise mapped_error(str(error)) from None

    def context(self):
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date();source_ready=archive_ready=ledger_ready=True;observed=None;run=None
        try:
            with self.source.session():self.source.assert_valid(full=True);observed=self.source.observed_date()
        except (Blocked,OSError):source_ready=False
        try:
            with self.controls.transaction(read_only=True):pass
            run=self.presence.current_run()
        except Blocked:ledger_ready=False
        try:self.presence.assert_valid(full=True)
        except (Blocked,OSError):archive_ready=False
        return dict(moduleEnabled=True,archiveAvailability='ready' if archive_ready else 'unavailable',sourceAvailability='ready' if source_ready else 'unavailable',
            ledgerAvailability='ready' if ledger_ready else 'unavailable',archiveLocation=str(DownloadOptions(today,today).output_root),currentRunId=run,
            queryDefaults=dict(startDate=(today-timedelta(days=self.policy.query_days-1)).isoformat(),endDate=today.isoformat(),downloadStatus='all'),
            downloadDefaults=dict(startDate=None,endDate=None,intervalSeconds=DownloadOptions(today,today).interval_seconds),
            policy=dict(pageSize=self.policy.page_size,companyLimit=self.policy.company_limit,pollSeconds=self.policy.poll_seconds),observedAnnDate=observed,sourceUpdateSucceededAt=None)

    def close(self):self.source.close();self.presence.close();self.controls.database.close()
