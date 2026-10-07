"""Archive-scoped, short lived PG controls; no announcement row projection."""
from contextlib import contextmanager
import json
import time
import uuid

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.foundation.clients.announcement_archive.core import Blocked, identity, timestamp
from src.foundation.config.announcement_archive import DataCenterPolicy
from .pg_archive import placeholders
from .pg_schema import TABLES, qualified, validate_schema, VERSION, DDL_SHA256
from src.foundation.clients.announcement_archive.budget import remaining

OBJECTS = {'query': ('query_snapshots', 'query_id', ('query_files', 'query_day_counts', 'query_presence')),
           'preview': ('previews', 'preview_id', ('preview_days', 'preview_artifacts'))}


class QueryControls:
    def __init__(self, database, archive_id, scope, policy=DataCenterPolicy()):
        self.database, self.archive_id, self.scope, self.policy = database, archive_id, scope, policy
        with database.transaction(read_only=True) as conn:
            validate_schema(conn)
            self.assert_ready(conn)

    def assert_ready(self, conn):
        info=conn.execute(text('SELECT a.import_state,s.version,s.ddl_sha256 FROM announcement_archive.archives a CROSS JOIN announcement_archive.schema_info s WHERE a.archive_id=:a AND s.singleton=1'), {'a':self.archive_id}).first()
        if info is not None and tuple(info[1:])!=(VERSION,DDL_SHA256):raise Blocked('archive_schema_invalid')
        state=info[0] if info else None
        if state != 'ready':
            raise Blocked('archive_import_incomplete' if state else 'archive_not_found')

    @contextmanager
    def transaction(self, *, read_only=False):
        with self.database.transaction(read_only=read_only) as conn:
            conn.execute(text("SELECT set_config('statement_timeout',:milliseconds,true)"), {'milliseconds':str(max(1,int(remaining(self.policy.sql_seconds)*1000)))})
            self.assert_ready(conn)
            yield conn

    def rows(self, table, where='', params=None, *, order='', limit=500):
        if table not in TABLES or 'archive_id' not in TABLES[table]['columns'] or not 1 <= limit <= 500:
            raise ValueError('archive_query_invalid')
        with self.transaction(read_only=True) as conn:
            return [dict(r) for r in conn.execute(text(f'SELECT * FROM {qualified(table)} WHERE archive_id=:a '
                + where + (' ORDER BY ' + order if order else '') + ' LIMIT :limit'),
                dict(params or {}, a=self.archive_id, limit=limit)).mappings()]

    def get(self, kind, object_id):
        table, key, _ = OBJECTS[kind]
        rows = self.rows(table, f'AND {key}=:id', {'id': object_id}, limit=1)
        return rows[0] if rows else None

    def query(self, object_id): return self.get('query', object_id)
    def preview(self, object_id): return self.get('preview', object_id)

    def insert(self, conn, table, rows, *, ignore=False):
        if not rows: return []
        if len(rows) > 500: raise ValueError('archive_batch_invalid')
        columns = list(rows[0])
        if not set(columns) <= set(TABLES[table]['columns']) - {'archive_id'} or any(set(r) != set(columns) for r in rows):
            raise ValueError('archive_columns_invalid')
        values, params = placeholders(rows, columns)
        params['a'] = self.archive_id
        values = values.replace('(', '(:a,')
        return [dict(r) for r in conn.execute(text(f'INSERT INTO {qualified(table)} (archive_id,{",".join(columns)}) VALUES '
            + values + (' ON CONFLICT DO NOTHING' if ignore else '') + ' RETURNING *'), params).mappings()]

    def create_query(self, query_id, conditions):
        from datetime import date
        now = timestamp()
        row = dict(query_id=query_id,source_scope=self.scope,conditions=json.dumps(conditions,ensure_ascii=False),
            state='preparing',status_available=0,created_at=now,updated_at=now,preparation_stage='readingSource',
            dates_total=(date.fromisoformat(conditions['endDate'])-date.fromisoformat(conditions['startDate'])).days+1)
        with self.transaction() as conn: self.insert(conn, 'query_snapshots', [row])

    def create_preview(self, preview_id, start, end, interval, archive_id):
        from datetime import date
        if archive_id != self.archive_id: raise Blocked('preview_stale')
        now = timestamp()
        with self.transaction() as conn:
            self.insert(conn,'previews',[dict(preview_id=preview_id,start_date=start,end_date=end,interval_seconds=interval,
                source_scope=self.scope,state='preparing',created_at=now,updated_at=now,
                dates_total=(date.fromisoformat(end)-date.fromisoformat(start)).days+1)])

    def update(self, conn, kind, object_id, values, *, owner=None, preparing=False):
        table, key, _ = OBJECTS[kind]
        if not set(values) <= set(TABLES[table]['columns']) - {'archive_id',key}: raise ValueError('archive_columns_invalid')
        params = dict(values,a=self.archive_id,id=object_id,owner=owner)
        sql = f'UPDATE {qualified(table)} SET ' + ','.join(f'{c}=:{c}' for c in values)
        sql += f' WHERE archive_id=:a AND {key}=:id'
        if owner: sql += ' AND owner_token=:owner'
        if preparing: sql += " AND state='preparing'"
        if conn.execute(text(sql),params).rowcount != 1: raise Blocked('query_claim_lost')

    def save_unit(self, kind, object_id, owner, details, values):
        with self.transaction() as conn:
            for table, rows in details.items(): self.insert(conn,table,rows,ignore=table in {'query_presence','preview_artifacts'})
            self.update(conn,kind,object_id,dict(values,updated_at=timestamp()),owner=owner,preparing=True)

    def finish(self, kind, object_id, owner, **values):
        with self.transaction() as conn:
            self.update(conn,kind,object_id,dict(values,updated_at=timestamp(),expires_at=time.time()+self.policy.ttl_seconds),owner=owner,preparing=True)

    def cancel_preview(self, object_id):
        row = self.preview(object_id)
        if row is None: raise Blocked('preview_not_found')
        if row['state'] == 'preparing':
            with self.transaction() as conn:
                self.update(conn,'preview',object_id,dict(state='cancelled',updated_at=timestamp(),expires_at=time.time()+self.policy.ttl_seconds),preparing=True)

    def pending(self):
        for kind,(table,_,_) in OBJECTS.items():
            rows=self.rows(table,"AND state='preparing'",order='created_at',limit=1)
            if rows: return kind,rows[0]
        return None

    @contextmanager
    def claim(self, kind, object_id):
        """Session lock outlives short transactions, released even on pooled connection return."""
        number=int(identity([self.archive_id,kind,object_id])[:16],16)
        if number >= 2**63: number -= 2**64
        connection=None;locked=False
        try:
            connection=self.database.engine.connect()
            locked=bool(connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':number}));connection.commit()
            if not locked: yield None; return
            owner=uuid.uuid4().hex
            row=self.get(kind,object_id)
            if not row or row['state']!='preparing': yield None; return
            with self.transaction() as conn:
                self.update(conn,kind,object_id,dict(owner_token=owner,dates_scanned=0,records_scanned=0,updated_at=timestamp(),
                    **(dict(preparation_stage='readingSource',artifacts_checked=0,total=None,source_version=None,checked_at=None,status_available=0) if kind=='query' else dict(statistics=None,source_version=None))),preparing=True)
            # Interrupted unsealed controls have no published meaning; clear in bounded transactions.
            for table in OBJECTS[kind][2]:
                while self.delete_batch(table,OBJECTS[kind][1],object_id):
                    self.check_claim(connection,kind,object_id,owner)
            yield owner,connection
        except SQLAlchemyError:
            raise Blocked('archive_database_unavailable') from None
        finally:
            if connection is not None:
                try:
                    if locked:
                        connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':number});connection.commit()
                except SQLAlchemyError: connection.invalidate()
                connection.close()

    def check_claim(self, connection, kind, object_id, owner):
        connection.execute(text('SELECT 1'));connection.commit()
        row=self.get(kind,object_id)
        if not row or row['owner_token']!=owner: raise Blocked('query_claim_lost')
        if row['state']=='cancelled': raise Blocked('preview_cancelled')
        if row['state']!='preparing': raise Blocked('query_claim_lost')

    def delete_batch(self, table, key, object_id):
        with self.transaction() as conn:
            return conn.execute(text(f'DELETE FROM {qualified(table)} WHERE ctid IN (SELECT ctid FROM {qualified(table)} '
                f'WHERE archive_id=:a AND {key}=:id LIMIT :limit)'),
                {'a':self.archive_id,'id':object_id,'limit':self.policy.gc_batch_size}).rowcount

    def files(self, query_id):
        after=('','')
        while rows:=self.rows('query_files', 'AND query_id=:id AND (source_kind,partition)>(:kind,:partition)',
                {'id':query_id,'kind':after[0],'partition':after[1]},order='source_kind,partition'):
            yield rows
            after=(rows[-1]['source_kind'],rows[-1]['partition'])

    def validate_counts(self,query_id,expected_days,expected_total):
        with self.transaction(read_only=True) as conn:
            result=conn.execute(text('SELECT count(*),coalesce(sum(match_count),0) FROM announcement_archive.query_day_counts WHERE archive_id=:a AND query_id=:id'),dict(a=self.archive_id,id=query_id)).first()
            files=conn.scalar(text('SELECT count(*) FROM announcement_archive.query_files WHERE archive_id=:a AND query_id=:id'),dict(a=self.archive_id,id=query_id))
        if tuple(result)!=(expected_days,expected_total) or files!=expected_days+2:raise Blocked('query_context_changed')

    def day_counts(self, query_id):
        before='9999-12-32'
        while rows:=self.rows('query_day_counts','AND query_id=:id AND ann_date<:before',
                {'id':query_id,'before':before},order='ann_date DESC'):
            yield rows; before=rows[-1]['ann_date']

    def successful(self, conditions, after=''):
        return self.rows('artifacts',"AND state='succeeded' AND ann_date BETWEEN :start AND :end AND artifact_key>:after "
            'AND (CAST(:code AS TEXT) IS NULL OR ts_code=:code)',dict(start=conditions['startDate'],end=conditions['endDate'],code=conditions['tsCode'],after=after),order='artifact_key')

    def artifact_rows(self, keys):
        if not keys:return []
        if len(keys)>500:raise ValueError('presence_batch_limit')
        params={f'k{i}':key for i,key in enumerate(keys)}
        return self.rows('artifacts',"AND state='succeeded' AND artifact_key IN ("+','.join(':'+k for k in params)+')',params)

    def presence_keys(self, query_id, after='', *, day=None, code=None):
        if day is None:
            return self.rows('query_presence','AND query_id=:id AND artifact_key>:after',{'id':query_id,'after':after},order='artifact_key')
        # Only related successful keys; title filtering stays in DuckDB.
        with self.transaction(read_only=True) as conn:
            return [dict(r) for r in conn.execute(text('SELECT p.artifact_key FROM announcement_archive.query_presence p '
                'JOIN announcement_archive.artifacts a ON a.archive_id=p.archive_id AND a.artifact_key=p.artifact_key '
                'WHERE p.archive_id=:a AND p.query_id=:id AND a.ann_date=:day AND (CAST(:code AS TEXT) IS NULL OR a.ts_code=:code) '
                'AND p.artifact_key>:after ORDER BY p.artifact_key LIMIT 500'),
                dict(a=self.archive_id,id=query_id,day=day,code=code,after=after)).mappings()]

    def preview_day(self, object_id, day):
        rows=self.rows('preview_days','AND preview_id=:id AND ann_date=:day',dict(id=object_id,day=day),limit=1)
        return rows[0] if rows else None

    def gc(self, check=lambda:None):
        deadline=time.monotonic()+self.policy.sql_seconds; removed=0
        for kind,(table,key,children) in OBJECTS.items():
            for row in self.rows(table,'AND expires_at<=:now AND state<>\'preparing\'',{'now':time.time()},order='expires_at'):
                check()
                if time.monotonic()>=deadline:return removed
                object_id=row[key]
                with self.transaction() as conn:
                    self.update(conn,kind,object_id,dict(state='expired',reason='query_context_changed' if kind=='query' else 'preview_stale'))
                for child in children:
                    while True:
                        check()
                        if time.monotonic()>=deadline:return removed
                        count=self.delete_batch(child,key,object_id);removed+=count
                        if not count:break
                with self.transaction() as conn:
                    if kind=='preview' and conn.scalar(text('SELECT 1 FROM announcement_archive.runs WHERE archive_id=:a AND preview_id=:id LIMIT 1'),dict(a=self.archive_id,id=object_id)):
                        self.update(conn,kind,object_id,dict(expires_at=None))
                    else:
                        conn.execute(text(f'DELETE FROM {qualified(table)} WHERE archive_id=:a AND {key}=:id'),dict(a=self.archive_id,id=object_id))
                removed+=1
        return removed
