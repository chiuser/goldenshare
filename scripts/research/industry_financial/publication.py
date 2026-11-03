"""Current-financial report from immutable local evidence; no source connections."""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal as D
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from .metrics import Book, P, ratio
from .sample_chapters import quadrant_row, STATES
from .spec import SPEC as RESEARCH_SPEC
from .storage import ROOT, OUTPUT_ROOT, atomic_json, digest, load


@dataclass(frozen=True)
class PublicationSpec:
    source_run: str = 'formal_20261101_01'
    sample_run: str = 'chapter_samples_20261102_01'
    preparation_run: str = 'preparation_20261102_01'
    stage: str = 'current'
    periods: tuple = ('2025-09-30', '2026-09-30')
    max_heat_rows: int = 16
    max_cases: int = 6
    aggregate_bytes: int = 50 * 1024**2
    memory_bytes: int = 512 * 1024**2
    output_bytes: int = 100 * 1024**2
    calculation_seconds: int = 300
    unit_seconds: int = 30
    build_seconds: int = 45
    max_builds: int = 3
    blue: str = '#3276b5'
    teal: str = '#0f9185'
    year_colors: tuple = (('2024', '#94a3b8'), ('2025', '#4f78ac'), ('2026', '#0f9185'))


SPEC = PublicationSpec()


@dataclass(frozen=True)
class HistoryPublicationSpec(PublicationSpec):
    stage: str = 'history'
    periods: tuple = RESEARCH_SPEC.dates
    nine_month_periods: tuple = ('2024-09-30', '2025-09-30', '2026-09-30')
    income_bytes: int = 150 * 1024**2
    max_records: int = 61281
    calculation_seconds: int = 600


HISTORY_SPEC = HistoryPublicationSpec()


@dataclass(frozen=True)
class ForecastPublicationSpec(PublicationSpec):
    stage: str = 'forecast'
    primary_top: int = 10
    secondary_top: int = 15
    prediction_color: str = '#d2933b'


FORECAST_SPEC = ForecastPublicationSpec()
TOTAL_REVENUE = ('income', 'total_revenue')
MONEY = D('100000000')


def numeric(x, scale=1):
    return None if x is None else float(D(str(x)) / D(scale))


def rss_bytes():
    n = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return n if sys.platform == 'darwin' else n * 1024


def safe_relative(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()) or p == root.resolve():
        raise ValueError('Source path outside immutable run')
    return p


class FrozenSource:
    def __init__(self, root, expected_manifest=None):
        self.root = Path(root).resolve()
        p = self.root / 'evidence/artifact_manifest.json'
        if expected_manifest and digest(p) != expected_manifest:
            raise ValueError('Frozen source manifest changed')
        self.manifest = load(p)['files']
        self.used = {'evidence/artifact_manifest.json': digest(p)}

    def verified(self, relative):
        p = safe_relative(self.root, relative)
        expected = self.manifest.get(relative)
        if not expected or digest(p) != expected:
            raise ValueError('Frozen source hash mismatch: ' + relative)
        self.used[relative] = expected
        return p

    def json(self, relative):
        return load(self.verified(relative))

    def income(self, codes):
        """Scan the two declared logical windows once; retain only finance fields."""
        parts = self.json('evidence/input_parts.json')
        result = []
        for period in SPEC.periods:
            names = parts.get('income_' + period)
            if not names:
                raise ValueError('Missing approved income period')
            for name in names:
                receipt = self.json('evidence/' + name + '.receipt.json')
                p = self.verified(receipt['artifact'])
                if digest(p) != receipt['sha256']:
                    raise ValueError('Input receipt hash mismatch')
                with p.open() as stream:
                    for line in stream:
                        r = json.loads(line, parse_float=D)
                        if r['ts_code'] not in codes:
                            continue
                        fields = ('ts_code', 'end_date', 'total_revenue', 'n_income_attr_p', 'report_type')
                        if any(k not in r for k in fields):
                            raise ValueError('Financial income column absent')
                        if r['end_date'] != period or r['report_type'] != '1':
                            raise ValueError('Wrong frozen financial period/consolidation')
                        result.append({k: r[k] for k in fields})
        if len({(r['ts_code'], r['end_date']) for r in result}) != len(result):
            raise ValueError('Duplicate financial income key')
        return result


