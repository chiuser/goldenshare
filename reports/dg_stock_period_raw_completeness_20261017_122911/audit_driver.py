"""Read-only period coverage audit. Only temporary relations and report files are written."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
import hashlib,json,resource,time
from orchestrator.defs.duckdb_connection import connect_configured_duckdb,DuckDBConnectionSettings

WORK=Path('/private/tmp/dg_period_completeness_mjfo40k9')
probe=json.loads((WORK/'probe.json').read_text());ROOT=Path('/Volumes/datasource/data_lake')
OUT=Path('/Users/congming/github/goldenshare/reports')/('dg_stock_period_raw_completeness_'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S'))
OUT.mkdir();start=time.monotonic();timings=[];queries=[]
raw_files={f:sorted((ROOT/f'raw/tushare/stk_period_bar_adj_{f}').glob('*/*.parquet')) for f in ('week','month')}
susp_files=sorted((ROOT/'silver/quote/stock_suspend_daily').glob('*/*.parquet'))
refs={k:Path(v) for k,v in probe['paths'].items()}
all_files=[*refs.values(),*raw_files['week'],*raw_files['month'],*susp_files]
def version(p):
 s=p.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]
before={str(p):version(p) for p in all_files}
(WORK/'input_versions.json').write_text(json.dumps(before))
settings=DuckDBConnectionSettings(temp_directory=WORK/'spill',memory_limit='3GiB',threads=2,max_temp_directory_size='8GiB')
summary={'observed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'report_dir':str(OUT),'input_files':dict(raw_week=len(raw_files['week']),raw_month=len(raw_files['month']),suspend_final=len(susp_files),reference=4),'input_bytes':sum(p.stat().st_size for p in all_files),'scope':'raw week/month only; lifecycle L and D separate; no source requests or lake writes'}
with connect_configured_duckdb(settings) as con:
 con.execute('SET autoinstall_known_extensions=false');con.execute('SET autoload_known_extensions=false')
 def q(label,sql,params=None):
  t=time.monotonic();r=con.execute(sql,params or []);timings.append({'stage':label,'seconds':round(time.monotonic()-t,6)})
  queries.append('-- '+label+'\n'+sql+';\n')
  print(json.dumps({'stage':label,'seconds':timings[-1]['seconds'],'elapsed':round(time.monotonic()-start,3)}),flush=True)
  return r
 def rows(sql,params=None):
  r=con.execute(sql,params or []);cols=[x[0] for x in r.description];return [dict(zip(cols,row)) for row in r.fetchall()]
 def export(sql,name):q('export_'+name,'COPY ('+sql+') TO ? (FORMAT CSV, HEADER TRUE)',[str(OUT/name)])
 # Independent literal boundary witness: partial suspension still requires a bar;
 # whole eligible interval suspended does not; delisting date is exclusive.
 golden=q('literal_boundaries',"""
 WITH days AS (SELECT DATE '2026-10-12'+i::INTEGER d FROM range(5) t(i)),
 life(code,listed,delisted) AS (VALUES ('A',DATE '2026-10-12',NULL::DATE),('B',DATE '2026-10-12',NULL::DATE),('C',DATE '2026-10-15',NULL::DATE),('D',DATE '2026-10-12',DATE '2026-10-14'),('E',DATE '2026-10-15',NULL::DATE)),
 susp(code,d) AS (VALUES ('A',DATE '2026-10-14'),('A',DATE '2026-10-15'),('B',DATE '2026-10-12'),('B',DATE '2026-10-13'),('B',DATE '2026-10-14'),('B',DATE '2026-10-15'),('B',DATE '2026-10-16'),('E',DATE '2026-10-15'),('E',DATE '2026-10-16'))
 SELECT l.code,count(*) active_days,count(s.d) suspended_days,count(*)>count(s.d) bar_required
 FROM life l JOIN days ON days.d>=l.listed AND (l.delisted IS NULL OR days.d<l.delisted)
 LEFT JOIN susp s ON s.code=l.code AND s.d=days.d GROUP BY l.code ORDER BY l.code
 """).fetchall()
 assert golden==[('A',5,2,True),('B',5,5,False),('C',2,0,True),('D',2,0,True),('E',2,2,False)],golden
 summary['literal_boundaries_passed']=5
 q('lifecycle','CREATE TEMP TABLE life AS SELECT * FROM read_parquet(?)',[str(refs['lifecycle'])])
 q('identity','CREATE TEMP TABLE identities AS SELECT source_ts_code,latest_ts_code,valid_from,valid_to FROM read_parquet(?)',[str(refs['identity'])])
 assert con.execute('SELECT count(*)=count(DISTINCT source_ts_code) FROM identities').fetchone()[0]
 q('calendar','CREATE TEMP TABLE calendar_all AS SELECT * FROM read_parquet(?) WHERE exchange=\'SSE\'',[str(refs['calendar'])])
 asof=con.execute('SELECT max(trade_date) FROM calendar_all WHERE is_open AND trade_date<=?',[datetime.now(ZoneInfo('Asia/Shanghai')).date()]).fetchone()[0]
 summary['asof_trade_date']=str(asof)
 q('suspension_file_coverage','CREATE TEMP TABLE susp_file_dates AS SELECT unnest(?)::DATE trade_date',[[p.parent.name.split('=',1)[1] for p in susp_files]])
 q('open_calendar',"""CREATE TEMP TABLE cal AS SELECT c.trade_date,row_number() OVER(ORDER BY c.trade_date)::INTEGER ord,
 sum(CASE WHEN s.trade_date IS NULL THEN 1 ELSE 0 END) OVER(ORDER BY c.trade_date)::INTEGER unknown_prefix
 FROM calendar_all c LEFT JOIN susp_file_dates s USING(trade_date) WHERE c.is_open AND c.trade_date<=?""",[asof])
 summary['calendar']=rows('SELECT min(trade_date) first_day,max(trade_date) last_day,count(*) trading_days FROM cal')[0]
 summary['lifecycle']=rows('SELECT list_status,count(*) stocks,min(list_date) earliest_listing,max(list_date) latest_listing FROM life GROUP BY list_status ORDER BY list_status')
 assert con.execute('SELECT count(*) FROM life WHERE list_date IS NULL OR (list_status=\'D\' AND delist_date IS NULL)').fetchone()[0]==0
 q('lifecycle_trading_bounds',"""CREATE TEMP TABLE life_bounds AS
 SELECT l.*,n.ord first_ord,p.ord last_ord
 FROM life l ASOF LEFT JOIN cal n ON l.list_date<=n.trade_date
 ASOF LEFT JOIN cal p ON least(coalesce(l.delist_date-1,?::DATE),?::DATE)>=p.trade_date""",[asof,asof])
 q('raw_projection_once',"""CREATE TEMP TABLE raw AS
 SELECT 'week' freq,ts_code,strptime(trade_date,'%Y%m%d')::DATE bar_date,try_strptime(end_date,'%Y%m%d')::DATE source_asof FROM read_parquet(?,hive_partitioning=false)
 UNION ALL
 SELECT 'month',ts_code,strptime(trade_date,'%Y%m%d')::DATE,try_strptime(end_date,'%Y%m%d')::DATE FROM read_parquet(?,hive_partitioning=false)""",[[str(p) for p in raw_files['week']],[str(p) for p in raw_files['month']]])
 summary['history_ranges']=rows('SELECT freq,count(*) raw_rows,count(DISTINCT ts_code) stocks,min(bar_date) first_bar_date,max(bar_date) last_bar_date,min(source_asof) min_source_end_date,max(source_asof) max_source_end_date FROM raw GROUP BY freq ORDER BY freq')
 q('raw_stock_period_keys',"""CREATE TEMP TABLE actual AS
 SELECT r.freq,coalesce(i.latest_ts_code,r.ts_code) ts_code, date_trunc(r.freq,r.bar_date)::DATE period_start,
 min(r.bar_date) first_source_label,max(r.bar_date) last_source_label,count(*) raw_rows
 FROM raw r LEFT JOIN identities i ON r.ts_code=i.source_ts_code GROUP BY 1,2,3""")
 summary['multiple_source_labels']=rows('SELECT freq,count(*) stock_periods_with_multiple_source_rows,sum(raw_rows-1) additional_rows FROM actual WHERE raw_rows>1 GROUP BY freq ORDER BY freq')
 q('market_periods',"""CREATE TEMP TABLE periods AS
 WITH p AS (SELECT f.freq,date_trunc(f.freq,c.trade_date)::DATE period_start,min(c.ord) first_ord,max(c.ord) last_ord,min(c.trade_date) first_trade_day,max(c.trade_date) last_trade_day
 FROM cal c CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2)
 SELECT *,CASE WHEN freq='week' THEN period_start+4 ELSE (period_start+INTERVAL '1 month'-INTERVAL '1 day')::DATE END period_label,
 row_number() OVER(PARTITION BY freq ORDER BY period_start)::INTEGER period_seq FROM p""")
 q('period_coverage_bounds',"""CREATE TEMP TABLE limits AS SELECT freq,min(period_start) first_period,max(period_start) last_period FROM actual GROUP BY freq""")
 q('suspension_projection_once',"""CREATE TEMP TABLE susp_all AS SELECT ts_code,trade_date,suspend_type,suspend_timing FROM read_parquet(?,hive_partitioning=false)""",[[str(p) for p in susp_files]])
 q('confirmed_reference','CREATE TEMP TABLE confirmed AS SELECT * FROM read_parquet(?)',[str(refs['confirmed'])])
 summary['suspension_reference']=rows('SELECT count(*) row_count,count(DISTINCT ts_code) stocks,min(trade_date) first_day,max(trade_date) last_day FROM susp_all')[0]
 summary['confirmed_reference']=rows('SELECT count(*) row_count,count(DISTINCT ts_code) stocks,min(trade_date) first_day,max(trade_date) last_day FROM confirmed')[0]
 q('full_day_suspensions',"""CREATE TEMP TABLE full_susp AS SELECT DISTINCT s.ts_code,s.trade_date FROM susp_all s WHERE s.suspend_type='S' AND (s.suspend_timing IS NULL OR trim(s.suspend_timing)='')""")
 summary['confirmed_absent_from_final']=con.execute('SELECT count(*) FROM confirmed c ANTI JOIN full_susp s USING(ts_code,trade_date)').fetchone()[0]
 summary['reference_dates_missing_since_start']=con.execute('SELECT count(*) FROM cal c ANTI JOIN susp_file_dates f USING(trade_date) WHERE c.trade_date>=(SELECT min(trade_date) FROM susp_file_dates)').fetchone()[0]
 q('suspended_stock_period_counts',"""CREATE TEMP TABLE susp_period AS
 SELECT f.freq,coalesce(i.latest_ts_code,s.ts_code) ts_code,date_trunc(f.freq,s.trade_date)::DATE period_start,count(DISTINCT s.trade_date)::INTEGER suspended_days
 FROM full_susp s LEFT JOIN identities i ON i.source_ts_code=s.ts_code
 JOIN life_bounds l ON l.ts_code=coalesce(i.latest_ts_code,s.ts_code)
 JOIN cal c ON c.trade_date=s.trade_date AND c.ord BETWEEN l.first_ord AND l.last_ord
 CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2,3""")
 q('stock_period_expectations',"""CREATE TEMP TABLE expected AS
 SELECT p.freq,l.ts_code,p.period_start,p.period_label,p.period_seq,l.list_status,
 greatest(l.first_ord,p.first_ord)::INTEGER first_ord,least(l.last_ord,p.last_ord)::INTEGER last_ord,
 (least(l.last_ord,p.last_ord)-greatest(l.first_ord,p.first_ord)+1)::INTEGER eligible_days,
 coalesce(s.suspended_days,0)::INTEGER suspended_days
 FROM life_bounds l JOIN periods p ON l.first_ord<=p.last_ord AND l.last_ord>=p.first_ord
 JOIN limits b ON b.freq=p.freq AND p.period_start BETWEEN b.first_period AND b.last_period
 LEFT JOIN susp_period s ON s.freq=p.freq AND s.ts_code=l.ts_code AND s.period_start=p.period_start""")
 assert con.execute('SELECT count(*) FROM expected WHERE suspended_days>eligible_days').fetchone()[0]==0
 q('missing_periods',"""CREATE TEMP TABLE missing AS
 WITH absent AS (SELECT e.* FROM expected e ANTI JOIN actual a USING(freq,ts_code,period_start)
 WHERE e.eligible_days>e.suspended_days),
 classified AS (SELECT e.*,c.unknown_prefix-coalesce(p.unknown_prefix,0) unknown_reference_days
 FROM absent e JOIN cal c ON c.ord=e.last_ord LEFT JOIN cal p ON p.ord=e.first_ord-1)
 SELECT *,CASE WHEN list_status='D' THEN 'delisted_history_excluded_by_policy'
 WHEN eligible_days-suspended_days-unknown_reference_days=0 THEN 'suspension_reference_incomplete'
 ELSE 'missing_despite_available_suspension_reference' END classification FROM classified""")
 q('missing_range_islands',"""CREATE TEMP TABLE missing_ranges AS
 WITH numbered AS (SELECT *,period_seq-row_number() OVER(PARTITION BY freq,ts_code,classification ORDER BY period_seq) island FROM missing),
 ranges AS (SELECT freq,ts_code,classification,island,min(period_label) missing_from,max(period_label) missing_to,count(*) missing_period_count,
 sum(eligible_days) eligible_trading_days,sum(suspended_days) full_day_suspension_days,sum(unknown_reference_days) suspension_reference_unknown_days,
 min(period_start) first_period_start,max(period_start) last_period_start
 FROM numbered GROUP BY freq,ts_code,classification,island),
 available AS (SELECT freq,ts_code,min(first_source_label) first_existing_label,max(last_source_label) last_existing_label,count(*) existing_periods FROM actual GROUP BY freq,ts_code)
 SELECT r.freq frequency,r.ts_code,l.name stock_name,l.exchange,l.list_status,l.list_date,l.delist_date,
 r.missing_from,r.missing_to,r.missing_period_count,r.eligible_trading_days,r.full_day_suspension_days,r.suspension_reference_unknown_days,r.classification,
 a.first_existing_label,a.last_existing_label,coalesce(a.existing_periods,0) existing_periods,
 r.first_period_start,r.last_period_start
 FROM ranges r JOIN life l USING(ts_code) LEFT JOIN available a ON a.ts_code=r.ts_code AND a.freq=r.freq""")
 summary['missing']=rows('SELECT freq,list_status,classification,count(*) missing_periods,count(DISTINCT ts_code) stocks,sum(eligible_days) eligible_days,sum(suspended_days) suspended_days,count(*) FILTER(WHERE suspended_days>0) partly_suspended_missing_periods FROM missing GROUP BY ALL ORDER BY freq,list_status,classification')
 summary['expected']=rows("""SELECT e.freq,e.list_status,count(*) lifecycle_periods,
 count(*) FILTER(WHERE e.eligible_days>e.suspended_days) required_periods,
 count(*) FILTER(WHERE e.eligible_days=e.suspended_days) entirely_suspended_periods,
 count(*) FILTER(WHERE e.eligible_days=e.suspended_days AND a.ts_code IS NULL) suspension_explains_absence,
 count(*) FILTER(WHERE e.eligible_days>e.suspended_days AND a.ts_code IS NOT NULL) observed_required_periods
 FROM expected e LEFT JOIN actual a USING(freq,ts_code,period_start) GROUP BY e.freq,e.list_status ORDER BY e.freq,e.list_status""")
 summary['range_counts']=rows('SELECT frequency,list_status,classification,count(*) ranges,count(DISTINCT ts_code) stocks FROM missing_ranges GROUP BY ALL ORDER BY ALL')
 summary['partial_suspension_missing_samples']=rows("SELECT m.freq,m.ts_code,l.name,m.period_label,m.eligible_days,m.suspended_days,m.classification FROM missing m JOIN life l USING(ts_code) WHERE m.list_status='L' AND m.suspended_days>0 ORDER BY m.classification,m.period_start DESC LIMIT 10")
 q('observed_lifecycle_boundaries',"""CREATE TEMP TABLE observed_boundaries AS
 SELECT a.*,l.list_status,l.name stock_name,l.exchange,l.list_date,l.delist_date,
 CASE WHEN l.ts_code IS NULL THEN 'identity_or_lifecycle_missing'
 WHEN p.freq IS NULL THEN 'no_open_market_period'
 WHEN p.last_ord<l.first_ord THEN 'before_listing_period'
 WHEN l.delist_date IS NOT NULL AND p.first_ord>l.last_ord THEN 'after_delisting_period'
 ELSE 'lifecycle_period' END classification
 FROM actual a LEFT JOIN life_bounds l USING(ts_code) LEFT JOIN periods p USING(freq,period_start)""")
 summary['observed_boundaries']=rows('SELECT freq,list_status,classification,count(DISTINCT ts_code) stocks,count(*) stock_periods,sum(raw_rows) raw_rows FROM observed_boundaries GROUP BY ALL ORDER BY ALL')
 summary['delisted']=rows("""SELECT l.list_status,count(*) stocks,
 count(*) FILTER(WHERE w.ts_code IS NOT NULL) stocks_with_week_rows,
 count(*) FILTER(WHERE m.ts_code IS NOT NULL) stocks_with_month_rows
 FROM life l LEFT JOIN (SELECT DISTINCT ts_code FROM actual WHERE freq='week') w USING(ts_code)
 LEFT JOIN (SELECT DISTINCT ts_code FROM actual WHERE freq='month') m USING(ts_code)
 GROUP BY l.list_status ORDER BY l.list_status""")
 summary['missing_listed_samples']=rows("SELECT * FROM missing_ranges WHERE list_status='L' ORDER BY classification,missing_period_count DESC,frequency,ts_code LIMIT 16")
 export('SELECT * FROM missing_ranges ORDER BY list_status,classification,frequency,ts_code,missing_from','missing_ranges.csv')
 export("SELECT * FROM missing_ranges WHERE list_status='L' ORDER BY classification,frequency,ts_code,missing_from",'listed_missing_ranges.csv')
 export("SELECT freq frequency,ts_code,stock_name,exchange,list_status,list_date,delist_date,classification,min(first_source_label) first_label,max(last_source_label) last_label,count(*) stock_periods,sum(raw_rows) raw_rows FROM observed_boundaries WHERE classification<>'lifecycle_period' GROUP BY ALL ORDER BY classification,freq,ts_code",'extra_lifecycle_rows.csv')
 # Exact period detail remains available for review without re-reading any lake file.
 export("SELECT m.freq frequency,m.ts_code,l.name stock_name,m.list_status,m.period_label,m.eligible_days,m.suspended_days,m.unknown_reference_days,m.classification FROM missing m JOIN life l USING(ts_code) WHERE m.list_status='L' ORDER BY classification,frequency,ts_code,period_label",'listed_missing_periods.csv')
 summary['query_timings']=timings
 summary['sql_wall_seconds']=round(sum(x['seconds'] for x in timings),3)
 summary['duckdb_version']=con.execute('SELECT version()').fetchone()[0]
 summary['duckdb_settings']={'memory_limit':'3GiB','threads':2,'temp_directory':str(WORK/'spill')}
 summary['period_counts']=rows('SELECT freq,count(*) trading_periods,min(first_trade_day) first_day,max(last_trade_day) last_day FROM periods GROUP BY freq ORDER BY freq')
changed=[f for f,v in before.items() if not Path(f).exists() or version(Path(f))!=v]
summary['input_versions_unchanged']=not changed;summary['changed_inputs']=changed
summary['elapsed_seconds']=round(time.monotonic()-start,3);summary['process_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
summary['output_files']={p.name:p.stat().st_size for p in OUT.glob('*.csv')}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str))
(OUT/'audit.sql').write_text('\n'.join(queries))
(WORK/'output_path.txt').write_text(str(OUT))
assert not changed,changed[:3]
print(json.dumps(summary,ensure_ascii=False,default=str),flush=True)
