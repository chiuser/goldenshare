"""Independent source literals and bounded artifact acceptance, never source writes."""
from decimal import Decimal as D
from pathlib import Path
from .storage import atomic_json,load,digest
from .spec import SPEC
from .metrics import Book,R,DED,C
from .extract import (selection_query,mapping_query,valuation_query,financial_query,
                      exception_query,known_exceptions,validate_rows)

# Issuer annual quarterly tables already inspected, not calculated by Book.flow.
# Page/source references are kept alongside the independent literals in evidence.
ANNOUNCEMENT_QUARTERS=(
    ('000568.SZ','2024-12-31','6892693021.03','1835111684.27','6717053567.54',
     'https://static.cninfo.com.cn/finalpage/2025-04-28/1223330076.PDF',2),
    ('000021.SZ','2024-12-31','3975480893.35','283517764.68','510904424.78',
     'https://static.cninfo.com.cn/finalpage/2025-04-25/1223270318.PDF',3),
    ('000422.SZ','2025-12-31','6486099289.91','-13937945.37','488882335.43',
     'https://static.cninfo.com.cn/finalpage/2026-04-25/1225183616.PDF',10),
)


def frozen_queries(store):
    codes=tuple(r['ts_code'] for r in store.rows('sample'))
    return [selection_query(),mapping_query(codes),valuation_query(codes)]+[
        financial_query(k,d,codes) for k in ('income','balancesheet','cashflow','fina_indicator') for d in SPEC.dates]+[
        exception_query(n,c,ds) for n,c,ds in known_exceptions()]


def manual_checks(store):
    results=[]
    for code,date,r,d,c,url,page in ANNOUNCEMENT_QUARTERS:
        book=Book.from_run(store,[code])
        for field,expected in ((R,r),(DED,d),(C,c)):
            actual=book.flow(field,code,date)
            results.append({'code':code,'date':date,'field':field,'expected':expected,'actual':actual,
                            'difference':None if actual is None else actual-D(expected),
                            'pass':actual is not None and abs(actual-D(expected))<=D(SPEC.amount_tolerance),
                            'source_url':url,'page':page})
    # Fixed real valuation row copied before this check; source units are 万元/万股.
    # Moving the decimal four places independently gives the two literal expectations.
    quote=next(r for r in store.rows('valuation') if r['ts_code']=='000021.SZ')
    for field,expected in (('total_mv','40699779056'),('total_share','1584882362')):
        actual=D(quote[field])*10000
        results.append({'code':'000021.SZ','date':SPEC.snapshot,'field':field,'expected':expected,
                        'actual':actual,'pass':actual==D(expected),'basis':'frozen source quote in 万元/万股; four decimal places shifted'})
    output={'checks':results,'all_pass':all(r['pass'] for r in results),'tolerance_yuan':SPEC.amount_tolerance}
    atomic_json(store.path/'evidence/manual_checks.json',output)
    if not output['all_pass']:raise AssertionError('Independent source literal check failed')
    return output


