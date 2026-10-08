"""SQL company ranking on source-version-bound small names, no persistent dictionary."""
from .direct_source import batches,days
from .names import normalized_name


class CompanySource:
    def __init__(self,source):self.source=source

    def prepare(self,controls,query_id,conditions,version):
        source=self.source
        if source.range_version==version:return
        source.sql('CREATE OR REPLACE TEMP TABLE range_names(ts_code VARCHAR,name VARCHAR,ann_date VARCHAR,record_key VARCHAR)',limit=0)
        for manifest in controls.files(query_id):
            for batch in batches([r for r in manifest if r['source_kind']=='anns_d'],source.policy.file_batch_size):
                parts=[r['partition'] for r in batch];expected={r['partition']:r for r in batch}
                with source.pinned('anns_d',parts,expected) as (paths,_):
                    sql,args=source.projection(paths,parts,dict(conditions,tsCode=None,titleKeyword='',downloadStatus='all'))
                    source.sql(sql+''' INSERT INTO range_names SELECT ts_code,coalesce(name,''),max(ann_date),min(record_key)
                        FROM projected WHERE ts_code IS NOT NULL GROUP BY ts_code,coalesce(name,'')''',args,0)
        source.sql('''CREATE OR REPLACE TEMP TABLE announcement_names AS SELECT ts_code,name,max(ann_date) ann_date,min(record_key) record_key,
            name_initials(name,ts_code) initials FROM range_names GROUP BY ts_code,name''',limit=0)
        source.sql('DROP TABLE range_names',limit=0)
        source.range_version=version

    @staticmethod
    def cte(include_announcements=True):
        announcements = 'UNION ALL SELECT ts_code,name,initials,\'announcement\',ann_date,record_key FROM announcement_names' if include_announcements else ''
        return '''WITH aliases AS (
          SELECT ts_code,coalesce(name,'') AS name,initials,'master' AS kind,'' AS ann_date,'' AS record_key FROM stock_basic_names
          UNION ALL SELECT ts_code,coalesce(name,''),initials,'history','','' FROM namechange_names
        ''' + announcements + '''), ranked AS (
          SELECT *,row_number() OVER(PARTITION BY ts_code ORDER BY
            CASE WHEN kind='master' AND length(trim(name))>0 THEN 0 WHEN kind='announcement' AND length(trim(name))>0 THEN 1 ELSE 2 END,
            ann_date DESC,record_key,name) pos FROM aliases WHERE kind<>'history'
        ), companies AS (
          SELECT codes.ts_code,CASE WHEN length(trim(coalesce(n.name,'')))>0 THEN n.name ELSE codes.ts_code END display_name,
            CASE WHEN length(trim(coalesce(n.name,'')))=0 THEN 'code' ELSE n.kind END name_source,n.initials
          FROM (SELECT DISTINCT ts_code FROM aliases WHERE ts_code IS NOT NULL) codes LEFT JOIN ranked n ON n.ts_code=codes.ts_code AND n.pos=1
        )'''

    def search(self,keyword,limit,*,include_announcements=True):
        key=normalized_name(keyword);upper=key.upper()
        sql=self.cte(include_announcements)+''', matches AS (
          SELECT c.*,CASE WHEN upper(c.ts_code)=? THEN 0 WHEN substr(c.ts_code,1,6)=? THEN 1
            WHEN starts_with(upper(c.ts_code),?) THEN 2 WHEN normalized_name(display_name)=? THEN 3
            WHEN contains(normalized_name(display_name),?) THEN 4 WHEN starts_with(initials,?) THEN 5
            WHEN EXISTS(SELECT 1 FROM aliases a WHERE a.ts_code=c.ts_code AND
              (contains(normalized_name(a.name),?) OR starts_with(a.initials,?))) THEN 6 ELSE 99 END rank
          FROM companies c
        ) SELECT *,CASE WHEN rank=6 THEN (SELECT a.name FROM aliases a WHERE a.ts_code=matches.ts_code
            AND (contains(normalized_name(a.name),?) OR starts_with(a.initials,?))
            ORDER BY a.name,a.kind,a.ann_date DESC LIMIT 1) END matched_alias FROM matches WHERE rank<99 ORDER BY rank,ts_code LIMIT ?'''
        rows=self.source.sql(sql,[upper,upper,upper,key,key,upper,key,upper,key,upper,limit+1],limit+1)
        columns=[r[0] for r in self.source.connection.description]
        kinds={0:'exactCode',1:'exactCode',2:'codePrefix',3:'name',4:'name',5:'initials',6:'alias'}
        values=[dict(zip(columns,row)) for row in rows]
        return dict(keyword=keyword,hasMore=len(values)>limit,items=[dict(tsCode=r['ts_code'],name=r['display_name'],initials=r['initials'],
            matchedAlias=r['matched_alias'],nameSource=r['name_source'],matchKind=kinds[r['rank']]) for r in values[:limit]])
