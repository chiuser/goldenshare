"""Stable row order and whole-scope status filtering before count/page."""
from .company_query import company_cte


def bindings(conditions):
    return dict(start=conditions['startDate'],end=conditions['endDate'],code=conditions['tsCode'],title=conditions['titleKeyword'])


def matching_sql():
    return ''' FROM catalog_records r JOIN catalog_days d
      ON r.ann_date=d.ann_date AND r.generation=d.active_generation
      WHERE r.ann_date BETWEEN :start AND :end AND (:code IS NULL OR r.ts_code=:code)
      AND (:title='' OR instr(COALESCE(r.title,''),:title)>0)'''


class AnnouncementQuery:
    def __init__(self,catalog,policy):
        self.catalog,self.policy=catalog,policy

    def keys(self,conditions,after=''):
        with self.catalog.connection() as conn:
            return [r[0] for r in conn.execute('SELECT DISTINCT r.artifact_key'+matching_sql()+
              ' AND r.artifact_key IS NOT NULL AND r.artifact_key>:after ORDER BY r.artifact_key LIMIT 500',
              dict(bindings(conditions),after=after)).fetchmany(500)]

    def filtered_where(self,conditions):
        where=matching_sql()
        if conditions['downloadStatus']=='downloaded':
            where+=' AND r.artifact_key IN (SELECT artifact_key FROM query_presence WHERE query_id=:query_id)'
        elif conditions['downloadStatus']=='undownloaded':
            where+=' AND (r.artifact_key IS NULL OR r.artifact_key NOT IN (SELECT artifact_key FROM query_presence WHERE query_id=:query_id))'
        return where

    def prepare_counts(self,query_id,conditions,check=lambda:None):
        after=''
        while days:=self.catalog.days_after(conditions['startDate'],conditions['endDate'],after):
            for day in days:
                check()
                if conditions['tsCode'] is None and not conditions['titleKeyword'] and conditions['downloadStatus']=='all':
                    count=day['footer_count']
                else:
                    parameters=dict(bindings(conditions),query_id=query_id,day=day['ann_date'],generation=day['active_generation'])
                    where=self.filtered_where(conditions)+' AND r.ann_date=:day AND r.generation=:generation'
                    with self.catalog.connection() as conn:
                        count=conn.execute('SELECT COUNT(*)'+where,parameters).fetchone()[0]
                self.catalog.query_counts(query_id,[(day['ann_date'],day['active_generation'],count)])
            after=days[-1]['ann_date']

    def page(self,query_id,conditions,page,revision):
        parameters=dict(bindings(conditions),query_id=query_id)
        with self.catalog.connection() as conn:
            if conn.execute('SELECT revision FROM catalog_meta WHERE singleton=1').fetchone()[0]!=revision:
                from src.foundation.clients.announcement_archive.core import Blocked
                raise Blocked('query_context_changed')
            # These derived counts were sealed under the same revision and exact WHERE as the rows.
            summary=conn.execute('''SELECT COALESCE(SUM(c.match_count),0),COUNT(*),
                COALESCE(SUM(d.active_generation IS NULL OR c.generation<>d.active_generation),0)
                FROM query_day_counts c LEFT JOIN catalog_days d ON d.ann_date=c.ann_date
                WHERE c.query_id=:query_id AND c.ann_date BETWEEN :start AND :end''',parameters).fetchone()
            from datetime import date
            expected_days=(date.fromisoformat(conditions['endDate'])-date.fromisoformat(conditions['startDate'])).days+1
            if summary[1]!=expected_days or summary[2]:
                from src.foundation.clients.announcement_archive.core import Blocked
                raise Blocked('query_context_changed')
            total=summary[0]
            offset=(page-1)*self.policy.page_size
            if offset>=total:
                return total,[],set()
            # Only read bounded day-count batches. A deep page never skips all preceding record rows.
            days=[];before='9999-12-32';remaining=self.policy.page_size
            while remaining and (batch:=conn.execute('SELECT ann_date,generation,match_count FROM query_day_counts WHERE query_id=? AND ann_date BETWEEN ? AND ? AND ann_date<? AND match_count>0 ORDER BY ann_date DESC LIMIT 500',
                                                       (query_id,conditions['startDate'],conditions['endDate'],before)).fetchmany(500)):
                for day in batch:
                    if offset>=day['match_count']:
                        offset-=day['match_count'];continue
                    take=min(remaining,day['match_count']-offset)
                    days.append((day['ann_date'],day['generation'],offset,take))
                    remaining-=take;offset=0
                    if not remaining:break
                before=batch[-1]['ann_date']
            keys=[]
            where=self.filtered_where(conditions)+' AND r.ann_date=:day AND r.generation=:generation'
            where=where.replace('catalog_records r JOIN','catalog_records r INDEXED BY catalog_order JOIN')
            for day,generation,local_offset,take in days:
                values=dict(parameters,day=day,generation=generation,offset=local_offset,limit=take)
                keys.extend(conn.execute('SELECT r.ann_date,r.generation,r.record_key'+where+'''
                    ORDER BY r.ann_date DESC,(r.ts_code IS NULL),r.ts_code,r.record_key LIMIT :limit OFFSET :offset''',values).fetchmany(take))
            if not keys:
                return total,[],set()
            values=','.join(f'(:day{i},:generation{i},:key{i})' for i in range(len(keys)))
            for i,key in enumerate(keys):
                parameters.update({f'day{i}':key['ann_date'],f'generation{i}':key['generation'],f'key{i}':key['record_key']})
            rows=conn.execute(company_cte()+', selected(ann_date,generation,record_key) AS (VALUES '+values+''')
                SELECT r.*,c.display_name,c.name_source FROM selected s
                JOIN catalog_records r ON r.ann_date=s.ann_date AND r.generation=s.generation AND r.record_key=s.record_key
                LEFT JOIN companies c ON c.ts_code=r.ts_code
                ORDER BY r.ann_date DESC,(r.ts_code IS NULL),r.ts_code,r.record_key''',parameters).fetchmany(self.policy.page_size)
            present={r[0] for r in conn.execute('SELECT artifact_key FROM query_presence WHERE query_id=? AND artifact_key IN ('
                +','.join('?' for _ in rows)+')',(query_id,*(r['artifact_key'] for r in rows))).fetchmany(self.policy.page_size)}
        return total,[dict(row) for row in rows],present