def validate_artifacts(store):
    queries=frozen_queries(store)
    receipts=[store.completed(q.name) for q in queries]
    if any(r is None for r in receipts):raise ValueError('Missing frozen unit')
    for q in queries[:47]:validate_rows(q,list(store.rows(q.name)))
    samples=load(store.path/'calculations/sample.json')
    groups=load(store.path/'calculations/groups.json')
    ranking=load(store.path/'calculations/ranking.json')
    checks=load(store.path/'evidence/reconciliation.json')
    if not checks['all_pass']:raise ValueError('Ledger checks did not pass')
    root_codes=[c for g in groups for c in g['forecasts']['D'].get('codes',[])]
    if len(root_codes)!=len(set(root_codes)):raise ValueError('Duplicate company across roots')
    render=load(store.path/'evidence/chart_render_receipts.json')
    qa=load(store.path/'evidence/browser_qa.json') if (store.path/'evidence/browser_qa.json').exists() else {'pass':False,'reason':'not_checked'}
    if qa.get('pass'):
        if qa.get('report_sha256')!=digest(store.path/'report.html'):raise ValueError('Browser QA belongs to another report version')
        for level in (1,2):
            actual={row['chart']:row['points'] for row in qa[f'l{level}']}
            expected={row['number']:row['rows'] for row in render['charts'] if row['level']==level}
            if actual!=expected:raise ValueError('Browser point counts differ from frozen chart payload')
    payload_checks=[]
    for chart in render['charts']:
        stem=f"L{chart['level']}_chart{chart['number']}"
        p=load(store.path/'charts'/f'{stem}.json')
        a=load(store.path/'charts'/f'{stem}_audit.json')
        if len(p['rows'])!=a['plotted'] or len(p['rows'])!=chart['rows']:raise ValueError('Chart count mismatch')
        if len({r['row_id'] for r in p['rows']})!=len(p['rows']):raise ValueError('Duplicate chart point')
        if sum(a['quadrant_counts'].values())!=a['plotted']:raise ValueError('Quadrant count mismatch')
        if any(not r['sample_id'] or r['样本数']<=0 for r in p['rows']):raise ValueError('Missing chart common sample')
        payload_checks.append({'chart':stem,'points':len(p['rows']),'missing':len(a['not_plotted']),'pass':True})
    exceptions=load(store.path/'evidence/version_audit.json')
    output={'scope':'bounded engineering trial only','selected_companies':len(samples),
            'selected_roots':len(groups),'second_level_groups':sum(len(g['children']) for g in groups),
            'primary_units':47,'exception_units':len(receipts)-47,
            'financial_rows':sum(r['rows'] for q,r in zip(queries,receipts) if q.name.startswith(('income_','balancesheet_','cashflow_','fina_indicator_'))),
            'exception_rows':exceptions['rows'],'all_receipt_hashes_valid':True,'ledger_pass':True,
            'manual_checks_pass':load(store.path/'evidence/manual_checks.json')['all_pass'],
            'chart_payloads':payload_checks,'browser_qa':qa,
            'ranked_groups':{level:sum(bool(r.get('score_available')) for r in rows) for level,rows in ranking.items()},
            'known_limitations':['sample not representative of whole industries','issuer semantics checked for only 3 companies',
                                 '22 historical conflict candidates remain different; current global conflict list incomplete',
                                 'restatement adjustment not written back or patched','provisional gates/scenarios are not formal parameter approval'],
            'full_market_report_ready':False,'spec_hash':SPEC.digest(),
            'code_hashes':{p.name:digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))}}
    atomic_json(store.path/'evidence/acceptance.json',output)
    return output


def validate_formal(store):
    from .formal import saved_queries,validate_identity
    queries=saved_queries(store)
    receipts=[store.completed(q.name) for q in queries]
    if len(queries)!=151 or any(r is None for r in receipts):raise ValueError('Incomplete formal extraction')
    identities=list(store.rows('sample'));validate_identity(identities)
    samples=load(store.path/'calculations/sample.json')
    if len(samples)!=5571 or len({r['ts_code'] for r in samples})!=5571:raise ValueError('Mapped pool mismatch')
    groups=load(store.path/'calculations/groups.json');ranking=load(store.path/'calculations/ranking.json')
    if len(groups)!=31 or sum(len(g['children']) for g in groups)!=128:raise ValueError('Hierarchy group coverage')
    counts=[];nulls={};missing=[];codes={r['ts_code'] for r in samples}
    for kind in ('income','balancesheet','cashflow','fina_indicator'):
        for date in SPEC.dates:
            rows=list(store.rows(kind+'_'+date));keys=[r['ts_code'] for r in rows]
            if len(keys)!=len(set(keys)) or not set(keys)<=codes:raise ValueError('Batch expansion or duplicate financial record')
            if any(r['end_date']!=date for r in rows):raise ValueError('Wrong logical report period')
            counts.append({'dataset':kind,'period':date,'rows':len(rows),'candidate_companies':5571})
            missing.append({'dataset':kind,'period':date,'codes':sorted(codes-set(keys))})
            from .spec import FIELDS
            nulls[kind+'_'+date]={f:sum(r.get(f) is None for r in rows) for f in FIELDS[kind]}
    financial_rows=sum(r['rows'] for r in counts)
    if financial_rows>store.scope.max_rows:raise ValueError('Formal financial row budget')
    ledger=load(store.path/'evidence/reconciliation.json')
    if not ledger['all_pass']:raise ValueError('Formal ledger reconciliation failed')
    child_sum_checks=[]
    for group in groups:
        for kind in ('P','D','C'):
            parent=group['forecasts'][kind]
            if not parent['available']:continue
            children=[g['forecasts'][kind] for g in group['children'] if g['forecasts'][kind]['available']]
            for key in ('R9','X9','R_base','X_base','X_low','X_high'):
                residual=D(parent[key])-sum(D(c[key]) for c in children)
                if abs(residual)>D(SPEC.amount_tolerance):raise ValueError('Parent/child ledger difference')
                child_sum_checks.append({'root':group['identity']['sector_code'],'kind':kind,'field':key,'residual':residual})
    for level,rows in ranking.items():
        if any(r.get('eligible') and r.get('financial') for r in rows):raise ValueError('Financial industry entered nonfinancial ranking')
        for row in rows:
            if row.get('score_available') and (not row['eligible'] or len(row['raw'])!=7 or any(v is None for v in row['raw'])):raise ValueError('Incomplete score was ranked')
    conflicts=[dict(r,root=g['identity']['sector_code']) for g in groups for r in g['observed_deducted_quarter_conflicts']]
    atomic_json(store.path/'evidence/formal_coverage.json',{'counts':counts,'missing':missing,'nulls':nulls,'universe':5571,'financial_rows':financial_rows})
    atomic_json(store.path/'evidence/formal_q4_conflicts.json',{'conflicts':conflicts,'company_years':len(conflicts),'companies':len({r['code'] for r in conflicts}),'rule':'direct Q4 differs from cumulative difference by more than 1 yuan; no automatic release'})
    output={'scope':'approved current-company full industry study','companies':5571,'roots':31,'children':128,'financial_rows':financial_rows,
            'input_units':len(receipts),'input_hashes_valid':True,'ledger_pass':True,'child_sum_checks':child_sum_checks,
            'manual_checks_pass':load(store.path/'evidence/manual_checks.json')['all_pass'],
            'score_available':{k:sum(bool(r.get('score_available')) for r in rows) for k,rows in ranking.items()},
            'q4_conflict_company_years':len(conflicts),'data_quality':'known gaps retained; not a complete restatement audit',
            'source_check':load(store.path/'evidence/source_check.json'),'spec_hash':store.spec_hash,
            'source_code_hashes':{str(p):digest(p) for p in Path(__file__).parent.glob('*.py')}}
    atomic_json(store.path/'evidence/formal_acceptance.json',output)
    return output


