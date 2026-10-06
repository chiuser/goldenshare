"""Company presentation and ranking over published local name facts."""
from src.foundation.clients.announcement_archive.names import normalized_name


def company_cte():
    return '''WITH aliases AS (
      SELECT s.* FROM company_sources s,catalog_meta m
      WHERE m.singleton=1 AND ((s.source_kind IN ('raw_master','history') AND s.generation=m.name_generation)
        OR (s.source_kind='announcement' AND s.ann_date BETWEEN :start AND :end AND EXISTS(
          SELECT 1 FROM catalog_days d WHERE d.ann_date=s.ann_date AND d.active_generation=s.generation)))
    ), ranked AS (
      SELECT *,ROW_NUMBER() OVER(PARTITION BY ts_code ORDER BY
        CASE WHEN source_kind='raw_master' AND trim(name)<>'' THEN 0
             WHEN source_kind='announcement' AND trim(name)<>'' THEN 1 ELSE 2 END,
        ann_date DESC,record_key,name) AS position
      FROM aliases WHERE source_kind<>'history'
    ), companies AS (
      SELECT codes.ts_code,
        CASE WHEN trim(COALESCE(n.name,''))<>'' THEN n.name ELSE codes.ts_code END AS display_name,
        CASE WHEN trim(COALESCE(n.name,''))='' THEN 'code'
             WHEN n.source_kind='raw_master' THEN 'master' ELSE 'announcement' END AS name_source,
        CASE WHEN trim(COALESCE(n.name,''))<>'' THEN n.name_normalized ELSE lower(codes.ts_code) END AS normalized,
        n.initials FROM (SELECT DISTINCT ts_code FROM aliases) codes
        LEFT JOIN ranked n ON n.ts_code=codes.ts_code AND n.position=1
    )'''


class CompanyQuery:
    def __init__(self,catalog,policy):
        self.catalog,self.policy=catalog,policy

    def search(self,keyword,start,end):
        query = normalized_name(keyword)
        if not query:
            return dict(keyword=keyword,items=[],hasMore=False)
        sql = company_cte()+''', matches AS (
          SELECT c.*,
            CASE WHEN upper(c.ts_code)=:key THEN 0
                 WHEN substr(c.ts_code,1,6)=:key THEN 1
                 WHEN substr(upper(c.ts_code),1,length(:key))=:key THEN 2
                 WHEN c.normalized=:name THEN 3
                 WHEN instr(c.normalized,:name)>0 THEN 4
                 WHEN substr(c.initials,1,length(:key))=:key THEN 5
                 WHEN EXISTS(SELECT 1 FROM aliases a WHERE a.ts_code=c.ts_code
                   AND (instr(a.name_normalized,:name)>0 OR substr(a.initials,1,length(:key))=:key)) THEN 6
                 ELSE 99 END AS rank
          FROM companies c
        ) SELECT *,CASE WHEN rank=6 THEN (
          SELECT a.name FROM aliases a WHERE a.ts_code=matches.ts_code
            AND (instr(a.name_normalized,:name)>0 OR substr(a.initials,1,length(:key))=:key)
          ORDER BY a.name,a.source_kind,a.ann_date DESC LIMIT 1) END AS matched_alias
          FROM matches WHERE rank<99 ORDER BY rank,ts_code LIMIT :limit'''
        with self.catalog.connection() as conn:
            rows = conn.execute(sql,dict(start=start,end=end,key=query.upper(),name=query,limit=self.policy.company_limit+1)).fetchmany(self.policy.company_limit+1)
        kinds = {0:'exactCode',1:'exactCode',2:'codePrefix',3:'name',4:'name',5:'initials',6:'alias'}
        return dict(keyword=keyword,hasMore=len(rows)>self.policy.company_limit,items=[dict(
            tsCode=r['ts_code'],name=r['display_name'],initials=r['initials'],matchedAlias=r['matched_alias'],
            nameSource=r['name_source'],matchKind=kinds[r['rank']]) for r in rows[:self.policy.company_limit]])