class PublicationRun:
    """Receipt is the committed fact; progress is replaceable observation."""
    def __init__(self, output, source_fingerprint, resume=False, base_root=OUTPUT_ROOT, spec=SPEC):
        self.path = Path(output).resolve()
        if self.path.parent != Path(base_root).resolve() or not self.path.name.startswith('narrative_'):
            raise ValueError('Only a direct narrative_ output is allowed')
        self.started = time.monotonic()
        self.spec = spec
        self.policy = json.loads(json.dumps(asdict(spec)))
        self.fingerprint = source_fingerprint
        manifest = self.path / 'run.json'
        if self.path.exists():
            if not resume or not manifest.exists():
                raise ValueError('Existing output requires a matching explicit resume')
            self.state = load(manifest)
            if self.state['spec'] != self.policy or self.state['source'] != source_fingerprint:
                raise ValueError('Source/spec changed; cannot resume')
        else:
            self.path.mkdir()
            for name in ('units', 'evidence', 'calculations'):
                (self.path / name).mkdir()
            self.state = {'stage': spec.stage, 'spec': self.policy, 'source': source_fingerprint,
                          'calculation_seconds': 0, 'completed': 0, 'total': 31}
        self.base_seconds = float(self.state['calculation_seconds'])
        self.save(status='PROJECTING_' + spec.stage.upper())

    def check(self):
        if (self.path / 'CANCEL').exists():
            raise InterruptedError('Local current report cancelled')
        if self.base_seconds + time.monotonic() - self.started > self.spec.calculation_seconds:
            raise ValueError('Current report calculation budget exceeded')
        if rss_bytes() > self.spec.memory_bytes:
            raise ValueError('Current report memory budget exceeded')
        if sum(p.stat().st_size for p in self.path.rglob('*') if p.is_file()) > self.spec.output_bytes:
            raise ValueError('Current report output budget exceeded')

    def save(self, **updates):
        self.state.update(updates)
        self.state['calculation_seconds'] = self.base_seconds + time.monotonic() - self.started
        atomic_json(self.path / 'run.json', self.state)

    def unit(self, name, producer):
        self.check()
        artifact = self.path / 'units' / (name + '.json')
        receipt_path = self.path / 'evidence' / (name + '.receipt.json')
        if receipt_path.exists():
            receipt = load(receipt_path)
            if not artifact.exists() or digest(artifact) != receipt['sha256']:
                raise ValueError('Committed unit hash mismatch')
            return json.loads(artifact.read_text())
        started = time.monotonic()
        value = producer()
        if time.monotonic() - started > self.spec.unit_seconds:
            raise ValueError('Current report unit exceeded budget')
        atomic_json(artifact, value)
        atomic_json(receipt_path, {'sha256': digest(artifact), 'unit': name})
        self.save(completed=len(list((self.path / 'evidence').glob('*.receipt.json'))))
        print(f'{self.spec.stage.upper()} {self.state["completed"]}/31 {name}', flush=True)
        self.check()
        return value


def business_meta(group, item, root_name):
    return {'行业': group['identity']['sector_name'], '所属一级行业': root_name,
            '可比公司数': item['n'], '候选公司数': item['candidate_n'],
            '本期已知收入覆盖（%）': numeric(item['coverage_current'].get('value'), D('.01')),
            '上年已知收入覆盖（%）': numeric(item['coverage_previous'].get('value'), D('.01'))}


def profit_parts(plot, top_metric):
    if set(plot['codes']) != set(top_metric['codes']):
        raise ValueError('Top-three contribution has a different company set')
    r = plot['raw']
    delta = D(r['parent_profit']) - D(r['prior_parent_profit'])
    top = sum((D(x['profit_change']) for x in top_metric['value']), D(0))
    return delta, top, delta - top


def current_projection(group, root_name):
    plots = group['facts']['plots']
    metrics = {r['metric']: r for r in group['facts']['metrics']}
    result = {'identity': group['identity'], 'queries': {}, 'audit': {'samples': {}}}
    q = result['queries']
    for key, number in (('profit', '1'), ('quality', '3'), ('receivable', '7'), ('inventory', '8'), ('fixed', '9')):
        item = plots[number]
        result['audit']['samples'][key] = {k: item[k] for k in ('sample_id', 'codes', 'n')}
        if not item.get('available'):
            q[key] = dict(business_meta(group, item, root_name), 可用状态='缺少可比数据')
            continue
        r = item['raw']
        row = business_meta(group, item, root_name)
        if key == 'profit':
            d, top, rest = profit_parts(item, metrics['prior_revenue_top3_parent_profit_contribution'])
            row.update({'归母利润增减（亿元）': numeric(d, MONEY), '前三大收入公司贡献（亿元）': numeric(top, MONEY),
                        '其余公司贡献（亿元）': numeric(rest, MONEY), '归母利润（亿元）': numeric(r['parent_profit'], MONEY),
                        '上年归母利润（亿元）': numeric(r['prior_parent_profit'], MONEY),
                        '营业收入（亿元）': numeric(r['revenue'], MONEY), '上年营业收入（亿元）': numeric(r['prior_revenue'], MONEY),
                        '收入同比（%）': numeric(item['x'])})
        elif key == 'quality':
            row.update({'扣非利润率变化（百分点）': numeric(item['x']), '经营现金流率变化（百分点）': numeric(item['y']),
                        '扣非利润率（%）': numeric(r['deducted_margin'], D('.01')),
                        '经营现金流率（%）': numeric(r['cashflow_margin'], D('.01'))})
        elif key in ('receivable', 'inventory'):
            row.update({'周转天数变化（天）': numeric(item['y']), '本期周转天数（天）': numeric(r['current_days']),
                        '上年周转天数（天）': numeric(r['prior_days']), '同公司收入同比（%）': numeric(item['x'])})
        else:
            row.update({'收入增长（%）': numeric(item['x']), '固定资产增长（%）': numeric(item['y'])})
        q[key] = row
    plot = plots['4']
    if plot.get('available'):
        point, audit = quadrant_row(group)
        point['所属一级行业'] = root_name
        q['quadrant'] = point
        q['breadth'] = dict(business_meta(group, plot, root_name), **{
            '利润改善公司比例（%）': numeric(D(plot['raw']['improved_companies']) / D(plot['raw']['total_companies']), D('.01'))})
        result['audit']['quadrant'] = audit
    else:
        q['quadrant'] = None
        q['breadth'] = dict(business_meta(group, plot, root_name), 可用状态='缺少可比数据')
    item = metrics['cash_surplus']
    q['capex'] = dict(business_meta(group, item, root_name), **{'现金流扣除资本开支（亿元）': numeric(item['value'], MONEY)})
    result['audit']['samples']['capex'] = {k: item[k] for k in ('sample_id', 'codes', 'n')}
    return result


