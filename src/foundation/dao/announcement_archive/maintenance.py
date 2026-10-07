"""Bounded PG ledger observations; positive integer cursors refer to row_seq."""
import json
import time
import threading
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from dataclasses import dataclass
from src.foundation.clients.announcement_archive.core import Blocked

ARTIFACT_STATES=('pending','downloading','prepared','succeeded','failed','blocked')


@dataclass(frozen=True)
class LedgerQueryPolicy:
    page_default:int=20
    page_max:int=100
    query_timeout_seconds:float=4


class LedgerQuery:
    def __init__(self,ledger,control,policy=LedgerQueryPolicy()):
        if not 0<policy.page_default<=policy.page_max<=100 or not 0<policy.query_timeout_seconds<=4:raise ValueError('ledger_query_policy_invalid')
        self.ledger,self.control,self.policy=ledger,control,policy
        self.deadline=time.monotonic()+policy.query_timeout_seconds
        self.archive=ledger.archive

    def query(self,sql,params=None):
        self.control.check()
        if time.monotonic()>=self.deadline:raise Blocked('ledger_query_timeout')
        done=threading.Event()
        with self.ledger.transaction(read_only=True) as conn:
            seconds=self.deadline-time.monotonic()
            conn.execute(text("SELECT set_config('statement_timeout',:ms,true)"),dict(ms=str(max(1,int(seconds*1000)))))
            driver=conn.connection.driver_connection
            def watch():
                while not done.wait(.01):
                    if self.control.stop.is_set():
                        try:driver.cancel()
                        except Exception:pass
                        return
            thread=threading.Thread(target=watch,name='archive-query-cancel',daemon=True);thread.start()
            try:
                rows=self.ledger.rows(sql,params,conn=conn)
            except (Blocked,SQLAlchemyError):
                self.control.check()
                if time.monotonic()>=self.deadline:raise Blocked('ledger_query_timeout') from None
                raise
            finally:done.set();thread.join(timeout=1)
        self.control.check()
        if time.monotonic()>=self.deadline:raise Blocked('ledger_query_timeout')
        return rows

    def page(self,sql,params,limit,cursor_column,cursor_name):
        if type(limit) is not int or not 1<=limit<=self.policy.page_max:raise ValueError('ledger_page_limit_invalid')
        rows=self.query(sql+' LIMIT :limit',dict(params,limit=limit+1));more=len(rows)>limit;items=rows[:limit]
        return dict(items=items,limit=limit,has_more=more,**{cursor_name:items[-1][cursor_column] if more else None})

    @staticmethod
    def cursor(value):
        if value is not None and (type(value) is not int or not 0<value<2**63):raise ValueError('archive_cursor_invalid')
        return value

    def summary(self):
        return dict(archive=self.archive,files=self.query('SELECT state,COUNT(*) AS count FROM announcement_archive.artifacts WHERE archive_id=:a GROUP BY state'),dates=self.query('SELECT MIN(ann_date) AS first_date,MAX(ann_date) AS last_date,COUNT(*) AS file_tasks FROM announcement_archive.artifacts WHERE archive_id=:a')[0],sources=self.query('SELECT COUNT(*) AS records,COUNT(*) FILTER(WHERE artifact_key IS NULL) AS missing_url FROM announcement_archive.source_records WHERE archive_id=:a')[0],latest_run=self.runs(1)['items'],physical_status='not_checked')

    def runs(self,limit,before_rowid=None,run_id=None):
        sql='SELECT row_seq AS ledger_rowid,* FROM announcement_archive.runs WHERE archive_id=:a';p={}
        if before_rowid is not None:sql+=' AND row_seq<:before';p['before']=self.cursor(before_rowid)
        if run_id:sql+=' AND run_id=:run';p['run']=run_id
        return self.page(sql+' ORDER BY row_seq DESC',p,limit,'ledger_rowid','next_before_rowid')

    def files(self,limit,*,start_date=None,end_date=None,ts_code=None,title=None,state=None,run_id=None,after_key=None):
        sql='SELECT a.* FROM announcement_archive.artifacts a WHERE a.archive_id=:a';p={}
        if state is not None and state not in ARTIFACT_STATES:raise ValueError('ledger_state_invalid')
        for column,op,value in [('ann_date','>=',start_date),('ann_date','<=',end_date),('ts_code','=',ts_code),('state','=',state),('artifact_key','>',after_key)]:
            if value is not None:
                name='p'+str(len(p));sql+=f' AND a.{column}{op}:{name}';p[name]=str(value)
        if title is not None:sql+=' AND strpos(a.title,:title)>0';p['title']=title
        if run_id:sql+=' AND EXISTS(SELECT 1 FROM announcement_archive.run_artifacts r WHERE r.archive_id=a.archive_id AND r.artifact_key=a.artifact_key AND r.run_id=:run)';p['run']=run_id
        result=self.page(sql+' ORDER BY a.artifact_key',p,limit,'artifact_key','next_after_key')
        for row in result['items']:row['physical_status']='not_checked'
        return result

    def artifact(self,key):
        rows=self.query('SELECT * FROM announcement_archive.artifacts WHERE archive_id=:a AND artifact_key=:key',dict(key=key))
        if not rows:raise Blocked('artifact_not_found')
        return rows[0]

    def show(self,key,limit,after_rowid=None):
        artifact=self.artifact(key);artifact['physical_status']='not_checked'
        sql='SELECT row_seq AS ledger_rowid,source_scope,record_key,legacy_raw_id,metadata,first_seen_run,last_seen_run FROM announcement_archive.source_records WHERE archive_id=:a AND artifact_key=:key';p=dict(key=key)
        if after_rowid is not None:sql+=' AND row_seq>:after';p['after']=self.cursor(after_rowid)
        sources=self.page(sql+' ORDER BY row_seq',p,limit,'ledger_rowid','next_after_rowid')
        for row in sources['items']:
            try:row['metadata']=json.loads(row['metadata'])
            except (TypeError,ValueError):raise Blocked('ledger_metadata_invalid') from None
        return dict(artifact=artifact,sources=sources)
