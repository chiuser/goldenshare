"""Bounded pinned-FD Parquet reads on one serial DuckDB connection.

Only small names and a unit's presence keys are temporary relations. Announcement
rows never become a catalog; paths are opened via the verified volume anchor.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat
import threading
import time
from datetime import date,timedelta

from .budget import remaining
from .core import ANNOUNCEMENT_FIELDS,SOURCE_CONTRACT_VERSION,Blocked,identity
from .names import NameInitials,normalized_name

# Python str.strip identity, including control whitespace that DuckDB trim omits.
URL_WHITESPACE=''.join(chr(n) for n in (*range(9,14),*range(28,33),133,160,5760,*range(8192,8203),8232,8233,8239,8287,12288))
FACT_FIELDS=('opened_dev','opened_ino','size','mtime_ns')


def requested_conditions(conditions):
    return {key:value for key,value in conditions.items() if key!='effectiveEndDate'}


def effective_conditions(conditions):
    return dict(requested_conditions(conditions),endDate=conditions.get('effectiveEndDate') or conditions['endDate'])


def days(start,end):
    value=date.fromisoformat(start);last=date.fromisoformat(end)
    while value<=last:
        yield value.isoformat()
        if value==last:break
        value+=timedelta(days=1)


def batches(values,size=32):
    batch=[]
    for value in values:
        batch.append(value)
        if len(batch)==size:yield batch;batch=[]
    if batch:yield batch


def signature(info):
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns


def source_version(scope,dictionary_version,manifests):
    digest=hashlib.sha256()
    digest.update(json.dumps([scope,SOURCE_CONTRACT_VERSION,dictionary_version],ensure_ascii=False,separators=(',',':')).encode())
    for batch in manifests:
        for row in batch:
            digest.update(json.dumps([row['source_kind'],row['partition'],*(row[k] for k in FACT_FIELDS)],separators=(',',':')).encode())
    return digest.hexdigest()


class DirectSource:
    def __init__(self,volume,names_volume,control,policy,initials=None):
        import duckdb
        self.volume,self.names_volume,self.control,self.policy=volume,names_volume,control,policy
        self.initials=initials or NameInitials()
        self.scope='dg-anns-d:'+identity([volume.volume_uuid,volume.relative_root,str(SOURCE_CONTRACT_VERSION)])
        self.duckdb=duckdb
        self.connection=duckdb.connect(':memory:',config=dict(memory_limit='256MiB',threads=1,
            max_temp_directory_size='0B',autoinstall_known_extensions=False,autoload_known_extensions=False))
        self.lock=threading.Lock();self.name_version=None;self.range_version=None
        self.sql_calls=0;self.sql_max_seconds=0.;self.fd_peak=0
        self.connection.create_function('name_initials',lambda name,code:self.initials(name,code),
            ['VARCHAR','VARCHAR'],'VARCHAR',null_handling='special')
        self.connection.create_function('normalized_name',normalized_name,['VARCHAR'],'VARCHAR',null_handling='special')

    def assert_valid(self,full=False):
        self.volume.assert_valid(full=full);self.names_volume.assert_valid(full=full)
        # Dictionary replacement participates in source identity, even if no new search runs.
        if NameInitials(self.initials.path).version!=self.initials.version:raise Blocked('query_context_changed')

    @contextmanager
    def session(self):
        if not self.lock.acquire(timeout=remaining(self.policy.sql_seconds)):raise Blocked('query_resource_busy')
        try:
            self.control.check();yield self
        finally:self.lock.release()

    def sql(self,sql,parameters=(),limit=500):
        self.control.check();seconds=remaining(self.policy.sql_seconds)
        done=threading.Event();expired=threading.Event();start=time.monotonic()
        def interrupt():
            if not done.wait(seconds):expired.set();self.connection.interrupt()
        watcher=threading.Thread(target=interrupt,name='announcement-query-watchdog');watcher.start()
        try:
            result=self.connection.execute(sql,parameters)
            rows=result.fetchmany(limit) if limit else []
            if expired.is_set():raise Blocked('query_sql_timeout')
            self.control.check()
            return rows
        except self.duckdb.Error:
            raise Blocked('query_sql_timeout' if expired.is_set() else 'source_read_failed') from None
        finally:
            done.set();watcher.join();self.sql_calls+=1;self.sql_max_seconds=max(self.sql_max_seconds,time.monotonic()-start)

    def path(self,kind,partition):
        return (f'ann_date={partition}/part-000.parquet' if kind=='anns_d' else f'{kind}/full/part-000.parquet')

    def stat(self,kind,partition):
        volume=self.volume if kind=='anns_d' else self.names_volume
        relative=self.path(kind,partition)
        try:
            with volume.directory(relative.rsplit('/',1)[0]) as directory:
                info=os.stat('part-000.parquet',dir_fd=directory,follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_dev!=volume.device:raise Blocked('source_file_not_regular')
                return signature(info)
        except FileNotFoundError:raise Blocked('source_day_missing:'+partition if kind=='anns_d' else 'source_names_missing') from None

    @contextmanager
    def pinned(self,kind,partitions,expected=None,*,content=False):
        if len(partitions)>(self.policy.file_batch_size if kind=='anns_d' else 2):raise ValueError('source_file_batch_limit')
        volume=self.volume if kind=='anns_d' else self.names_volume
        opened=[]
        try:
            volume.assert_valid()
            for partition in partitions:
                relative=self.path(kind,partition)
                try:
                    with volume.directory(relative.rsplit('/',1)[0]) as directory:
                        fd=os.open('part-000.parquet',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                except FileNotFoundError:raise Blocked('source_day_missing:'+partition if kind=='anns_d' else 'source_names_missing') from None
                opened.append((fd,partition,relative,os.fstat(fd)))
            self.fd_peak=max(self.fd_peak,len(opened) if kind=='anns_d' else 0)
            paths=[f'/dev/fd/{fd}' for fd,_,_,_ in opened]
            for _,partition,_,info in opened:
                if not stat.S_ISREG(info.st_mode) or info.st_dev!=volume.device:raise Blocked('source_file_not_regular')
                if expected and signature(info)!=tuple(expected[partition][k] for k in FACT_FIELDS):raise Blocked('query_context_changed')
            schema=self.sql('SELECT file_name,name,duckdb_type FROM parquet_schema(?) WHERE num_children IS NULL',[paths],len(paths)*128+1)
            mapping={path:{} for path in paths}
            for path,column,typ in schema:mapping[path][column]=typ
            fields=ANNOUNCEMENT_FIELDS if kind=='anns_d' else ('ts_code','name','cnspell') if kind=='stock_basic' else ('ts_code','name')
            if any((set(value)!=set(fields) if kind=='anns_d' else not set(fields)<=set(value)) or any(value.get(f)!='VARCHAR' for f in fields) for value in mapping.values()):
                raise Blocked('source_file_schema')
            counts=dict(self.sql('SELECT file_name,num_rows FROM parquet_file_metadata(?)',[paths],len(paths)+1))
            if len(counts)!=len(paths) or any(not isinstance(n,int) or n<0 for n in counts.values()):raise Blocked('source_footer_invalid')
            facts=[]
            for (fd,partition,relative,info),path in zip(opened,paths):
                row=dict(source_kind=kind,partition=partition,relative_path=relative,opened_dev=info.st_dev,
                    opened_ino=info.st_ino,size=info.st_size,mtime_ns=info.st_mtime_ns,footer_count=counts[path])
                if content:row['sha256']=self.fingerprint(fd)
                facts.append(row)
            yield paths,facts
            for (fd,partition,_,info),fact in zip(opened,facts):
                if signature(os.fstat(fd))!=signature(info):raise Blocked('query_context_changed')
                if content and self.fingerprint(fd)!=fact['sha256']:raise Blocked('source_file_changed')
            volume.assert_valid()
        except OSError:raise Blocked('source_read_failed') from None
        finally:
            for fd,_,_,_ in opened:os.close(fd)

    def fingerprint(self,fd):
        digest=hashlib.sha256();offset=0
        while True:
            self.control.check();self.volume.assert_valid()
            chunk=os.pread(fd,self.control.policy.chunk_size,offset)
            if not chunk:break
            digest.update(chunk);offset+=len(chunk)
        return digest.hexdigest()

    def validate_manifest(self,manifests):
        self.assert_valid(full=True)
        for batch in manifests:
            for row in batch:
                self.control.check()
                if self.stat(row['source_kind'],row['partition'])!=tuple(row[k] for k in FACT_FIELDS):raise Blocked('query_context_changed')
        self.assert_valid(full=True)

    def prepare_names(self):
        facts=[]
        for kind in ('namechange','stock_basic'):
            with self.pinned(kind,['full']) as (paths,manifest):
                facts.extend(manifest)
        version=source_version(self.scope,self.initials.version,[facts])
        if version!=self.name_version:
            for kind in ('stock_basic','namechange'):
                expected={r['partition']:r for r in facts if r['source_kind']==kind}
                with self.pinned(kind,['full'],expected) as (paths,_):
                    fields='ts_code,name,cnspell' if kind=='stock_basic' else "ts_code,name,NULL::VARCHAR AS cnspell"
                    self.sql(f'CREATE OR REPLACE TEMP TABLE {kind}_names AS SELECT DISTINCT {fields} FROM read_parquet(?,hive_partitioning=false)',[paths],0)
                    # Conversion on the small, grouped name snapshots, never per keypress.
                    self.sql(f'ALTER TABLE {kind}_names ADD COLUMN initials VARCHAR',limit=0)
                    self.sql(f'UPDATE {kind}_names SET initials=CASE WHEN cnspell IS NOT NULL AND length(trim(cnspell))>0 THEN upper(cnspell) ELSE name_initials(name,ts_code) END',limit=0)
            self.name_version=version;self.range_version=None
        self.validate_manifest([facts])
        return facts

    def projection(self,paths,partitions,conditions):
        values=','.join('(?,?)' for _ in paths)
        args=[v for pair in zip(paths,partitions) for v in pair]
        args.extend([URL_WHITESPACE,URL_WHITESPACE,paths,conditions['tsCode'],conditions['tsCode'],conditions['titleKeyword'],conditions['titleKeyword']])
        sql=f'''WITH files(path,day) AS (VALUES {values}), projected AS (
            SELECT r.ann_date AS raw_ann_date,f.day AS ann_date,r.ts_code,r.name,r.title,r.url,r.rec_time,
            sha256(to_json(list_value('dg-anns-d-v1',r.ann_date,r.ts_code,r.name,r.title,r.url,r.rec_time))) AS record_key,
            CASE WHEN length(trim(coalesce(r.url,''),?))=0 THEN NULL ELSE
              sha256(to_json(list_value(f.day,r.ts_code,trim(r.url,?)))) END AS artifact_key
            FROM read_parquet(?,hive_partitioning=false,filename=true) r JOIN files f ON r.filename=f.path
            WHERE (? IS NULL OR r.ts_code=?) AND (?='' OR contains(coalesce(r.title,''),?)))'''
        return sql,args

    def validate_days(self,paths,partitions):
        values=','.join('(?,?)' for _ in paths)
        args=[v for pair in zip(paths,partitions) for v in pair]+[paths]
        bad=self.sql(f'''WITH files(path,day) AS (VALUES {values}) SELECT count(*) FROM read_parquet(?,hive_partitioning=false,filename=true) r
            JOIN files f ON r.filename=f.path WHERE r.ann_date IS NULL OR r.ann_date<>replace(f.day,'-','')''',args,1)[0][0]
        if bad:raise Blocked('source_partition_mismatch')

    def set_presence(self,rows):
        self.sql('CREATE OR REPLACE TEMP TABLE unit_presence(artifact_key VARCHAR PRIMARY KEY)',limit=0)
        for batch in rows:
            if len(batch)>500:raise ValueError('presence_batch_limit')
            keys=[r['artifact_key'] for r in batch]
            if keys:self.sql('INSERT INTO unit_presence SELECT unnest(?) ON CONFLICT DO NOTHING',[keys],0)

    @staticmethod
    def filtered(conditions):
        status=conditions['downloadStatus']
        if status=='all':return 'projected'
        return '(SELECT projected.* FROM projected '+('SEMI' if status=='downloaded' else 'ANTI')+' JOIN unit_presence USING(artifact_key))'

    def count_unit(self,partitions,conditions,expected=None):
        with self.pinned('anns_d',partitions,expected) as (paths,facts):
            self.validate_days(paths,partitions)
            sql,args=self.projection(paths,partitions,conditions)
            counts=dict(self.sql(sql+' SELECT ann_date,count(*) FROM '+self.filtered(conditions)+' GROUP BY ann_date',args,len(partitions)))
        return facts,[(day,counts.get(day,0)) for day in partitions]

    def page_day(self,day,conditions,offset,take,expected):
        with self.pinned('anns_d',[day],{day:expected}) as (paths,_):
            sql,args=self.projection(paths,[day],conditions)
            from .company_source import CompanySource
            # Reuse range name ranking; no row-specific company-name invention.
            company=CompanySource.cte().removeprefix('WITH ')
            result=self.sql(sql+', '+company+' SELECT p.*,c.display_name,c.name_source FROM '+self.filtered(conditions)+                ' p LEFT JOIN companies c ON c.ts_code=p.ts_code ORDER BY p.ann_date DESC,p.ts_code ASC NULLS LAST,p.record_key ASC LIMIT ? OFFSET ?',args+[take,offset],take)
            columns=[r[0] for r in self.connection.description]
            return [dict(zip(columns,row)) for row in result]

    def preview_start(self,day,conditions,expected=None):
        with self.pinned('anns_d',[day],{day:expected} if expected else None,content=True) as (paths,facts):
            self.validate_days(paths,[day]);sql,args=self.projection(paths,[day],conditions)
            missing=self.sql(sql+' SELECT count(*) FROM projected WHERE artifact_key IS NULL',args,1)[0][0]
        if expected and facts[0]['sha256']!=expected['sha256']:raise Blocked('source_file_changed')
        return facts[0],missing

    def preview_keys(self,day,conditions,after,facts):
        with self.pinned('anns_d',[day],{day:facts}) as (paths,_):
            sql,args=self.projection(paths,[day],conditions)
            return [r[0] for r in self.sql(sql+' SELECT DISTINCT artifact_key FROM projected WHERE artifact_key>? ORDER BY artifact_key LIMIT 500',args+[after])]

    def latest_date(self,end):
        """Latest physical partition, including valid zero-row days; never skip damage."""
        latest=self.observed_date()
        if latest is not None and latest<=end:
            with self.pinned('anns_d',[latest]):pass
        return latest

    def observed_date(self):
        self.volume.assert_valid()
        maximum=None
        # Directory inventory only. No Parquet scan or inferred DG successful check.
        with os.scandir(self.volume.root_fd) as entries:
            for item in entries:
                self.control.check()
                if re.fullmatch(r'ann_date=\d{4}-\d{2}-\d{2}',item.name) and item.is_dir(follow_symlinks=False):
                    day=item.name[9:]
                    try:date.fromisoformat(day)
                    except ValueError:continue
                    if maximum is None or day>maximum:maximum=day
        return maximum

    def close(self):
        self.control.stop.set()
        with self.lock:self.connection.close()
        self.volume.close();self.names_volume.close()