def reconcile_parent(group):
    parent = group['facts']['plots']['1']
    children = [c['facts']['plots']['1'] for c in group['children'] if c['facts']['plots']['1'].get('available')]
    codes = [code for child in children for code in child['codes']]
    if len(codes) != len(set(codes)) or set(codes) != set(parent['codes']):
        raise ValueError('Parent/child comparable-company sets differ')
    residuals = {}
    for field in ('revenue', 'prior_revenue', 'parent_profit', 'prior_parent_profit'):
        v = sum((D(c['raw'][field]) for c in children), D(0)) - D(parent['raw'][field])
        if abs(v) > D(RESEARCH_SPEC.amount_tolerance):
            raise ValueError('Parent/child money does not reconcile')
        residuals[field] = v
    return residuals


def financial_projection(book, codes, identity, root_name):
    sample = book.common(codes, [(field, date) for field in (TOTAL_REVENUE, P) for date in SPEC.periods])
    data = []
    for date in SPEC.periods:
        revenue = book.total(TOTAL_REVENUE, sample, date)
        profit = book.total(P, sample, date)
        known = book.common(codes, [(TOTAL_REVENUE, date)])
        denominator = book.total(TOTAL_REVENUE, known, date)
        coverage = ratio(revenue, denominator)
        if coverage is not None and not 0 <= coverage <= 1:
            raise ValueError('Invalid financial known-revenue coverage')
        data.append({'行业': identity['sector_name'], '所属一级行业': root_name, '层级': '一级' if identity['level'] == 1 else '二级',
                     '年份': date[:4], '营业总收入（亿元）': numeric(revenue, MONEY), '归母净利润（亿元）': numeric(profit, MONEY),
                     '可比公司数': len(sample), '候选公司数': len(codes), '已知营业总收入覆盖（%）': numeric(coverage, D('.01')),
                     '可用状态': '可比' if sample else '缺少两期可比数据'})
    return {'rows': data, 'codes': sample, 'excluded': book.explain(codes, [(f, d) for f in (TOTAL_REVENUE, P) for d in SPEC.periods], sample)}


def pack_heat_groups(roots):
    groups, current, parents = [], [], []
    for root in roots:
        rows = [c['queries']['quadrant']['行业'] for c in root['children'] if c['queries']['quadrant']]
        if current and len(current) + len(rows) > SPEC.max_heat_rows:
            groups.append({'industries': current, 'parents': parents})
            current, parents = [], []
        while len(rows) > SPEC.max_heat_rows:
            groups.append({'industries': rows[:SPEC.max_heat_rows], 'parents': [root['identity']['sector_name']]})
            rows = rows[SPEC.max_heat_rows:]
        if rows:
            current.extend(rows); parents.append(root['identity']['sector_name'])
    if current:
        groups.append({'industries': current, 'parents': parents})
    flat = [x for g in groups for x in g['industries']]
    if len(flat) != len(set(flat)):
        raise ValueError('Repeated secondary name in grouped display')
    return groups


def select_cases(children):
    ordered = sorted(children, key=lambda c: (-abs(c['queries']['profit'].get('归母利润增减（亿元）') or 0), c['identity']['sector_code']))
    chosen = []
    rules = [('利润增加贡献', lambda c: (c['queries']['profit'].get('归母利润增减（亿元）') or 0) > 0),
             ('利润减少贡献', lambda c: (c['queries']['profit'].get('归母利润增减（亿元）') or 0) < 0),
             ('仍处亏损', lambda c: (c['queries']['profit'].get('归母利润（亿元）') or 0) < 0),
             ('增收但利润率下降', lambda c: c['queries']['quadrant'] and c['queries']['quadrant']['经营状态'] == STATES[1])]
    for reason, predicate in rules:
        eligible = [c for c in ordered if predicate(c) and c['identity']['sector_name'] not in [v['行业'] for v in chosen]]
        if eligible:
            chosen.append({'行业': eligible[0]['identity']['sector_name'], '入选原因': reason})
    for c in ordered:
        if len(chosen) >= SPEC.max_cases:
            break
        name = c['identity']['sector_name']
        if name not in [v['行业'] for v in chosen]:
            chosen.append({'行业': name, '入选原因': '利润增减绝对金额靠前'})
    return chosen


def inherited_sample():
    sample = OUTPUT_ROOT / SPEC.sample_run
    m = load(sample / 'evidence/artifact_manifest.json')['files']
    for rel in ('data.json', 'report.html'):
        if digest(sample / rel) != m[rel]:
            raise ValueError('Approved sample changed before expansion')
    return json.loads((sample / 'data.json').read_text())


