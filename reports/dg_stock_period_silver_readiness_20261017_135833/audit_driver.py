"""One read-only audit under shared LLD section 9; no production writes."""
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json
import resource
import shutil
import time

from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings, connect_configured_duckdb

ROOT = Path('/Volumes/datasource/data_lake')
ASOF = date(2026, 10, 16)
LOWER = date(2014, 1, 1)
WORK = Path('/private/tmp/dg_period_approved_audit_' + str(time.time_ns()))
WORK.mkdir()
OUT = Path('/Users/congming/github/goldenshare/reports') / ('dg_stock_period_silver_readiness_' + datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S'))
OUT.mkdir()
prior = json.loads(Path('/private/tmp/dg_period_completeness_mjfo40k9/probe.json').read_text())
refs = {k: prior['paths'][k] for k in ('lifecycle', 'identity', 'calendar')}
files = {}
for f in ('week', 'month'):
    all_paths = sorted((ROOT / f'raw/tushare/stk_period_bar_adj_{f}').glob('*/*.parquet'))
    lo, hi = ('2014-01-03', '2026-10-16') if f == 'week' else ('2014-01', '2026-10')
    files[f] = [str(p) for p in all_paths if lo <= p.parent.name.split('=', 1)[1] <= hi]
susp = [str(p) for p in sorted((ROOT / 'silver/quote/stock_suspend_daily').glob('*/*.parquet')) if '2014-01-01' <= p.parent.name.split('=', 1)[1] <= ASOF.isoformat()]
summary = {'scope': 'shared LLD section 9; listed stocks; complete periods; no Silver generation', 'observed_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'asof': str(ASOF), 'lower': str(LOWER), 'document_commit': '585b0a041', 'report_dir': str(OUT), 'work_dir': str(WORK), 'references': refs, 'input_file_counts': {**{k: len(v) for k, v in files.items()}, 'suspension': len(susp)}, 'frequencies': {}, 'timings': []}
(OUT / 'inputs.json').write_text(json.dumps({'references': refs, 'raw_files': files, 'suspension_files': susp}, ensure_ascii=False, indent=2))
sql_log = []
t0 = time.monotonic()
settings = DuckDBConnectionSettings(temp_directory=WORK / 'spill', memory_limit='3GiB', threads=2, max_temp_directory_size='8GiB')
numeric = ['open','high','low','close','pre_close','open_qfq','high_qfq','low_qfq','close_qfq','open_hfq','high_hfq','low_hfq','close_hfq','vol','amount','change','pct_chg']

with connect_configured_duckdb(settings) as con:
    con.execute('SET autoinstall_known_extensions=false')
    con.execute('SET autoload_known_extensions=false')
    def q(label, sql, params=None):
        start = time.monotonic()
        r = con.execute(sql, params or [])
        summary['timings'].append({'stage': label, 'seconds': round(time.monotonic() - start, 6)})
        sql_log.append('-- ' + label + '\n' + sql + ';\n')
        (OUT / 'audit.sql').write_text('\n'.join(sql_log))
        print(json.dumps({'stage': label, 'elapsed': round(time.monotonic() - t0, 3)}, ensure_ascii=False), flush=True)
        return r
    def rows(sql, params=None):
        r = con.execute(sql, params or [])
        return [dict(zip([x[0] for x in r.description], row)) for row in r.fetchall()]
    def export(label, sql, name):
        q(label, 'COPY (' + sql + ') TO ? (FORMAT CSV, HEADER TRUE)', [str(OUT / name)])
    def save_summary():
        (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    q('lifecycle_once', 'CREATE TEMP TABLE life AS SELECT ts_code,name,exchange,list_status,list_date,delist_date,is_cny_stock FROM read_parquet(?)', [refs['lifecycle']])
    q('listed_scope', "CREATE TEMP TABLE listed AS SELECT * FROM life WHERE list_status='L' AND is_cny_stock")
    q('identity_once', 'CREATE TEMP TABLE identities AS SELECT source_ts_code,latest_ts_code,confidence FROM read_parquet(?)', [refs['identity']])
    q('calendar_once', 'CREATE TEMP TABLE cal AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)::INTEGER ord FROM read_parquet(?) WHERE exchange=\'SSE\' AND is_open AND trade_date BETWEEN ? AND ?', [refs['calendar'], LOWER, ASOF])
    summary['listed_stocks'] = con.execute('SELECT count(*) FROM listed').fetchone()[0]
    summary['calendar'] = rows('SELECT min(trade_date) first_day,max(trade_date) last_day,count(*) trading_days FROM cal')[0]
    summary['reference_issues'] = {
        'duplicate_lifecycle_codes': con.execute('SELECT count(*)-count(DISTINCT ts_code) FROM life').fetchone()[0],
        'duplicate_identity_sources': con.execute('SELECT count(*)-count(DISTINCT source_ts_code) FROM identities').fetchone()[0],
        'listed_missing_date': con.execute('SELECT count(*) FROM listed WHERE list_date IS NULL').fetchone()[0],
        'missing_suspension_dates': con.execute('SELECT count(*) FROM cal WHERE trade_date NOT IN (SELECT unnest(?)::DATE)', [[Path(p).parent.name.split('=',1)[1] for p in susp]]).fetchone()[0],
    }
    if any(summary['reference_issues'].values()):
        summary['status'] = 'blocked_reference_contract'
        save_summary()
        raise RuntimeError(summary['reference_issues'])
    q('lifecycle_bounds', '''CREATE TEMP TABLE bounds AS SELECT l.*,n.ord first_ord,p.ord last_ord
        FROM listed l ASOF LEFT JOIN cal n ON greatest(l.list_date,?::DATE)<=n.trade_date
        ASOF LEFT JOIN cal p ON least(coalesce(l.delist_date-1,?::DATE),?::DATE)>=p.trade_date''', [LOWER, ASOF, ASOF])
    q('periods', '''CREATE TEMP TABLE periods AS
        WITH p AS (SELECT f.freq,date_trunc(f.freq,c.trade_date)::DATE period_start,min(c.ord) first_ord,max(c.ord) last_ord
            FROM cal c CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2)
        SELECT *,CASE WHEN freq='week' THEN period_start+4 ELSE last_day(period_start) END period_label,
        row_number() OVER(PARTITION BY freq ORDER BY period_start)::INTEGER period_seq FROM p''')
    q('suspension_once', '''CREATE TEMP TABLE susp_all AS
        SELECT s.ts_code source_code,i.latest_ts_code ts_code,s.trade_date,s.suspend_type,s.suspend_timing
        FROM read_parquet(?,hive_partitioning=false) s LEFT JOIN identities i ON s.ts_code=i.source_ts_code''', [susp])
    summary['suspension_rows'] = con.execute('SELECT count(*) FROM susp_all').fetchone()[0]
    q('full_day_suspensions', "CREATE TEMP TABLE full_susp AS SELECT DISTINCT ts_code,trade_date FROM susp_all WHERE suspend_type='S' AND suspend_timing IS NULL")
    q('suspension_periods', '''CREATE TEMP TABLE susp_period AS
        SELECT f.freq,s.ts_code,date_trunc(f.freq,s.trade_date)::DATE period_start,count(DISTINCT s.trade_date)::INTEGER suspended_days
        FROM full_susp s JOIN bounds b USING(ts_code) JOIN cal c ON c.trade_date=s.trade_date AND c.ord BETWEEN b.first_ord AND b.last_ord
        CROSS JOIN (VALUES ('week'),('month')) f(freq) GROUP BY 1,2,3''')
    q('expected_stock_periods', '''CREATE TEMP TABLE expected AS
        SELECT p.freq,b.ts_code,p.period_start,p.period_label,p.period_seq,
        (least(b.last_ord,p.last_ord)-greatest(b.first_ord,p.first_ord)+1)::INTEGER eligible_days,
        coalesce(s.suspended_days,0)::INTEGER suspended_days
        FROM bounds b JOIN periods p ON b.first_ord<=p.last_ord AND b.last_ord>=p.first_ord
        LEFT JOIN susp_period s ON s.freq=p.freq AND s.ts_code=b.ts_code AND s.period_start=p.period_start''')
    assert con.execute('SELECT count(*) FROM expected WHERE suspended_days>eligible_days OR eligible_days<=0').fetchone()[0] == 0
    all_stats = []
    for freq in ('week', 'month'):
        stat = {}
        columns = ','.join('r."'+x+'"' for x in ['ts_code','trade_date','end_date','freq',*numeric])
        q(freq+'_raw_once', f'''CREATE TEMP TABLE raw AS SELECT {columns},r.filename,
            i.latest_ts_code canonical_code,i.confidence,
            try_strptime(r.trade_date,'%Y%m%d')::DATE bar_date,try_strptime(r.end_date,'%Y%m%d')::DATE source_asof,
            date_trunc('{freq}',try_strptime(r.trade_date,'%Y%m%d'))::DATE period_start
            FROM read_parquet(?,hive_partitioning=false,filename=true) r LEFT JOIN identities i ON r.ts_code=i.source_ts_code''', [files[freq]])
        q(freq+'_scope', f'''CREATE TEMP VIEW scoped AS SELECT r.*,l.list_status,l.list_date,l.delist_date,
            CASE WHEN r.canonical_code IS NULL OR r.confidence IS DISTINCT FROM 'confirmed' THEN 'identity_unresolved'
              WHEN l.ts_code IS NULL THEN 'lifecycle_unresolved'
              WHEN l.list_status<>'L' OR NOT l.is_cny_stock THEN 'outside_listed_scope'
              WHEN r.bar_date IS NULL OR r.source_asof IS NULL OR r.freq<>'{freq}' THEN 'invalid_date_or_frequency'
              WHEN r.period_start<date_trunc('{freq}',DATE '2014-01-01') THEN 'before_2014_period'
              WHEN r.period_start<date_trunc('{freq}',l.list_date) THEN 'before_listing_period'
              WHEN l.delist_date IS NOT NULL AND r.period_start>date_trunc('{freq}',l.delist_date-1) THEN 'after_delisting_period'
              WHEN r.period_start>date_trunc('{freq}',DATE '2026-10-16') THEN 'future_period'
              ELSE 'eligible' END classification
            FROM raw r LEFT JOIN life l ON l.ts_code=r.canonical_code''')
        stat['input'] = rows('SELECT count(*) raw_rows,count(DISTINCT ts_code) raw_stocks,min(bar_date) first_label,max(bar_date) last_label,min(source_asof) oldest_end_date,max(source_asof) newest_end_date FROM raw')[0]
        stat['scope_counts'] = rows('SELECT classification,count(*) raw_rows,count(DISTINCT canonical_code) stocks FROM scoped GROUP BY classification ORDER BY classification')
        export(freq+'_scope_issues', "SELECT ? frequency,ts_code source_code,canonical_code,trade_date,end_date,classification,filename FROM scoped WHERE classification NOT IN ('eligible','before_2014_period','before_listing_period','outside_listed_scope')".replace('? frequency', "'"+freq+"' frequency"), freq+'_scope_issues.csv')
        q(freq+'_latest_keys', '''CREATE TEMP TABLE latest_keys AS SELECT canonical_code ts_code,period_start,max(source_asof) source_asof,count(*) raw_rows
            FROM scoped WHERE classification='eligible' GROUP BY 1,2''')
        q(freq+'_latest_counts', '''CREATE TEMP TABLE latest_counts AS SELECT k.ts_code,k.period_start,k.source_asof,k.raw_rows,count(*) latest_rows,
            min(r.bar_date) first_latest_label,max(r.bar_date) last_latest_label
            FROM latest_keys k JOIN scoped r ON r.canonical_code=k.ts_code AND r.period_start=k.period_start AND r.source_asof=k.source_asof
            WHERE r.classification='eligible' GROUP BY 1,2,3,4''')
        values = ','.join('r."'+x+'"' for x in numeric)
        q(freq+'_only_tied_latest_values', f'''CREATE TEMP TABLE tie_variants AS
            SELECT c.ts_code,c.period_start,count(DISTINCT ({values})) variants
            FROM latest_counts c JOIN scoped r ON r.canonical_code=c.ts_code AND r.period_start=c.period_start AND r.source_asof=c.source_asof
            WHERE c.latest_rows>1 AND r.classification='eligible' GROUP BY 1,2''')
        q(freq+'_actual_valid_periods', '''CREATE TEMP TABLE actual AS SELECT c.* FROM latest_counts c LEFT JOIN tie_variants t USING(ts_code,period_start) WHERE coalesce(t.variants,1)=1''')
        payload = ','.join(x+' := r."'+x+'"' for x in numeric)
        export(freq+'_latest_conflicts', f'''SELECT '{freq}' frequency,r.canonical_code ts_code,l.name stock_name,r.period_start,r.trade_date,r.end_date,
            to_json(struct_pack({payload})) business_values,r.filename source_file
            FROM scoped r JOIN tie_variants t ON r.canonical_code=t.ts_code AND r.period_start=t.period_start
            JOIN latest_keys k ON k.ts_code=t.ts_code AND k.period_start=t.period_start AND k.source_asof=r.source_asof
            JOIN listed l ON l.ts_code=r.canonical_code WHERE t.variants>1 AND r.classification='eligible'
            ORDER BY ts_code,period_start,r.trade_date''', freq+'_latest_version_conflicts.csv')
        stat['versions'] = rows('''SELECT count(*) eligible_stock_periods,sum(raw_rows) eligible_raw_rows,
            sum(raw_rows-latest_rows) old_version_rows,sum(latest_rows-1) tied_additional_rows,
            count(*) FILTER(WHERE raw_rows>1) multirow_periods FROM latest_counts''')[0]
        stat['version_conflict_periods'] = con.execute('SELECT count(*) FROM tie_variants WHERE variants>1').fetchone()[0]
        q(freq+'_missing', f'''CREATE TEMP TABLE missing AS SELECT e.*,
            CASE WHEN k.ts_code IS NOT NULL THEN 'latest_version_conflict' ELSE 'missing_required_period' END reason
            FROM expected e ANTI JOIN actual a USING(ts_code,period_start)
            LEFT JOIN latest_keys k USING(ts_code,period_start)
            WHERE e.freq='{freq}' AND e.eligible_days>e.suspended_days''')
        q(freq+'_missing_ranges', '''CREATE TEMP TABLE missing_ranges AS
            WITH n AS (SELECT *,period_seq-row_number() OVER(PARTITION BY ts_code,reason ORDER BY period_seq) island FROM missing),
            g AS (SELECT ts_code,reason,island,min(period_label) missing_from,max(period_label) missing_to,count(*) missing_period_count,
                sum(eligible_days) eligible_trading_days,sum(suspended_days) full_day_suspension_days FROM n GROUP BY 1,2,3)
            SELECT g.*,l.name stock_name,l.exchange,l.list_status,l.list_date,l.delist_date FROM g JOIN listed l USING(ts_code)''')
        export(freq+'_missing_range_csv', f"SELECT '{freq}' frequency,ts_code,stock_name,exchange,list_status,list_date,delist_date,missing_from,missing_to,missing_period_count,eligible_trading_days,full_day_suspension_days,reason FROM missing_ranges ORDER BY ts_code,missing_from", freq+'_missing_ranges.csv')
        export(freq+'_missing_period_csv', f"SELECT '{freq}' frequency,m.ts_code,l.name stock_name,l.exchange,l.list_date,l.delist_date,m.period_label,m.eligible_days,m.suspended_days,m.reason FROM missing m JOIN listed l USING(ts_code) ORDER BY m.ts_code,m.period_label", freq+'_missing_periods.csv')
        stat['completeness'] = rows(f'''SELECT count(*) lifecycle_periods,
            count(*) FILTER(WHERE e.eligible_days>e.suspended_days) required_periods,
            count(*) FILTER(WHERE a.ts_code IS NOT NULL) observed_valid_periods,
            count(*) FILTER(WHERE e.eligible_days>e.suspended_days AND a.ts_code IS NOT NULL) observed_required_periods,
            count(*) FILTER(WHERE e.eligible_days=e.suspended_days AND a.ts_code IS NULL) full_suspension_absence,
            count(*) FILTER(WHERE e.eligible_days=e.suspended_days AND a.ts_code IS NOT NULL) full_suspension_with_bar
            FROM expected e LEFT JOIN actual a USING(ts_code,period_start) WHERE e.freq='{freq}' ''')[0]
        stat['missing'] = rows('SELECT reason,count(*) missing_periods,count(DISTINCT ts_code) stocks FROM missing GROUP BY reason')
        stat['missing_range_count'] = con.execute('SELECT count(*) FROM missing_ranges').fetchone()[0]
        stat['selected'] = rows('SELECT count(*) stock_periods,count(DISTINCT ts_code) stocks,min(first_latest_label) first_source_label,max(last_latest_label) last_source_label FROM actual')[0]
        stat['boundaries'] = rows(f'''SELECT
            count(*) FILTER(WHERE a.period_start=date_trunc('{freq}',DATE '2014-01-01')) first_2014_periods,
            count(*) FILTER(WHERE a.period_start=date_trunc('{freq}',l.list_date)) listing_periods,
            count(*) FILTER(WHERE a.period_start=date_trunc('{freq}',DATE '2026-10-16')) current_periods
            FROM actual a JOIN listed l USING(ts_code)''')[0]
        export(freq+'_suspension_contradictions', f'''SELECT '{freq}' frequency,e.ts_code,l.name stock_name,e.period_label,e.eligible_days,e.suspended_days,
            a.first_latest_label,a.last_latest_label FROM expected e JOIN actual a USING(ts_code,period_start) JOIN listed l USING(ts_code)
            WHERE e.freq='{freq}' AND e.eligible_days=e.suspended_days AND e.period_start>=greatest(l.list_date,DATE '2014-01-01') ORDER BY e.ts_code,e.period_label''', freq+'_suspension_contradictions.csv')
        stat['suspension_contradictions'] = con.execute(f'''SELECT count(*) FROM expected e JOIN actual a USING(ts_code,period_start) JOIN listed l USING(ts_code)
            WHERE e.freq='{freq}' AND e.eligible_days=e.suspended_days AND e.period_start>=greatest(l.list_date,DATE '2014-01-01')''').fetchone()[0]
        stat['selected_outside_expected'] = con.execute(f"SELECT count(*) FROM actual a ANTI JOIN (SELECT * FROM expected WHERE freq='{freq}') e USING(ts_code,period_start)").fetchone()[0]
        stat['blocking_scope_rows'] = sum(x['raw_rows'] for x in stat['scope_counts'] if x['classification'] not in ('eligible','before_2014_period','before_listing_period','outside_listed_scope'))
        stat['status'] = 'passed' if not (stat['missing'] or stat['version_conflict_periods'] or stat['suspension_contradictions'] or stat['blocking_scope_rows']) else 'not_passed'
        summary['frequencies'][freq] = stat
        save_summary()
        print(json.dumps({'frequency': freq, 'result': stat}, ensure_ascii=False, default=str), flush=True)
        for name in ('missing_ranges','missing','actual','tie_variants','latest_counts','latest_keys'):
            con.execute('DROP TABLE ' + name)
        con.execute('DROP VIEW scoped')
        con.execute('DROP TABLE raw')
    summary['duckdb_version'] = con.execute('SELECT version()').fetchone()[0]
summary['status'] = 'passed' if all(x['status']=='passed' for x in summary['frequencies'].values()) else 'not_passed'
summary['elapsed_seconds'] = round(time.monotonic()-t0, 3)
summary['sql_seconds'] = round(sum(x['seconds'] for x in summary['timings']), 3)
summary['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
summary['source_requests'] = 0
summary['formal_writes'] = 0
summary['settings'] = {'memory_limit': '3GiB', 'threads': 2, 'max_temp_directory_size': '8GiB', 'temp_directory': str(WORK/'spill'), 'basis': 'reuse prior audit settings; no new production configuration'}
save_summary()
shutil.copyfile(__file__, OUT/'audit_driver.py')
(WORK/'output_path.txt').write_text(str(OUT))
print(json.dumps({'finished': summary['status'], 'output': str(OUT), 'seconds': summary['elapsed_seconds'], 'peak_rss_bytes': summary['peak_rss_bytes']},ensure_ascii=False), flush=True)
