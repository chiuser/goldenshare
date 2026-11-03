"""SQL is fixed and projected; use the existing approved psql entry point."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import signal
import subprocess
import time
from .spec import SPEC, FIELDS, IDENTITY, TABLES
from .storage import ROOT, Cancelled, BudgetExceeded, atomic_json

@dataclass(frozen=True)
class Query:
    name: str
    select: str
    limit: int
    fingerprint: str
    codes: tuple = ()
    dates: tuple = ()
    industrial_only: bool = True


def literals(values, pattern, max_count=SPEC.max_codes):
    values=tuple(values)
    if max_count not in (SPEC.max_codes,500,2000):raise ValueError('Unapproved identifier bound')
    if not values or len(values)>max_count:raise ValueError('Invalid bounded identifier set')
    if any(not re.fullmatch(pattern,str(v)) for v in values):raise ValueError('Invalid SQL identifier value')
    return ','.join("'"+v+"'" for v in values)


def codes_sql(codes,max_count=SPEC.max_codes):return literals(codes,r'\d{6}\.(?:SZ|SH|BJ)',max_count)

def wrap(select):
    # Only generated SELECT/WITH is accepted; multiple statements and SQL comments are forbidden.
    if not select.lstrip().startswith(('SELECT ','WITH ')) or ';' in select or '--' in select or '/*' in select:
        raise ValueError('Not a single generated read query')
    if re.search(r'\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY|CALL|DO|INTO)\b',select,re.I):
        raise ValueError('Write SQL is forbidden')
    return ("BEGIN READ ONLY;\nSET LOCAL statement_timeout='30s'; SET LOCAL lock_timeout='3s'; SET LOCAL jit=off;\n"
            'SELECT row_to_json(projected) FROM ('+select+') projected;\nCOMMIT;\n')


def selection_query():
    roots=literals(SPEC.roots,r'BK\d{4}\.DC')
    excluded=codes_sql(SPEC.excluded)
    select=f"""WITH roots AS (SELECT sector_code FROM core_serving.wealth_sector_hierarchy
 WHERE sector_code IN ({roots}) AND industry_level=1 AND baseline_version='{SPEC.baseline}')
 SELECT candidate.* FROM roots r CROSS JOIN LATERAL (
 SELECT DISTINCT s.ts_code,s.name,s.fullname,s.curr_type,s.list_date,s.delist_date,s.list_status,
 s.fetched_at,r.sector_code AS selected_root
 FROM raw_tushare.stock_basic s JOIN core_serving.dc_member m ON m.con_code=s.ts_code
 JOIN core_serving.wealth_sector_hierarchy h ON h.sector_code=m.ts_code
 WHERE m.trade_date=DATE '{SPEC.snapshot}' AND h.root_sector_code=r.sector_code
 AND h.baseline_version='{SPEC.baseline}' AND s.ts_code !~ '^(200|900)'
 AND s.list_status IN ('L','P') AND s.list_date<=DATE '{SPEC.snapshot}'
 AND (s.delist_date IS NULL OR s.delist_date>DATE '{SPEC.snapshot}')
 AND s.ts_code NOT IN ({excluded}) ORDER BY s.ts_code LIMIT {SPEC.per_root}) candidate
 ORDER BY selected_root,ts_code"""
    fp=f"SELECT count(*) AS n,md5(string_agg(row_to_json(q)::text,'' ORDER BY selected_root,ts_code)) AS content FROM ({select}) q"
    return Query('sample',select,SPEC.max_codes,fp)


def mapping_query(codes,max_codes=SPEC.max_codes,row_limit=SPEC.max_member_rows):
    if row_limit not in (SPEC.max_member_rows,2000):raise ValueError('Unapproved membership bound')
    cs=codes_sql(codes,max_codes)
    select=f"""SELECT m.con_code,m.ts_code AS sector_code,m.trade_date,h.sector_name,h.industry_level,
 h.parent_sector_code,h.parent_sector_name,h.root_sector_code,h.root_sector_name,h.baseline_version
 FROM core_serving.dc_member m JOIN core_serving.wealth_sector_hierarchy h ON h.sector_code=m.ts_code
 WHERE m.trade_date=DATE '{SPEC.snapshot}' AND m.con_code IN ({cs}) AND h.baseline_version='{SPEC.baseline}'
 ORDER BY m.con_code,h.industry_level,m.ts_code LIMIT {row_limit+1}"""
    return Query('mapping',select,row_limit,
                 f"SELECT count(*) n,md5(string_agg(row_to_json(q)::text,'' ORDER BY con_code,sector_code)) content FROM ({select}) q",tuple(codes),(SPEC.snapshot,))


def financial_query(dataset,date,codes,max_codes=SPEC.max_codes,industrial_only=True):
    if dataset not in TABLES or dataset=='valuation' or date not in SPEC.dates:raise ValueError('Dataset/date outside trial')
    cs=codes_sql(codes,max_codes); table=TABLES[dataset]
    if dataset=='fina_indicator':
        cols=('ts_code','end_date','ann_date','update_flag','fetched_at','source_content_hash')+FIELDS[dataset]
        cols_sql=','.join(cols)
        base=f"SELECT {cols_sql} FROM {table} WHERE ts_code IN ({cs}) AND end_date=DATE '{date}'"
        select=f"SELECT DISTINCT ON (ts_code,end_date) {cols_sql} FROM ({base}) raw ORDER BY ts_code,end_date,CASE update_flag WHEN '1' THEN 0 ELSE 1 END,ann_date DESC NULLS LAST,fetched_at DESC NULLS LAST,source_content_hash DESC"
    else:
        cols=IDENTITY+FIELDS[dataset]
        select=f"SELECT {','.join(cols)} FROM {table} WHERE ts_code IN ({cs}) AND end_date=DATE '{date}' ORDER BY ts_code"
    fp=f"SELECT count(*) n,max(fetched_at) fetched_at FROM ({select}) q"
    return Query(dataset+'_'+date,select,len(codes),fp,tuple(codes),(date,),industrial_only)


def valuation_query(codes,max_codes=SPEC.max_codes):
    cs=codes_sql(codes,max_codes)
    select=f"SELECT ts_code,trade_date,{','.join(FIELDS['valuation'])},updated_at FROM {TABLES['valuation']} WHERE ts_code IN ({cs}) AND trade_date=DATE '{SPEC.snapshot}' ORDER BY ts_code"
    return Query('valuation',select,len(codes),f"SELECT count(*) n,max(updated_at) fetched_at FROM ({select}) q",tuple(codes),(SPEC.snapshot,))


def validate_rows(query,rows):
    if len(rows)>query.limit:raise ValueError('Row limit exceeded: '+query.name)
    for row in rows:
        if query.codes and row.get('ts_code',row.get('con_code')) not in query.codes:raise ValueError('Code outside frozen query')
        if query.dates and row.get('end_date',row.get('trade_date')) not in query.dates:raise ValueError('Date outside frozen query')
    if query.name=='sample':
        codes=[r['ts_code'] for r in rows]
        if len(set(codes))!=len(codes) or not rows:raise ValueError('Empty/conflicting selected roots')
        if set(codes)&set(SPEC.excluded):raise ValueError('Excluded code selected')
        for r in rows:
            if r['selected_root'] not in SPEC.roots:raise ValueError('Unexpected root')
            if r.get('curr_type')!='CNY':raise ValueError('Unexpected reporting currency')
        for root in SPEC.roots:
            if not 0<sum(r['selected_root']==root for r in rows)<=SPEC.per_root:raise ValueError('Root size')
    elif query.name.startswith('mapping'):return
    elif query.name=='tree':
        if len({r['sector_code'] for r in rows})!=len(rows):raise ValueError('Duplicate hierarchy node')
        if any(r['baseline_version']!=SPEC.baseline for r in rows):raise ValueError('Wrong hierarchy baseline')
        return
    else:
        keys=[(r['ts_code'],r.get('end_date',r.get('trade_date'))) for r in rows]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate canonical record')
        for r in rows:
            if r['ts_code'] in SPEC.excluded:raise ValueError('Excluded financial row')
            if 'end_date' in r and r['end_date'] not in SPEC.dates:raise ValueError('Wrong period')
            if 'report_type' in r and r['report_type']!='1':raise ValueError('Wrong consolidation')
            if query.industrial_only and 'comp_type' in r and r['comp_type']!='1':raise ValueError('Unexpected nonindustrial report in selected sectors')


def command_sql(store,name,select,max_rows):
    store.check(); started=time.monotonic()
    sql=store.path/'evidence'/f'{name}.sql';sql.write_text(wrap(select))
    part=store.path/'inputs'/f'{name}.jsonl.part'
    stderr=store.path/'evidence'/f'{name}.stderr.txt'
    with part.open('wb') as out,stderr.open('wb') as err:
        proc=subprocess.Popen(['bash','scripts/psql-remote.sh','-f',str(sql),'--','-A','-t','-q'],
                              cwd=ROOT,stdout=out,stderr=err,start_new_session=True)
        try:
            while proc.poll() is None:
                store.check()
                if time.monotonic()-started>SPEC.unit_seconds:raise BudgetExceeded('Unit time limit')
                if part.stat().st_size>SPEC.disk_bytes:raise BudgetExceeded('Unit file size')
                time.sleep(.05)
        except BaseException:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            raise
        finally:
            store.state['db_seconds']=float(store.state['db_seconds'])+time.monotonic()-started
            store.save()
    if proc.returncode:raise RuntimeError('Read-only database unit failed: '+name+'; see stderr artifact')
    rows=[]
    with part.open() as stream:
        for line in stream:
            rows.append(json.loads(line))
            if len(rows)>max_rows:raise ValueError('Unit result overflow')
    return part,rows


def fingerprint(store,query):
    part,rows=command_sql(store,'fp_'+query.name,query.fingerprint,1)
    if len(rows)!=1:raise ValueError('Fingerprint shape')
    part.unlink()
    return rows[0]


def run_unit(store,query):
    old=store.completed(query.name)
    if old:
        if fingerprint(store,query)!=old['fingerprint']:raise ValueError('Source changed during resume: '+query.name)
        return list(store.rows(query.name)),False
    fp=fingerprint(store,query)
    part,rows=command_sql(store,query.name,query.select,query.limit)
    validate_rows(query,rows)
    if len(rows)!=fp['n']:raise ValueError('Source changed during unit read')
    store.seal(query.name,part,len(rows),fp)
    return list(store.rows(query.name)),True


def resolve_mapping(samples,rows):
    result=[]
    for sample in samples:
        found=[r for r in rows if r['con_code']==sample['ts_code']]
        roots={r['sector_code'] if r['industry_level']==1 else r['root_sector_code'] for r in found}
        parents={r['sector_code'] for r in found if r['industry_level']==2}
        parents.update(r['parent_sector_code'] for r in found if r['industry_level']==3)
        if len(roots)!=1 or ('selected_root' in sample and roots!={sample['selected_root']}) or len(parents)!=1:raise ValueError('Conflicting/missing hierarchy: '+sample['ts_code'])
        parent=next(iter(parents));root=next(iter(roots))
        root_name=next(r['root_sector_name'] for r in found)
        parent_name=next((r['sector_name'] for r in found if r['sector_code']==parent),None)
        if parent_name is None:parent_name=next((r['parent_sector_name'] for r in found if r.get('parent_sector_code')==parent),parent)
        result.append(dict(sample,root=root,root_name=root_name,parent=parent,parent_name=parent_name))
    return result


def extract_trial(store,stop_after=None):
    processed=0;reused=0
    store.save(status='EXTRACTING',total_units=47)
    def unit(q):
        nonlocal processed,reused
        rows,fresh=run_unit(store,q)
        processed+=1;reused+=not fresh
        print(json.dumps({'stage':'extract','unit':q.name,'done':processed,'total':47,'percent':round(processed/47*100,1),'rows':len(rows),'reused':not fresh}),flush=True)
        if stop_after and processed>=stop_after:raise Cancelled('Planned stop for real resume acceptance')
        return rows
    samples=unit(selection_query()); codes=[r['ts_code'] for r in samples]
    mappings=unit(mapping_query(codes));mapped=resolve_mapping(samples,mappings)
    atomic_json(store.path/'calculations/sample.json',mapped)
    unit(valuation_query(codes))
    for dataset in ('income','balancesheet','cashflow','fina_indicator'):
        for date in SPEC.dates:unit(financial_query(dataset,date,codes))
    for dataset in ('income','balancesheet','cashflow','fina_indicator'):
        if sum(store.completed(dataset+'_'+d)['rows'] for d in SPEC.dates)>SPEC.max_codes*len(SPEC.dates):raise ValueError('Dataset row budget')
    queries=[selection_query(),mapping_query(codes),valuation_query(codes)]+[financial_query(k,d,codes) for k in ('income','balancesheet','cashflow','fina_indicator') for d in SPEC.dates]
    verify_source(store,queries)
    store.save(status='INPUTS_FROZEN',reused_units=reused,processed_units=processed)
    return mapped


def verify_source(store,queries):
    parts=["SELECT '"+q.name+"'::text name,row_to_json(f) fingerprint FROM ("+q.fingerprint+") f" for q in queries]
    part,rows=command_sql(store,'source_final',' UNION ALL '.join(parts),len(queries))
    actual={r['name']:r['fingerprint'] for r in rows}
    for query in queries:
        if actual.get(query.name)!=store.completed(query.name)['fingerprint']:
            raise ValueError('Source changed before freeze: '+query.name)
    os.replace(part,store.path/'evidence/source_final.jsonl')
    atomic_json(store.path/'evidence/source_check.json',{'units':len(queries),'all_fingerprints_equal':True,'limitation':'counts/latest timestamp are not atomic multi-table snapshots'})


def known_exceptions():
    pairs=set()
    for folder in ('a_share_industry_prosperity_2026q3_coverage_20261101','a_share_industry_prosperity_2026q3_coverage_20261101_recheck'):
        path=ROOT/'reports'/folder/'04_q4_and_versions.jsonl'
        for line in path.read_text().splitlines():
            record=json.loads(line)
            if record.get('section')=='deducted_q4_consistency':
                pairs.update((r['ts_code'],int(r['y'])) for r in record['conflict_samples'])
    units=[(f'exception_{code}_{year}',code,(f'{year}-09-30',f'{year}-12-31')) for code,year in sorted(pairs)]
    units += [('exception_920038_2024H1','920038.BJ',('2024-06-30',)),
              ('exception_920165_2024H1','920165.BJ',('2024-06-30',)),
              ('exception_920165_2024Q3','920165.BJ',('2024-09-30',))]
    if len(units)>26:raise ValueError('Exception scope exceeds plan')
    return units


def exception_query(name,code,dates):
    cs=codes_sql([code])
    if any(d not in SPEC.dates for d in dates):raise ValueError('Exception date')
    ds=','.join("DATE '"+d+"'" for d in dates)
    select=f"""SELECT ts_code,end_date,ann_date,update_flag,fetched_at,source_content_hash,profit_dedt,q_dtprofit,
 count(*) OVER() AS available_versions FROM raw_tushare.fina_indicator
 WHERE ts_code IN ({cs}) AND end_date IN ({ds})
 ORDER BY end_date,CASE update_flag WHEN '1' THEN 0 ELSE 1 END,ann_date DESC,fetched_at DESC,source_content_hash DESC LIMIT 10"""
    return Query(name,select,10,f"SELECT count(*) n,max(fetched_at) fetched_at FROM ({select}) q",(code,),tuple(dates))


def audit_exceptions(store):
    findings=[];row_count=0
    units=known_exceptions()
    for index,(name,code,dates) in enumerate(units,1):
        query=exception_query(name,code,dates)
        # Raw versions intentionally share code/report period; canonical uniqueness does not apply.
        old=store.completed(name)
        if old:
            if fingerprint(store,query)!=old['fingerprint']:raise ValueError('Exception source changed')
            rows=list(store.rows(name))
        else:
            fp=fingerprint(store,query);part,raw=command_sql(store,name,query.select,10)
            if len(raw)!=fp['n']:raise ValueError('Exception source changed during read')
            if any(r['ts_code']!=code or r['end_date'] not in dates for r in raw):raise ValueError('Exception scope mismatch')
            store.seal(name,part,len(raw),fp);rows=list(store.rows(name))
        row_count+=len(rows)
        if row_count>SPEC.max_exception_rows:raise ValueError('Exception row budget')
        first={}
        for row in rows:first.setdefault(row['end_date'],row)
        truncated=bool(rows and rows[0]['available_versions']>10)
        result={'name':name,'code':code,'dates':dates,'rows':len(rows),'truncated':truncated,'selected':[dict(r) for r in first.values()]}
        if len(dates)==2 and all(d in first for d in dates):
            from decimal import Decimal
            a,b=first[dates[0]],first[dates[1]]
            vals=[a['profit_dedt'],b['profit_dedt'],b['q_dtprofit']]
            result['difference']=None if any(v is None for v in vals) else b['q_dtprofit']-(b['profit_dedt']-a['profit_dedt'])
            result['resolved_as_equivalent']=result['difference'] is not None and abs(result['difference'])<=Decimal(SPEC.amount_tolerance)
        else:
            result['preferred_is_null']=bool(first and next(iter(first.values()))['profit_dedt'] is None)
            result['alternate_nonnull']=any(r['profit_dedt'] is not None for r in rows)
        findings.append(result)
        print(json.dumps({'stage':'exception_audit','unit':name,'done':index,'total':len(units),'percent':round(index/len(units)*100,1),'rows':len(rows)}),flush=True)
    output={'units':len(findings),'rows':row_count,'historical_conflict_total':23,'historical_unique_candidate_pairs':len(known_exceptions())-3,
            'complete_global_conflict_list':False,'global_rescan_performed':False,'findings':findings}
    atomic_json(store.path/'evidence/version_audit.json',output)
    return output