def protect_history():
    """Bounded target hashes; do not rescan 1,046 unrelated historical files."""
    paths = []
    for run in (SPEC.source_run, SPEC.sample_run):
        base = OUTPUT_ROOT / run
        manifest = load(base / 'evidence/artifact_manifest.json')['files']
        for rel in ('report.html', 'data.json', 'evidence/artifact_manifest.json'):
            p = base / rel
            if not p.exists():
                continue
            if rel in manifest and digest(p) != manifest[rel]:
                raise ValueError('Historical report artifact changed')
            paths.append(p)
    acceptance = load(OUTPUT_ROOT / SPEC.source_run / 'evidence/formal_acceptance.json')
    for name, expected in acceptance['source_code_hashes'].items():
        if digest(name) != expected:
            raise ValueError('Core research implementation changed')
        paths.append(Path(name))
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def snapshot_for_current(roots, sample):
    nonfinancial = [r for r in roots if not r['identity']['financial']]
    children = [c for r in nonfinancial for c in r['children']]
    queries = {'history_comparison': sample['queries']['history_comparison']}
    def add(name, rows, definition):
        queries[name] = {'rows': rows, 'source': {
            'label': '[1] 当前行业财务' if not name.startswith('financial') else '[2] 金融通用财务',
            'scope': '2026年1—9月与2025年同期；10/30归属，11/1冻结财务',
            'files': ['calculations/groups.json'] if not name.startswith('financial') else ['冻结income两期白名单；本地financial_projection'],
            'filters': ['东财2025年末分类体系；固定10/30公司归属', '两期字段完整且符合已知可比边界'],
            'caveats': ['每项按自身共同有效公司计算，覆盖为已知收入覆盖；缺失不填0'],
            'metricDefinitions': [{'label': name, 'definition': definition, 'componentIds': [name]}]}}
    points = [r['queries']['quadrant'] for r in nonfinancial]
    if len(points) != 29 or any(r is None for r in points):
        raise ValueError('Expected all 29 approved primary quadrant points')
    # Preserve exactly the original query-row fields for the already reviewed plot.
    clean = [{k: v for k, v in r.items() if k != '所属一级行业'} for r in points]
    add('industry_quadrant', clean, '收入同比与扣非利润率变化；同一R/D公司金额先合计，坐标未舍入分区。')
    for kind in ('profit', 'quality', 'receivable', 'inventory', 'breadth', 'fixed', 'capex'):
        add('primary_' + kind, [r['queries'][kind] for r in nonfinancial], '当前两期联合字段公司范围；定义及精确来源见原计算口径10.11与逐行业审计。')
    for name, key, field, unit in (
        ('secondary_income', 'quadrant', '收入增长（%）', '%'),
        ('secondary_margin', 'quality', '扣非利润率变化（百分点）', '百分点'),
        ('secondary_cash', 'quality', '经营现金流率变化（百分点）', '百分点')):
        rows = []
        for c in children:
            row = c['queries'][key]
            if row is None:
                row = c['queries']['profit']
            meta = {k: v for k, v in row.items() if k in ('行业', '所属一级行业', '可比公司数', '候选公司数', '本期已知收入覆盖（%）', '上年已知收入覆盖（%）', '当期已知收入覆盖（%）')}
            rows.append(dict(meta, **{'指标': {'secondary_income': '收入同比（%）', 'secondary_margin': '利润率变化（百分点）', 'secondary_cash': '现金流率变化（百分点）'}[name], '数值': row.get(field), '单位': unit}))
        add(name, rows, '同一指标的全部124非金融二级采用统一、以0为中心的数值域；缺失和0分开。')
    add('secondary_profit', [c['queries']['profit'] for c in children], '二级归母利润增减；R/P两期同集，各一级子行业加总与一级核对。')
    add('secondary_cases', [dict(c['queries']['profit'], **{'入选原因': reason['入选原因']}) for reason in select_cases(children) for c in children if c['identity']['sector_name'] == reason['行业']], '案例按正负贡献、亏损、增收利润率下降及绝对金额规则选取；全貌不因此过滤。')
    finance = [v for r in roots if r['identity']['financial'] for v in r['finance_rows']]
    add('financial_current', finance, 'total_revenue营业总收入和归母，两期同一批金融公司；不使用非金融revenue。')
    status = []
    for root in roots:
        for child in root['children']:
            name = child['identity']['sector_name']
            if root['identity']['financial']:
                rr = next(r for r in root['finance_rows'] if r['行业'] == name)
                state = '金融单列；' + rr['可用状态']; n = rr['候选公司数']
            else:
                p = child['queries']['profit']; n = p['候选公司数']; state = '已展示' if child['queries']['quadrant'] else '缺少可比数据'
            status.append({'行业': name, '所属一级行业': root['identity']['sector_name'], '候选公司数': n, '可用状态': state})
    add('industry_status', status, '固定树128个二级全部列出可用状态；124非金融和4金融分别呈现。')
    heat = pack_heat_groups(nonfinancial)
    domains = {}
    for name in ('secondary_income', 'secondary_margin', 'secondary_cash'):
        values = [abs(r['数值']) for r in queries[name]['rows'] if r['数值'] is not None]
        bound = max(values) if values else 1
        domains[name] = [-bound, bound] if bound else [-1, 1]
    counts = {s: sum(r['经营状态'] == s for r in clean) for s in STATES}
    quality = queries['primary_quality']['rows']
    stats = {'counts': counts, 'revenue_up': sum(r['收入增长（%）'] > 0 for r in clean),
             'quality_joint_up': sum((r.get('扣非利润率变化（百分点）') or 0) > 0 and (r.get('经营现金流率变化（百分点）') or 0) > 0 for r in quality),
             'profit_delta': numeric(sum(D(str(r['归母利润增减（亿元）'])) for r in queries['primary_profit']['rows'])),
             'receivable_longer': sum((r.get('周转天数变化（天）') or 0) > 0 for r in queries['primary_receivable']['rows']),
             'inventory_longer': sum((r.get('周转天数变化（天）') or 0) > 0 for r in queries['primary_inventory']['rows']),
             'capex_positive': sum((r.get('现金流扣除资本开支（亿元）') or 0) >= 0 for r in queries['primary_capex']['rows'])}
    snapshot = dict(sample)
    snapshot.update(title='A股行业财务分析｜2026年前三季度', generatedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), buildStatus='updating', queries=queries)
    snapshot['study'] = dict(sample['study'], stage='current', counts=counts, stats=stats,
                             heatGroups=heat, heatDomains=domains, caseNames=[r['行业'] for r in queries['secondary_cases']['rows']],
                             colors={'blue': SPEC.blue, 'teal': SPEC.teal}, yearColors=dict(SPEC.year_colors))
    return snapshot