def validate_report_snapshot(store):
    """Reconcile displayed row bindings/units with the already frozen ledgers."""
    import json
    snapshot=json.loads((store.path/'calculations/report_snapshot.json').read_text())
    rankings=load(store.path/'calculations/ranking.json')
    checked=[]
    for cfg in snapshot['study']['chartConfigs']:
        original=json.loads((store.path/'charts'/(cfg['id']+'.json')).read_text())
        rows=snapshot['queries'][cfg['id']]['rows']
        if rows!=original['rows'] or cfg['spec']!=original['spec']:raise ValueError('Report chart differs from frozen chart')
        if len({r['row_id'] for r in rows})!=len(rows):raise ValueError('Duplicate displayed industry')
        for r in rows:
            if not all(isinstance(r[k],(int,float)) for k in ('x','y')):raise ValueError('Displayed coordinate type changed')
            if not isinstance(json.loads(r['raw_values']),dict):raise ValueError('Tooltip raw values lack metric names')
        checked.append({'id':cfg['id'],'rows':len(rows),'same_coordinates_references':True})
    if len(checked)!=18:raise ValueError('Missing approved quadrant view')
    for level,source in rankings.items():
        rows=snapshot['queries']['rank_'+level]['rows'];by_code={r['行业代码']:r for r in rows}
        if len(rows)!=len(source):raise ValueError('Ranking coverage changed')
        for r in source:
            shown=by_code[r['sector_code']]
            if shown['名次']!=r.get('rank') or shown['N']!=r['n']:raise ValueError('Ranking/sample differs')
            for display,key in [('预测收入亿元','R_base'),('预测扣非亿元','X_base')]:
                value=r.get(key);actual=shown[display]
                if (value is None)!=(actual is None):raise ValueError('Missing forecast replaced')
                if value is not None and abs(D(str(actual))*100000000-D(value))>1:raise ValueError('Forecast display unit conversion')
    panel=load(store.path/'calculations/three_year_common_panel.json')
    for r in snapshot['queries']['three_year_totals']['rows']:
        exact=panel['overall_exact'][r['报告期']]
        if r['共同公司数']!=exact['n']:raise ValueError('Fixed panel company count')
        if abs(D(str(r['收入亿元']))*100000000-D(exact['revenue']))>1:raise ValueError('Fixed panel currency conversion')
    result={'chart_views':checked,'ranking_and_forecast_display_pass':True,'fixed_panel_display_pass':True,
            'financial_observation_rows':len(snapshot['queries']['financial_observations']['rows']),
            'history_rows':len(snapshot['queries']['history_1']['rows']),'snapshot_sha256':digest(store.path/'calculations/report_snapshot.json')}
    atomic_json(store.path/'evidence/report_acceptance.json',result)
    return result
