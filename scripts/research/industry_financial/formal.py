"""Authorized, fixed full-study extraction. Financial formulas are shared."""
from dataclasses import replace
import json
import os
from .spec import SPEC,FORMAL_SCOPE
from .storage import Cancelled,atomic_json,load
from .extract import (Query,codes_sql,mapping_query,valuation_query,financial_query,
                      run_unit,command_sql,resolve_mapping,verify_source)

IDENTITY_COLUMNS='ts_code,name,fullname,curr_type,list_date,delist_date,list_status,fetched_at'


def candidate_where():
    return (f"list_status IN ('L','P') AND list_date<=DATE '{SPEC.snapshot}' "
            f"AND (delist_date IS NULL OR delist_date>DATE '{SPEC.snapshot}') "
            f"AND ts_code !~ '^(200|900)' AND ts_code NOT IN ({codes_sql(SPEC.excluded)})")


def batches(codes,size):
    codes=tuple(codes)
    if not codes or len(codes)>FORMAL_SCOPE.max_codes or len(set(codes))!=len(codes):raise ValueError('Invalid formal code pool')
    if size not in (500,2000):raise ValueError('Unapproved batch size')
    return [codes[i:i+size] for i in range(0,len(codes),size)]


def identity_query(index,after):
    if index not in (0,1,2):raise ValueError('Identity page outside approved scope')
    if after:
        codes_sql([after]);where=f" AND ts_code>'{after}'"
    else:where=''
    select=f"SELECT {IDENTITY_COLUMNS} FROM raw_tushare.stock_basic WHERE {candidate_where()}{where} ORDER BY ts_code LIMIT 2000"
    fp=f"SELECT count(*) n,md5(string_agg(row_to_json(q)::text,'' ORDER BY ts_code)) content FROM ({select}) q"
    return Query(f'identity_p{index:02d}',select,2000,fp)


def tree_query():
    cols='sector_code,sector_name,industry_level,parent_sector_code,parent_sector_name,root_sector_code,root_sector_name,baseline_version,published_at'
    select=f"SELECT {cols} FROM core_serving.wealth_sector_hierarchy WHERE baseline_version='{SPEC.baseline}' ORDER BY industry_level,sector_code LIMIT 497"
    return Query('tree',select,496,f"SELECT count(*) n,md5(string_agg(row_to_json(q)::text,'' ORDER BY sector_code)) content FROM ({select}) q")


def qualified_count(store,name):
    part,rows=command_sql(store,name,f"SELECT count(*) n FROM raw_tushare.stock_basic WHERE {candidate_where()}",1)
    os.replace(part,store.path/'evidence'/f'{name}.jsonl')
    if len(rows)!=1 or rows[0]['n']!=FORMAL_SCOPE.max_codes:raise ValueError('Candidate count changed from approved 5571; no automatic expansion')


def validate_identity(rows):
    codes=[r['ts_code'] for r in rows]
    if len(codes)!=5571 or len(set(codes))!=5571 or codes!=sorted(codes):raise ValueError('Incomplete/duplicate identity pool')
    if set(codes)&set(SPEC.excluded):raise ValueError('Excluded company selected')
    if any(r['curr_type']!='CNY' or r['list_status'] not in ('L','P') for r in rows):raise ValueError('Identity currency/status mismatch')


def extract_formal(store,stop_after=None):
    if store.scope!=FORMAL_SCOPE:raise ValueError('Explicit formal scope required')
    store.save(status='EXTRACTING_FORMAL',total_units=151)
    qualified_count(store,'candidate_count_before')
    processed=0;queries=[];parts={}
    def save_parts():atomic_json(store.path/'evidence/input_parts.json',parts)
    def unit(q):
        nonlocal processed
        rows,fresh=run_unit(store,q);queries.append(q);processed+=1
        done=store.state['completed']
        print(json.dumps({'stage':'extract_formal','unit':q.name,'completed':done,'total':151,'percent':round(done/151*100,1),'rows':len(rows),'reused':not fresh,'eta':'暂无法估算'}),flush=True)
        if stop_after and processed>=stop_after:raise Cancelled('Controlled formal resume acceptance stop')
        return rows
    samples=[];ids=[];after=''
    for i in range(3):
        q=identity_query(i,after);rows=unit(q)
        if not rows:raise ValueError('Early end of identity pages')
        samples.extend(rows);ids.append(q.name);after=rows[-1]['ts_code']
    validate_identity(samples);parts['sample']=ids;save_parts()
    tree=unit(tree_query())
    levels={level:sum(r['industry_level']==level for r in tree) for level in (1,2,3)}
    if levels!={1:31,2:128,3:337}:raise ValueError('Published hierarchy counts changed')
    codes=tuple(r['ts_code'] for r in samples)
    mappings=[];names=[]
    for i,chunk in enumerate(batches(codes,500)):
        q=replace(mapping_query(chunk,500,2000),name=f'mapping_b{i:02d}')
        rows=unit(q);mappings.extend(rows);names.append(q.name)
    if len(mappings)>FORMAL_SCOPE.max_member_rows:raise ValueError('Membership row budget exceeded')
    parts['mapping']=names;save_parts()
    mapped=resolve_mapping(samples,mappings)
    atomic_json(store.path/'calculations/sample.json',mapped)
    names=[]
    for i,chunk in enumerate(batches(codes,2000)):
        q=replace(valuation_query(chunk,2000),name=f'valuation_b{i:02d}')
        unit(q);names.append(q.name)
    parts['valuation']=names;save_parts()
    financial_rows=0
    for kind in ('income','balancesheet','cashflow','fina_indicator'):
        for date in SPEC.dates:
            names=[]
            for i,chunk in enumerate(batches(codes,2000)):
                q=replace(financial_query(kind,date,chunk,2000,industrial_only=False),name=f'{kind}_{date}_b{i:02d}')
                rows=unit(q);financial_rows+=len(rows);names.append(q.name)
                if financial_rows>FORMAL_SCOPE.max_rows:raise ValueError('Financial record budget exceeded')
            parts[kind+'_'+date]=names;save_parts()
    atomic_json(store.path/'evidence/query_plan.json',[dict(name=q.name,select=q.select,limit=q.limit,fingerprint=q.fingerprint,codes=q.codes,dates=q.dates,industrial_only=q.industrial_only) for q in queries])
    verify_source(store,queries)
    qualified_count(store,'candidate_count_after')
    store.save(status='FORMAL_INPUTS_FROZEN',financial_rows=financial_rows,processed_units=processed)
    return mapped


def saved_queries(store):
    return [Query(r['name'],r['select'],r['limit'],r['fingerprint'],tuple(r['codes']),tuple(r['dates']),r['industrial_only']) for r in load(store.path/'evidence/query_plan.json')]