def validate_snapshot(snapshot, approved):
    forbidden = {'sample_id', '样本ID', '共同样本ID', '集合ID', 'ts_code', 'root', 'sector_code', 'row_id', 'codes'}
    for name, query in snapshot['queries'].items():
        for row in query['rows']:
            if forbidden & row.keys():
                raise ValueError('Internal field in reader projection: ' + name)
    q = snapshot['queries']
    if q['industry_quadrant']['rows'] != approved['queries']['industry_quadrant']['rows']:
        raise ValueError('Approved quadrant rows changed')
    if snapshot['id'] != approved['id'] or q['history_comparison'] != approved['queries']['history_comparison']:
        raise ValueError('Approved artifact identity/history query changed')
    if len(q['industry_status']['rows']) != 128 or len({r['行业'] for r in q['industry_status']['rows']}) != 128:
        raise ValueError('Secondary status coverage changed')
    for name in ('secondary_income', 'secondary_margin', 'secondary_cash', 'secondary_profit'):
        if len(q[name]['rows']) != 124:
            raise ValueError('Nonfinancial secondary display coverage changed')
    grouped = [name for group in snapshot['study']['heatGroups'] for name in group['industries']]
    if len(grouped) != 124 or len(set(grouped)) != 124:
        raise ValueError('Secondary heat groups omit or duplicate industries')


def prepare_current(output, resume=False):
    started = time.monotonic()
    protected = protect_history()
    prep = load(OUTPUT_ROOT / SPEC.preparation_run / 'evidence/preparation_baseline.json')
    key = f'reports/a_share_industry_prosperity_2026q3/{SPEC.source_run}/evidence/artifact_manifest.json'
    source = FrozenSource(OUTPUT_ROOT / SPEC.source_run, prep['before_sha256'][key])
    groups = source.json('calculations/groups.json')
    members = source.json('calculations/sample.json')
    quality = source.json('evidence/quality.json')
    if len(groups) != 31 or sum(len(g['children']) for g in groups) != 128:
        raise ValueError('Frozen industry tree shape changed')
    if len(members) != 5571 or len({r['ts_code'] for r in members}) != 5571:
        raise ValueError('Frozen current membership changed')
    finance_roots = {g['identity']['sector_code'] for g in groups if g['identity']['financial']}
    finance_members = [m for m in members if m['root'] in finance_roots]
    if any(m['curr_type'] != 'CNY' for m in finance_members):
        raise ValueError('Unverified financial currency')
    finance_records = source.income({r['ts_code'] for r in finance_members})
    book = Book({'income': finance_records}, noncomparable=quality.get('noncomparable_codes', {}))
    approved = inherited_sample()
    aggregate_size = sum((source.root / rel).stat().st_size for rel in source.used if not rel.startswith('inputs/'))
    if aggregate_size > SPEC.aggregate_bytes:
        raise ValueError('Aggregate input budget exceeded')
    fingerprint = dict(source.used, **{'approved_sample_data': digest(OUTPUT_ROOT / SPEC.sample_run / 'data.json'), 'projection_implementation': digest(Path(__file__))})
    run = PublicationRun(output, fingerprint, resume)
    atomic_json(run.path / 'evidence/history_before.json', protected)
    roots = []
    def make_group(group):
        meta = group['identity']; root_name = meta['sector_name']
        if not meta['financial']:
            result = current_projection(group, root_name)
            result['children'] = [current_projection(c, root_name) for c in group['children']]
            result['reconciliation'] = reconcile_parent(group)
            return result
        result = {'identity': meta, 'children': [], 'finance_rows': [], 'financial_audit': {}}
        root_members = [m for m in finance_members if m['root'] == meta['sector_code']]
        parent_codes = None; child_codes = []
        for obj in [group] + group['children']:
            identity = obj['identity']
            codes = [m['ts_code'] for m in root_members if identity['level'] == 1 or m['parent'] == identity['sector_code']]
            data = financial_projection(book, codes, identity, root_name)
            result['finance_rows'].extend(data['rows'])
            result['financial_audit'][identity['sector_code']] = data
            if identity['level'] == 1:
                parent_codes = set(data['codes'])
            else:
                result['children'].append({'identity': identity})
                child_codes.extend(data['codes'])
        if set(child_codes) != parent_codes or len(child_codes) != len(set(child_codes)):
            raise ValueError('Financial parent/child company sets differ')
        for year in ('2025', '2026'):
            for field in ('营业总收入（亿元）', '归母净利润（亿元）'):
                p = next(r[field] for r in result['finance_rows'] if r['年份'] == year and r['层级'] == '一级')
                values = [r[field] for r in result['finance_rows'] if r['年份'] == year and r['层级'] == '二级']
                if p is not None and abs(sum(D(str(v)) for v in values if v is not None) - D(str(p))) * MONEY > D(RESEARCH_SPEC.amount_tolerance):
                    raise ValueError('Financial parent/child display amounts do not reconcile')
        return result
    for group in groups:
        roots.append(run.unit(group['identity']['sector_code'], lambda group=group: make_group(group)))
    snapshot = snapshot_for_current(roots, approved)
    validate_snapshot(snapshot, approved)
    atomic_json(run.path / 'data.json', snapshot)
    atomic_json(run.path / 'evidence/source_manifest.json', {'files': source.used, 'aggregate_bytes': aggregate_size,
        'income_physical_bytes': sum((source.root / r).stat().st_size for r in source.used if r.startswith('inputs/')),
        'financial_projection_rows': len(finance_records), 'source_connections': 0})
    env = load(OUTPUT_ROOT / SPEC.sample_run / 'evidence/environment.json')
    atomic_json(run.path / 'evidence/environment.json', env)
    atomic_json(run.path / 'evidence/current_acceptance.json', {'primary_points': 29, 'secondary_nonfinancial': 124,
        'secondary_financial': 4, 'finance_records': len(finance_records), 'heat_groups': len(snapshot['study']['heatGroups']),
        'approved_quadrant_equal': True, 'parent_child_reconciliation': True, 'technical_fields_in_reader_rows': False,
        'peak_python_bytes': rss_bytes(), 'seconds': time.monotonic() - started, 'source_connections': 0,
        'historical_calculations_executed': False, 'forecast_or_score_executed': False})
    if protect_history() != protected:
        raise ValueError('Historical artifact changed while producing report')
    run.save(status='CURRENT_PROJECTED')
    run.check()
    print('CURRENT_PROJECTED', run.path, flush=True)


