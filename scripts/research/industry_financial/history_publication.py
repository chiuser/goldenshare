"""Historical chapters from already authorized, immutable local income (§10.14)."""
from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import time

from .metrics import Book, R, P, sample_id
from .publication import (SPEC, HISTORY_SPEC as HS, FrozenSource, PublicationRun,
                          TOTAL_REVENUE, MONEY, numeric, rss_bytes,
                          protect_history, inherited_sample, validate_snapshot)
from .spec import SPEC as RS
from .storage import OUTPUT_ROOT, atomic_json, digest, load


def profit_change(current, previous, prior_revenue):
    """Business state and growth: positive, material base only. Inputs in yuan."""
    if None in (current, previous, prior_revenue):
        return None, '无上年同期可比数据'
    if previous < 0:
        return None, ('扭亏' if current >= 0 else '减亏' if current > previous else '亏损扩大' if current < previous else '亏损持平')
    if current < 0:
        return None, '转亏'
    if previous == 0 or prior_revenue <= 0 or previous / prior_revenue < D(RS.near_zero_profit):
        return None, '近零或无效基数'
    return (current / previous - 1) * 100, ('增加' if current > previous else '减少' if current < previous else '持平')


def income_projection(source, members, check=lambda: None):
    identities = {m['ts_code']: m for m in members}
    if len(identities) != len(members) or any(m['curr_type'] != 'CNY' for m in members):
        raise ValueError('Duplicate identity or unverified income currency')
    parts = source.json('evidence/input_parts.json')
    physical = []
    for period in HS.periods:
        if not parts.get('income_' + period):
            raise ValueError('Missing historical income window')
        for name in parts['income_' + period]:
            receipt = source.json('evidence/' + name + '.receipt.json')
            path = source.root / receipt['artifact']
            physical.append((period, receipt, path))
    size = sum(p.stat().st_size for _, _, p in physical)
    if size > HS.income_bytes:
        raise ValueError('Historical income byte budget exceeded')
    records, seen = [], set()
    for i, (period, receipt, path) in enumerate(physical):
        check()
        path = source.verified(receipt['artifact'])
        if digest(path) != receipt['sha256']:
            raise ValueError('Historical income receipt mismatch')
        with path.open() as stream:
            for line in stream:
                r = json.loads(line, parse_float=D)
                fields = ['ts_code', 'end_date', 'report_type', 'revenue', 'n_income_attr_p']
                if any(k not in r for k in fields):
                    raise ValueError('Historical income column absent')
                code = r['ts_code']
                if code not in identities or r['end_date'] != period or r['report_type'] != '1':
                    raise ValueError('Unexpected historical income identity/period/consolidation')
                key = (code, period)
                if key in seen:
                    raise ValueError('Duplicate historical income key')
                seen.add(key)
                if identities[code]['root_name'] in ('银行', '非银金融') and period in HS.nine_month_periods:
                    fields.append('total_revenue')
                    if 'total_revenue' not in r:
                        raise ValueError('Financial total_revenue column absent')
                records.append({k: r[k] for k in fields})
                if len(records) > HS.max_records:
                    raise ValueError('Historical income record budget exceeded')
        print(f'HISTORY_INPUT {i+1}/{len(physical)} {period}', flush=True)
        check()
    return records, size