def top_company_names(metric, members):
    """Resolve the already selected company order; never select a new top three."""
    names = {}
    for member in members:
        code, name = member['ts_code'], member['name']
        if code in names or not isinstance(name, str) or not name.strip():
            raise ValueError('Duplicate or empty frozen company identity')
        names[code] = name.strip()
    codes = [item['code'] for item in metric['value']]
    if len(codes) > 3 or len(codes) != len(set(codes)) or any(code not in metric['codes'] for code in codes):
        raise ValueError('Invalid frozen top-three selection')
    if any(code not in names for code in codes):
        raise ValueError('Missing frozen top-three company name')
    return '、'.join(names[code] for code in codes)


def receivable_balance(group, root_name):
    values = [row for row in group['series'] if row['metric'] == 'accounts_receivable' and row['period'] == SPEC.periods[1]]
    if len(values) != 1:
        raise ValueError('Expected one frozen comparable receivable balance')
    row = values[0]
    current, previous = row['comparison_current'], row['comparison_previous']
    if (current is None) != (previous is None) or (row['comparison_n'] == 0) != (current is None):
        raise ValueError('Inconsistent comparable receivable balance')
    current = None if current is None else D(str(current))
    previous = None if previous is None else D(str(previous))
    delta = None if current is None else current - previous
    growth = None if previous is None or previous <= 0 else (current / previous - 1) * 100
    known = None if row['amount'] is None else D(str(row['amount']))
    coverage = None if known is None or known <= 0 or current is None else current / known * 100
    if coverage is not None and not 0 <= coverage <= 100:
        raise ValueError('Invalid known receivable coverage')
    return {'行业': group['identity']['sector_name'], '所属一级行业': root_name,
            '2025年9月末应收账款（亿元）': numeric(previous, MONEY), '2026年9月末应收账款（亿元）': numeric(current, MONEY),
            '应收账款增减（亿元）': numeric(delta, MONEY), '应收账款同比（%）': numeric(growth),
            '可比公司数': row['comparison_n'], '候选公司数': group['facts']['plots']['1']['candidate_n'],
            '本期已知应收余额覆盖（%）': numeric(coverage), '可用状态': '可比' if current is not None else '缺少两期可比数据'}


def reconcile_receivable(group):
    def current(obj):
        return next(row for row in obj['series'] if row['metric'] == 'accounts_receivable' and row['period'] == SPEC.periods[1])
    parent, children = current(group), [current(c) for c in group['children']]
    if sum(c['comparison_n'] for c in children) != parent['comparison_n']:
        raise ValueError('Receivable parent/child comparable counts differ')
    residuals = {}
    for field in ('comparison_current', 'comparison_previous'):
        values = [c[field] for c in children if c['comparison_n']]
        if parent['comparison_n'] and (parent[field] is None or any(v is None for v in values)):
            raise ValueError('Missing receivable parent/child amount')
        residual = sum((D(str(v)) for v in values), D(0)) - D(str(parent[field] or 0))
        if abs(residual) > D(RESEARCH_SPEC.amount_tolerance):
            raise ValueError('Receivable parent/child amounts differ')
        residuals[field] = residual
    return residuals


def revise_current(output, previous_output, resume=False):
    started = time.monotonic()
    previous_output = Path(previous_output).resolve()
    if previous_output.parent != OUTPUT_ROOT or not previous_output.name.startswith('narrative_') or previous_output == output:
        raise ValueError('Unsafe previous current report')
    protected = protect_history()
    previous = FrozenSource(previous_output)
    snapshot = json.loads(previous.verified('data.json').read_text())
    previous.verified('report.html')
    if snapshot['buildStatus'] != 'complete' or snapshot['study']['stage'] != 'current':
        raise ValueError('Previous current report must be complete')
    previous_units = [json.loads(previous.verified(f'units/{p.name}').read_text()) for p in sorted((previous_output/'units').glob('*.json'))]
    if len(previous_units) != 31:
        raise ValueError('Expected all 31 committed current units')
    prep = load(OUTPUT_ROOT / SPEC.preparation_run / 'evidence/preparation_baseline.json')
    key = f'reports/a_share_industry_prosperity_2026q3/{SPEC.source_run}/evidence/artifact_manifest.json'
    source = FrozenSource(OUTPUT_ROOT / SPEC.source_run, prep['before_sha256'][key])
    if sum(source.verified(name).stat().st_size for name in ('calculations/groups.json','calculations/sample.json')) > SPEC.aggregate_bytes:
        raise ValueError('Revision aggregate input budget exceeded')
    groups, members = source.json('calculations/groups.json'), source.json('calculations/sample.json')
    if len(members) != 5571 or len(groups) != 31:
        raise ValueError('Frozen scope changed')
    # Validate identity once before committing any revised unit.
    first = next(g for g in groups if not g['identity']['financial'])
    top_company_names(next(m for m in first['facts']['metrics'] if m['metric']=='prior_revenue_top3_parent_profit_contribution'), members)
    fingerprint = dict(source.used, previous_manifest=digest(previous_output/'evidence/artifact_manifest.json'),
                       previous_data=digest(previous_output/'data.json'), projection_implementation=digest(Path(__file__)))
    run = PublicationRun(output, fingerprint, resume)
    atomic_json(run.path/'evidence/history_before.json', protected)
    old_units = {r['identity']['sector_code']: r for r in previous_units}
    roots = []
    for group in groups:
        code = group['identity']['sector_code']
        def produce(group=group, code=code):
            result = json.loads(json.dumps(old_units[code]))
            if not group['identity']['financial']:
                metric = next(m for m in group['facts']['metrics'] if m['metric']=='prior_revenue_top3_parent_profit_contribution')
                result['queries']['profit']['前三大公司'] = top_company_names(metric, members)
                result['queries']['receivable_balance'] = receivable_balance(group, group['identity']['sector_name'])
                lookup = {c['identity']['sector_code']: c for c in group['children']}
                for child in result['children']:
                    child['queries']['receivable_balance'] = receivable_balance(lookup[child['identity']['sector_code']], group['identity']['sector_name'])
                result['receivable_reconciliation'] = reconcile_receivable(group)
            return result
        roots.append(run.unit(code, produce))
    nonfinancial = [r for r in roots if not r['identity']['financial']]
    profits = {r['identity']['sector_name']: r['queries']['profit'] for r in nonfinancial}
    for row in snapshot['queries']['primary_profit']['rows']:
        row['前三大公司'] = profits[row['行业']]['前三大公司']
    for query_id, rows in (
        ('primary_receivable_balance', [r['queries']['receivable_balance'] for r in nonfinancial]),
        ('secondary_receivable_balance', [c['queries']['receivable_balance'] for r in nonfinancial for c in r['children']])):
        snapshot['queries'][query_id] = {'rows': rows, 'source': {
            'label': '应收账款期末余额同期比较', 'scope': '2026-09-30与2025-09-30；两期应收均有效的同一批公司；非金融',
            'files': ['formal_20261101_01/calculations/groups.json；series.accounts_receivable'],
            'metricDefinitions': [{'label': '应收账款变动', 'definition': '期末余额先按两期共同公司分别合计；增减额=本期−上年同期，亿元；同比=本期/上年同期−1，上年非正数时不计算。'}],
            'caveats': ['本项只要求两期应收均有效，与收入/周转天数的公司范围可能不同；缺失不填0；金融单列不做该专项。']}}
    snapshot['queries']['primary_profit']['source']['metricDefinitions'].append({'label':'前三大公司','definition':'按冻结的2025年前三季营业收入入选名单，依原顺序解析冻结公司简称；不按本期重新排名。'})
    original = json.loads((previous_output/'data.json').read_text())
    for query_id, query in original['queries'].items():
        actual = snapshot['queries'][query_id]
        if query_id == 'primary_profit':
            stripped = [{k:v for k,v in row.items() if k!='前三大公司'} for row in actual['rows']]
            if stripped != query['rows']: raise ValueError('Existing profit values changed')
        elif actual != query:
            raise ValueError('Existing reviewed query changed: '+query_id)
    validate_snapshot(snapshot, inherited_sample())
    for query_id, count in (('primary_receivable_balance',29),('secondary_receivable_balance',124)):
        rows = snapshot['queries'][query_id]['rows']
        if len(rows) != count or len({r['行业'] for r in rows}) != count: raise ValueError('Receivable coverage changed')
    snapshot['buildStatus']='updating'
    atomic_json(run.path/'data.json', snapshot)
    atomic_json(run.path/'evidence/environment.json', json.loads(previous.verified('evidence/environment.json').read_text()))
    atomic_json(run.path/'evidence/source_manifest.json', {'files':source.used,'previous_run':previous_output.name,
        'previous_files':previous.used,'aggregate_bytes':sum((source.root/r).stat().st_size for r in source.used),
        'source_connections':0,'income_physical_bytes':0,'financial_projection_rows':0})
    atomic_json(run.path/'evidence/revision_acceptance.json', {'previous_run':previous_output.name,'old_queries_unchanged_except_company_names':True,
        'primary_receivable_rows':29,'secondary_receivable_rows':124,'receivable_parent_child_amounts_and_counts_equal':True,
        'peak_python_bytes':rss_bytes(),'seconds':time.monotonic()-started,'source_connections':0,'recomputed_old_metrics':False})
    if protect_history() != protected: raise ValueError('Protected history changed')
    run.save(status='CURRENT_REVISED');run.check()
    print('CURRENT_REVISED',run.path,flush=True)