def panel(book, codes, identity, root_name, quarter=False, finance=False):
    periods = HS.periods if quarter else HS.nine_month_periods
    revenue_field = TOTAL_REVENUE if finance else R
    requirements = [(f, d) for f in (revenue_field, P) for d in periods]
    selected = book.common(codes, requirements)
    rows, exact = [], {}
    for date in periods:
        revenue = book.total(revenue_field, selected, date, quarter=quarter)
        profit = book.total(P, selected, date, quarter=quarter)
        known = book.common(codes, [(revenue_field, date)])
        denominator = book.total(revenue_field, known, date)
        cumulative = book.total(revenue_field, selected, date)
        coverage = None if denominator is None or denominator <= 0 or cumulative is None else cumulative / denominator * 100
        if coverage is not None and not 0 <= coverage <= 100:
            raise ValueError('Invalid historical known-revenue coverage')
        prior_date = str(int(date[:4])-1) + date[4:]
        previous = exact.get(prior_date)
        p0 = previous['profit'] if previous else None
        r0 = previous['revenue'] if previous else None
        growth, state = profit_change(profit, p0, r0)
        r_growth = None if revenue is None or r0 is None or r0 <= 0 else (revenue / r0 - 1) * 100
        row = {'行业': identity['sector_name'], '所属一级行业': root_name,
               '层级': '一级' if identity['level'] == 1 else '二级', '年份': date[:4],
               '报告期': date, '季度': 'Q' + str((int(date[5:7])+2)//3),
               '营业总收入（亿元）' if finance else '营业收入（亿元）': numeric(revenue, MONEY),
               '归母净利润（亿元）': numeric(profit, MONEY), '收入同比（%）': numeric(r_growth),
               '归母利润同比（%）': numeric(growth), '利润变化状态': state,
               '归母利润增减（亿元）': numeric(None if profit is None or p0 is None else profit-p0, MONEY),
               '可比公司数': len(selected), '候选公司数': len(codes),
               '已知累计收入覆盖（%）': numeric(coverage),
               '可用状态': '可比' if selected else '缺少全期间可比数据'}
        rows.append(row)
        exact[date] = {'revenue': revenue, 'profit': profit}
    quarter_checks = {}
    if quarter and selected:
        for year, end in (('2024','12-31'), ('2025','12-31'), ('2026','09-30')):
            for f, key in ((revenue_field, 'revenue'), (P, 'profit')):
                residual = sum((v[key] for d, v in exact.items() if d.startswith(year)), D(0))-book.total(f, selected, year+'-'+end)
                if residual != 0:
                    raise ValueError('Quarterly amounts do not equal cumulative income')
                quarter_checks[year + '_' + key] = residual
    return {'rows': rows, 'audit': {'codes': selected, 'sample_id': sample_id(selected), 'exact': exact,
            'excluded': book.explain(codes, requirements, selected), 'quarter_residuals': quarter_checks}}


def reconcile_panels(parent, children):
    union = [code for c in children for code in c['audit']['codes']]
    if len(union) != len(set(union)) or set(union) != set(parent['audit']['codes']):
        raise ValueError('Historical parent/child company sets differ')
    residuals = {}
    for date, values in parent['audit']['exact'].items():
        for field, amount in values.items():
            parts = [c['audit']['exact'][date][field] for c in children if c['audit']['codes']]
            delta = sum((D(str(p)) for p in parts), D(0)) - (D(str(amount)) if amount is not None else D(0))
            if abs(delta) > D(RS.amount_tolerance):
                raise ValueError('Historical parent/child amounts differ')
            residuals[date + '_' + field] = delta
    return residuals


def reconcile_old_panel(roots, frozen):
    residuals = {}
    for root in roots:
        if root['identity']['financial']:
            continue
        p = root['nine_month']
        for old in frozen['sector_rows']:
            if old['root'] != root['identity']['sector_code']:
                continue
            date = old['报告期']
            if len(p['audit']['codes']) != old['共同公司数'] or p['audit']['sample_id'] != old['集合ID']:
                raise ValueError('Frozen three-year company set changed')
            for key, old_key in (('revenue','收入亿元'), ('profit','归母利润亿元')):
                delta = D(str(p['audit']['exact'][date][key])) - D(str(old[old_key])) * MONEY
                if abs(delta) > D(RS.amount_tolerance):
                    raise ValueError('Frozen three-year amount changed')
                residuals[root['identity']['sector_code']+'_'+date+'_'+key] = delta
    for date, old in frozen['overall_exact'].items():
        ns = [r['nine_month'] for r in roots if not r['identity']['financial']]
        if sum(len(p['audit']['codes']) for p in ns) != old['n']:
            raise ValueError('Frozen overall three-year count changed')
        for key, old_key in (('revenue','revenue'), ('profit','parent_profit')):
            delta = sum((D(str(p['audit']['exact'][date][key])) for p in ns), D(0)) - D(str(old[old_key]))
            if abs(delta) > D(RS.amount_tolerance):
                raise ValueError('Frozen overall three-year amount changed')
    return residuals


def add_queries(snapshot, roots, overall):
    result = deepcopy(snapshot)
    definitions = {
      'history_primary': ('一级三年前三季', [r for g in roots if not g['identity']['financial'] for r in g['nine_month']['rows']], False),
      'history_secondary': ('二级三年前三季', [r for g in roots if not g['identity']['financial'] for c in g['children'] for r in c['nine_month']['rows']], False),
      'history_quarter_primary': ('一级单季', [r for g in roots if not g['identity']['financial'] for r in g['quarter']['rows']], True),
      'history_quarter_secondary': ('二级单季', [r for g in roots if not g['identity']['financial'] for c in g['children'] for r in c['quarter']['rows']], True),
      'history_quarter_overall': ('非金融整体单季', overall['rows'], True),
      'history_financial': ('金融三年前三季', [r for g in roots if g['identity']['financial'] for obj in [g]+g['children'] for r in obj['nine_month']['rows']], False)}
    for name, (label, rows, quarterly) in definitions.items():
        result['queries'][name] = {'rows': rows, 'source': {
          'label': label, 'scope': ('2024Q1—2026Q3；全11期收入和归母共同有效公司' if quarterly else '2024/2025/2026年1—9月；三个期间收入和归母共同有效公司')+'；财务11/1冻结，归属10/30固定',
          'files': ['formal_20261101_01/inputs/income；冻结白名单', '逐行业历史计算及原三年面板核验'],
          'filters': ['东财2025年末分类体系，固定最新公司归属', '人民币合并口径；原缺失和已知可比边界保留'],
          'metricDefinitions': [{'label': '收入与归母利润', 'definition': ('先逐公司差分：Q1原值、Q2=H1−Q1、Q3=9M−H1、Q4=全年−9M，再合计；2026Q4尚无实际。' if quarterly else '三个年份分别合计同一批公司，不混入全年。') + ('金融收入使用营业总收入，与非金融营业收入分开。' if name=='history_financial' else '')},
              {'label': '同比及利润状态', 'definition': '收入同比基期必须为正；正常利润同比要求基期利润为正、当期非负、基期利润率≥0.1%。其他情况保留扭亏/转亏/减亏等状态与金额；2024同比为空，不读取2023。'},
              {'label': '收入覆盖及公司数', 'definition': '可比公司数各图期间固定。覆盖=这些公司的当期累计收入÷本行业当期已知累计收入；不代表未知公司的收入覆盖。'}],
          'caveats': ['三年同期与全11期公司范围分别固定，不能混用；湖北宜化等原可比排除保留。', '缺失不填零，近零/负利润基数不展示正常同比。']}}
    for name, query in snapshot['queries'].items():
        if result['queries'][name] != query:
            raise ValueError('Accepted current chapter query changed')
    result['study']['stage'] = 'history'
    result['study']['history'] = {'featured': ['电子','煤炭','食品饮料','农林牧渔'],
        'cases': snapshot['study']['caseNames'], 'primaryGroups': [
            [g['identity']['sector_name'] for g in roots if not g['identity']['financial']][i:i+HS.max_heat_rows]
            for i in range(0,29,HS.max_heat_rows)]}
    result['buildStatus'] = 'updating'
    return result


def prepare_history(output, previous_output, resume=False):
    started = time.monotonic()
    previous_output = Path(previous_output).resolve()
    if previous_output.parent != OUTPUT_ROOT or not previous_output.name.startswith('narrative_') or previous_output == output:
        raise ValueError('Unsafe previous historical report')
    protected = protect_history()
    previous = FrozenSource(previous_output)
    snapshot = json.loads(previous.verified('data.json').read_text())
    previous.verified('report.html')
    if snapshot['buildStatus'] != 'complete' or snapshot['study']['stage'] != 'current':
        raise ValueError('History requires an accepted complete current chapter')
    env = json.loads(previous.verified('evidence/environment.json').read_text())
    prep = load(OUTPUT_ROOT/SPEC.preparation_run/'evidence/preparation_baseline.json')
    key = f'reports/a_share_industry_prosperity_2026q3/{SPEC.source_run}/evidence/artifact_manifest.json'
    source = FrozenSource(OUTPUT_ROOT/SPEC.source_run, prep['before_sha256'][key])
    members = source.json('calculations/sample.json')
    groups = source.json('calculations/groups.json')
    frozen = source.json('calculations/three_year_common_panel.json')
    quality = source.json('evidence/quality.json')
    if len(members) != 5571 or len(groups) != 31 or sum(len(g['children']) for g in groups) != 128:
        raise ValueError('Frozen historical scope changed')
    child_parent = {c['identity']['sector_code']: g['identity']['sector_code'] for g in groups for c in g['children']}
    if len(child_parent) != 128 or any(child_parent.get(m['parent']) != m['root'] for m in members):
        raise ValueError('Invalid frozen industry membership')
    # Fingerprint input manifest before opening any income; it freezes each file.
    fingerprint = {'source_manifest': source.used['evidence/artifact_manifest.json'],
        'previous_manifest': previous.used['evidence/artifact_manifest.json'],
        'previous_data': previous.used['data.json'], 'publication': digest(Path(__file__).with_name('publication.py')),
        'history_implementation': digest(__file__)}
    run = PublicationRun(output, fingerprint, resume, spec=HS)
    atomic_json(run.path/'evidence/history_before.json', protected)
    records, physical_size = income_projection(source, members, run.check)
    book = Book({'income': records}, noncomparable=quality.get('noncomparable_codes', {}))
    del records
    roots = []
    by_root = {g['identity']['sector_code']: [m for m in members if m['root']==g['identity']['sector_code']] for g in groups}
    for g in groups:
        identity = g['identity']; code = identity['sector_code']; root_name = identity['sector_name']
        def produce(g=g, identity=identity, code=code, root_name=root_name):
            root_members = by_root[code]; finance = identity['financial']
            def calculate(obj):
                i = obj['identity']; codes = [m['ts_code'] for m in root_members if i['level']==1 or m['parent']==i['sector_code']]
                result = {'identity':i, 'nine_month':panel(book,codes,i,root_name,finance=finance)}
                if not finance:
                    result['quarter'] = panel(book,codes,i,root_name,quarter=True)
                return result
            result = calculate(g); result['children'] = [calculate(c) for c in g['children']]
            result['reconciliation'] = {'nine_month':reconcile_panels(result['nine_month'],[c['nine_month'] for c in result['children']])}
            if not finance:
                result['reconciliation']['quarter'] = reconcile_panels(result['quarter'],[c['quarter'] for c in result['children']])
            return result
        roots.append(run.unit(code, produce))
    residuals = reconcile_old_panel(roots, frozen)
    nonfinance = [m['ts_code'] for m in members if m['root_name'] not in ('银行','非银金融')]
    overall = panel(book, nonfinance, {'sector_name':'非金融整体','level':1}, '非金融整体', quarter=True)
    reconcile_panels(overall, [r['quarter'] for r in roots if not r['identity']['financial']])
    result = add_queries(snapshot, roots, overall)
    validate_snapshot(result, inherited_sample())
    aggregate_size = sum((source.root/p).stat().st_size for p in source.used if not p.startswith('inputs/'))
    if aggregate_size > HS.aggregate_bytes:
        raise ValueError('Historical metadata budget exceeded')
    atomic_json(run.path/'data.json',result)
    atomic_json(run.path/'evidence/environment.json',env)
    atomic_json(run.path/'calculations/overall_quarter.json',overall)
    atomic_json(run.path/'evidence/old_panel_residuals.json',residuals)
    atomic_json(run.path/'evidence/source_manifest.json',{'files':source.used,'previous_run':previous_output.name,
        'previous_files':previous.used,'aggregate_bytes':aggregate_size,'income_physical_bytes':physical_size,
        'income_projection_rows':len(book.data['income']), 'source_connections':0})
    acceptance = {'quarter_companies':len(overall['audit']['codes']), 'three_year_companies':5275,
        'quarter_parent_child_and_cumulative_equal':True, 'old_panel_amounts_and_company_sets_equal':True,
        'accepted_queries_unchanged':True,'source_connections':0,'forecast_or_score_executed':False,
        'query_rows':{k:len(q['rows']) for k,q in result['queries'].items() if k.startswith('history')},
        'peak_python_bytes':rss_bytes(),'seconds':time.monotonic()-started}
    atomic_json(run.path/'evidence/history_acceptance.json',acceptance)
    if protect_history() != protected:
        raise ValueError('Protected source changed')
    run.save(status='HISTORY_PROJECTED');run.check()
    print('HISTORY_PROJECTED',acceptance,flush=True)