def build(output, complete=False):
    output = Path(output).resolve()
    state = load(output / 'run.json')
    spec = {'current': SPEC, 'history': HISTORY_SPEC, 'forecast': FORECAST_SPEC}.get(state['stage'])
    if spec is None or state['spec'] != json.loads(json.dumps(asdict(spec))):
        raise ValueError('Wrong current report specification')
    before = load(output / 'evidence/history_before.json')
    if protect_history() != before:
        raise ValueError('Protected historical artifact changed')
    source_manifest = load(output / 'evidence/source_manifest.json')
    for rel, sha in source_manifest['files'].items():
        if digest(OUTPUT_ROOT / SPEC.source_run / rel) != sha:
            raise ValueError('Frozen report source changed before build')
    if source_manifest.get('previous_run'):
        previous_root = safe_relative(OUTPUT_ROOT, source_manifest['previous_run'])
        for rel, sha in source_manifest['previous_files'].items():
            if digest(safe_relative(previous_root, rel)) != sha:
                raise ValueError('Previous report artifact changed before build')
    env = load(output / 'evidence/environment.json')
    app, node, plugin = Path(env['app']), env['node'], Path(env['plugin'])
    if not app.is_dir() or app.parent != Path('/private/tmp') or not app.name.startswith('industry_financial_chapter_samples_'):
        raise ValueError('Approved author project unavailable')
    builds = int(state.get('builds', 0))
    if builds >= spec.max_builds:
        raise ValueError('Current report build budget exhausted')
    state['builds'] = builds + 1
    atomic_json(output / 'run.json', state)
    snapshot = json.loads((output / 'data.json').read_text())
    validate_snapshot(snapshot, inherited_sample())
    # One reviewed query can support several chart/prose IDs. Its definition
    # applies to each of those consumers rather than only the query-name ID.
    for query_id, query in snapshot['queries'].items():
        if query_id == 'history_comparison':
            continue
        for definition in query['source'].get('metricDefinitions', []):
            definition.pop('componentIds', None)
        if query_id == 'financial_current':
            query['source']['caveats'] = ['两期营业总收入和归母利润同一批金融公司；覆盖以已知营业总收入计算；缺失不填0。']
    if load(app / 'src/data.json')['id'] != snapshot['id']:
        raise ValueError('Author project identity changed')
    snapshot['buildStatus'] = 'complete' if complete else 'updating'
    atomic_json(output / 'data.json', snapshot); atomic_json(app / 'src/data.json', snapshot)
    for name in ('ReportContent.jsx', 'report.css', 'HistoryChapters.jsx', 'ForecastChapters.jsx'):
        shutil.copyfile(Path(__file__).parent / 'report_app' / name, app / 'src/content/report' / name)
    cli = plugin / 'output_formats/html/scripts/data-app.mjs'
    started = time.monotonic()
    commands = ([node, str(cli), 'build', '--project-dir', str(app), '--separate-data'],
                [node, str(cli), 'export-html', '--project-dir', str(app), '--output', str(app / '.data-app-offline/exports/current-financial.html')])
    receipts = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=spec.build_seconds)
        if result.returncode:
            raise RuntimeError(result.stderr[-3000:])
        receipts.append(result.stdout)
    (output / 'evidence' / f'build_{builds+1}.txt').write_text('\n'.join(receipts))
    export = app / '.data-app-offline/exports/current-financial.html'
    temporary = output / 'report.html.part'; shutil.copyfile(export, temporary); temporary.replace(output / 'report.html')
    atomic_json(output / 'evidence/build_receipt.json', {'round': builds + 1, 'seconds': time.monotonic() - started,
        'report_sha256': digest(output / 'report.html'), 'complete_current_batch': complete, 'stage': spec.stage,
        'app_id': snapshot['id'], 'no_installations': True})
    print(app / 'dist', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--complete', action='store_true')
    parser.add_argument('--revise-from', type=Path)
    parser.add_argument('--history-from', type=Path)
    parser.add_argument('--forecast-from', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != OUTPUT_ROOT or not output.name.startswith('narrative_'):
        raise ValueError('Unsafe current report output')
    if args.complete and not args.build:
        raise ValueError('--complete requires --build')
    if args.forecast_from and (args.build or args.revise_from or args.history_from):
        raise ValueError('--forecast-from prepares a new final stage; build separately')
    if args.history_from and (args.build or args.revise_from):
        raise ValueError('--history-from prepares a new stage; build it separately')
    if args.build and args.revise_from:
        raise ValueError('--revise-from prepares a new revision; build it separately')
    if args.build:
        build(output, args.complete)
    elif args.forecast_from:
        from .forecast_publication import prepare_forecast
        prepare_forecast(output, args.forecast_from, args.resume)
    elif args.history_from:
        from .history_publication import prepare_history
        prepare_history(output, args.history_from, args.resume)
    elif args.revise_from:
        revise_current(output, args.revise_from, args.resume)
    else:
        prepare_current(output, args.resume)


if __name__ == '__main__':
    main()
