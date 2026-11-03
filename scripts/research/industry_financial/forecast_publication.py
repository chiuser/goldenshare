"""Final report projection of frozen forecasts and rankings; never fits or scores."""
from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import time

from .publication import (SPEC, FORECAST_SPEC as FS, FrozenSource, PublicationRun,
                          MONEY, numeric, protect_history, inherited_sample,
                          validate_snapshot, rss_bytes)
from .history_publication import profit_change
from .forecast import SUM_KEYS
from .spec import SPEC as RS
from .storage import OUTPUT_ROOT, atomic_json, digest, load

LABELS={'P':'归母净利润','D':'扣非净利润','C':'经营现金流'}
RAW_NAMES=('预测扣非盈利收益率（%）','预测收入增长（%）','预测扣非利润率变化（百分点）',
           '经营现金流率（%）','扣非TTM净资产收益率（%）','资产负债率（%）','模型内下行幅度（%）')
DIMENSIONS=('估值得分','前景得分','质量得分','风险得分')
REASONS={'nonpositive_forecast_deducted_profit':'全年预测扣非净利润非正',
 'incomplete_metric':'评分指标不完整','fewer_than_5_companies':'可比公司不足5家',
 'coverage_current_below_90pct_or_unknown':'本期已知收入覆盖不足90%或未知',
 'coverage_previous_below_90pct_or_unknown':'上期已知收入覆盖不足90%或未知',
 'both_revenue_periods_unknown':'存在两期收入均未知的公司',
 'nonpositive_or_missing_denominator':'净资产、市值或收入分母无效',
 'invalid_quote':'报价或股本无效','deducted_attribution_unverified':'扣非归属口径未通过核验',
 'financial_industry_observation_only':'金融行业单列，不参加评分',
 'no_valid_child_forecast':'无可用细分行业预测','incomplete_model_history':'模型所需历史不完整',
 'nonpositive_revenue_model_input':'模型收入分母非正'}


def near(a,b,tolerance=D(RS.amount_tolerance)):
    return abs(D(str(a))-D(str(b)))<=tolerance


def validate_model(f):
    if not f['available']:
        return
    if f['n']!=len(f['codes']) or len(f['codes'])!=len(set(f['codes'])):
        raise ValueError('Frozen model company count/uniqueness mismatch')
    for prefix in ('R','X'):
        for suffix in ('base','low','high'):
            if not near(f[prefix+'_'+suffix],D(f[prefix+'9'])+D(f[prefix+'4_'+suffix])):
                raise ValueError('Frozen forecast annual identity mismatch')
        if not D(f[prefix+'_low'])<=D(f[prefix+'_base'])<=D(f[prefix+'_high']):
            raise ValueError('Frozen forecast scenario excludes base')
    if not near(f['R4_base'],(D(f['income_method_A'])+D(f['income_method_B']))/2):
        raise ValueError('Frozen revenue model is not approved 50/50')
    if 'season_weight' in f and D(f['season_weight'])!=D(RS.revenue_season_weight):
        raise ValueError('Frozen revenue weight changed')
    if 'quarter_margin_base' in f and not near(f['X4_base'],D(f['R4_base'])*D(f['quarter_margin_base'])):
        raise ValueError('Frozen forecast margin product mismatch')


def model_row(f,identity,root_name):
    validate_model(f)
    row={'行业':identity['sector_name'],'所属一级行业':root_name,'层级':str(identity['level']),
         '指标':LABELS[f['kind']],'可比公司数':f['n'],'候选公司数':f['candidate_n'],
         '本期已知收入覆盖（%）':numeric(f['coverage_current']['value'],D('.01')),
         '上期已知收入覆盖（%）':numeric(f['coverage_previous']['value'],D('.01'))}
    mapping={'2025全年实际（亿元）':'X25','前三季实际（亿元）':'X9','第四季度基准预测（亿元）':'X4_base',
       '全年基准预测（亿元）':'X_base','全年低情景（亿元）':'X_low','全年高情景（亿元）':'X_high',
       '第四季度低情景（亿元）':'X4_low','第四季度高情景（亿元）':'X4_high',
       '同集2025全年收入（亿元）':'R25','同集前三季收入（亿元）':'R9',
       '同集全年收入预测（亿元）':'R_base','同集全年收入低情景（亿元）':'R_low','同集全年收入高情景（亿元）':'R_high'}
    for label,key in mapping.items():row[label]=numeric(f.get(key),MONEY)
    rg=pg=None;state='无可用模型结果'
    if f['available']:
        rg=None if D(f['R25'])<=0 else (D(f['R_base'])/D(f['R25'])-1)*100
        if f['kind']!='C':pg,state=profit_change(D(f['X_base']),D(f['X25']),D(f['R25']))
        else:state='现金流预测单列'
    row.update({'全年收入增长（%）':numeric(rg),'全年利润增长（%）':numeric(pg),'利润变化状态':state,
        '全年增减（亿元）':numeric(D(f['X_base'])-D(f['X25']),MONEY) if f['available'] else None,
        '预测状态':'有模型结果' if f['available'] else REASONS.get(f.get('reason'),'缺少可用模型结果')})
    covs=[f[k].get('value') for k in ('coverage_current','coverage_previous')]
    hints=[]
    if f['n']<RS.min_companies:hints.append('可比公司不足5家')
    if any(c is None or D(c)<D(RS.min_coverage) for c in covs):hints.append('已知收入覆盖不足90%或未知')
    row['覆盖提示']='；'.join(hints) or '两期已知收入覆盖不低于90%'
    return row


def reconcile_models(group):
    result={}
    if group['identity']['financial']:return result
    for kind in LABELS:
        parent=group['forecasts'][kind];validate_model(parent)
        children=[c['forecasts'][kind] for c in group['children'] if c['forecasts'][kind]['available']]
        codes=[code for c in children for code in c['codes']]
        if len(codes)!=len(set(codes)) or set(codes)!=set(parent['codes']):
            raise ValueError('Frozen forecast parent/child company sets differ')
        for field in SUM_KEYS:
            residual=sum((D(c[field]) for c in children),D(0))-D(parent[field])
            if abs(residual)>D(RS.amount_tolerance):raise ValueError('Frozen forecast parent/child amount mismatch')
            result[kind+'_'+field]=residual
    return result


def score_row(r,root_name):
    qualified=bool(r.get('eligible') and r.get('score_available'))
    if r.get('eligible') and not qualified:raise ValueError('Frozen eligible industry missing score')
    raw=r.get('raw') or [None]*7;dims=r.get('dimensions') or [None]*4
    if qualified:
        if len(raw)!=7 or len(dims)!=4 or any(v is None for v in raw+dims):
            raise ValueError('Incomplete frozen score cannot be reweighted')
        points=list(map(D,dims));expected=sum((D(w)*v for w,v in zip(RS.dimension_weights,points)),D(0))
        if any(not 0<=v<=100 for v in points) or not near(r['total_score'],expected,D('1e-20')):
            raise ValueError('Frozen four-dimension score mismatch')
        if r['rank']<1:raise ValueError('Invalid frozen rank')
        # Only identities supported by this frozen record; never read cash/BS again.
        formulas={0:D(r['X_base'])/D(r['market_value_yuan']),1:D(r['R_base'])/D(r['R25'])-1,
                  2:D(r['X_base'])/D(r['R_base'])-D(r['X25'])/D(r['R25']),
                  4:D(r['deducted_ttm'])/D(r['average_parent_equity']),
                  6:(D(r['X_base'])-D(r['X_low']))/D(r['X_base'])}
        if any(not near(raw[i],v,D('1e-20')) for i,v in formulas.items()):
            raise ValueError('Frozen score metrics or company-scope identity mismatch')
    failures=r.get('qualification_failures',[])
    if any(x not in REASONS for x in failures):raise ValueError('Untranslated frozen qualification reason')
    reason='合格' if qualified else '；'.join(REASONS[x] for x in failures)
    if r.get('financial'):reason='金融行业单列，不参加预测或评分'
    row={'行业':r['sector_name'],'所属一级行业':root_name,'层级':str(r['level']),
         '评分状态':'合格' if qualified else '未评分','未评分原因':None if qualified else reason,
         '名次':r.get('rank') if qualified else None,'综合得分':numeric(r.get('total_score')) if qualified else None,
         '可比公司数':r['n'],'候选公司数':r['candidate_n'],
         '本期已知收入覆盖（%）':numeric(r['coverage_current']['value'],D('.01')),
         '上期已知收入覆盖（%）':numeric(r['coverage_previous']['value'],D('.01')),
         '同集市值（亿元）':numeric(r.get('market_value_yuan'),MONEY),
         '评分同集全年收入预测（亿元）':numeric(r.get('R_base'),MONEY),
         '评分同集全年扣非预测（亿元）':numeric(r.get('X_base'),MONEY)}
    row.update({k:numeric(v) if qualified else None for k,v in zip(DIMENSIONS,dims)})
    row.update({k:numeric(v,D('.01')) for k,v in zip(RAW_NAMES,raw)})
    return row


def cutoff_ties(items,limit):
    """Items carry exact Decimal values and a stable source code only in audit."""
    ordered=sorted((x for x in items if x['value'] is not None),key=lambda x:(-D(x['value']),x['code']))
    if len(ordered)<=limit:return ordered
    cut=D(ordered[limit-1]['value'])
    return [x for x in ordered if D(x['value'])>=cut]


def sensitivity_rows(ranks,source,root_names):
    qualified=[r for r in ranks if r.get('score_available')]
    expected={r['sector_code'] for r in qualified};weights=source['weight_sensitivity']
    if not weights['available'] or weights['combinations']!=85 or {r['sector_code'] for r in weights['rows']}!=expected:
        raise ValueError('Frozen weight sensitivity candidate set changed')
    lookup={r['sector_code']:r for r in weights['rows']};models=source['model_sensitivity']
    alternatives={}
    for key in ('0.25','0.75'):
        m=models[key]
        if not m.get('comparable_ranking') or not m.get('peer_set_unchanged') or {r['sector_code'] for r in m['rows']}!=expected:
            raise ValueError('Frozen model alternative candidate set changed')
        alternatives[key]={r['sector_code']:r for r in m['rows']}
    head=models['exclude_top3']
    if head.get('comparable_ranking'):
        raise ValueError('Unexpected head-company ranking comparability; design must be reviewed')
    failed=set(head['failed_original_candidates'])
    if not failed<=expected:raise ValueError('Head-company failure outside original candidates')
    removed={r['sector_code']:r for r in head['original_metrics']}
    wr,mr,hr=[],[],[]
    for base in qualified:
        code=base['sector_code'];w=lookup[code]
        if not w['min_rank']<=base['rank']<=w['max_rank'] or not 0<=w['top20_combinations']<=85:
            raise ValueError('Invalid weight sensitivity ranks/counts')
        if not near(w['top20_fraction'],D(w['top20_combinations'])/85,D('1e-20')):
            raise ValueError('Weight combination proportion mismatch')
        common={'行业':base['sector_name'],'所属一级行业':root_names[base['root']], '层级':str(base['level'])}
        wr.append(dict(common,**{'基准名次':base['rank'],'最好名次':w['min_rank'],'最差名次':w['max_rank'],
            '前20%组合数':w['top20_combinations'],'组合总数':85,'前20%组合占比（%）':numeric(w['top20_fraction'],D('.01'))}))
        mr.append(dict(common,**{'季节法25%名次':alternatives['0.25'][code]['rank'],
            '季节法50%名次':base['rank'],'季节法75%名次':alternatives['0.75'][code]['rank']}))
        alt=removed[code]
        hr.append(dict(common,**{'原评分资格':'合格','剔除头部后资格':'失效' if code in failed else '保留',
            '整体排名可比性':'不可比','替代名次':None,
            '剔除后本期已知收入覆盖（%）':numeric(alt['coverage_current']['value'],D('.01')),
            '剔除后上期已知收入覆盖（%）':numeric(alt['coverage_previous']['value'],D('.01')),
            '原因':'；'.join(REASONS[x] for x in alt.get('qualification_failures',[]))}))
    return wr,mr,hr


def prepare_forecast(output,previous_output,resume=False):
    started=time.monotonic();previous_output=Path(previous_output).resolve()
    if previous_output.parent!=OUTPUT_ROOT or not previous_output.name.startswith('narrative_') or previous_output==output:
        raise ValueError('Unsafe previous final report')
    protected=protect_history();previous=FrozenSource(previous_output)
    old=json.loads(previous.verified('data.json').read_text());previous.verified('report.html')
    env=json.loads(previous.verified('evidence/environment.json').read_text())
    if old['buildStatus']!='complete' or old['study']['stage']!='history':raise ValueError('Final stage requires completed history')
    prep=load(OUTPUT_ROOT/SPEC.preparation_run/'evidence/preparation_baseline.json')
    key=f'reports/a_share_industry_prosperity_2026q3/{SPEC.source_run}/evidence/artifact_manifest.json'
    source=FrozenSource(OUTPUT_ROOT/SPEC.source_run,prep['before_sha256'][key])
    files=('calculations/groups.json','calculations/ranking.json','calculations/sensitivity.json')
    size=sum(source.verified(f).stat().st_size for f in files)
    if size>FS.aggregate_bytes:raise ValueError('Final stage input budget exceeded')
    groups,ranks,sensitivity=[source.json(f) for f in files]
    if len(groups)!=31 or sum(len(g['children']) for g in groups)!=128:raise ValueError('Frozen industry tree changed')
    for level,count in (('1',24),('2',89)):
        if sum(bool(r.get('score_available')) for r in ranks[level])!=count:raise ValueError('Frozen qualification counts changed')
    root_names={g['identity']['sector_code']:g['identity']['sector_name'] for g in groups}
    all_identities={o['identity']['sector_code']:o['identity'] for g in groups for o in [g]+g['children']}
    if len(all_identities)!=159:raise ValueError('Duplicate frozen industry identity')
    ranked={r['sector_code']:r for level in ranks.values() for r in level}
    if set(ranked)!=set(all_identities):raise ValueError('Ranking industry coverage changed')
    sens={level:sensitivity_rows(ranks[level],sensitivity[level],root_names) for level in ('1','2')}
    fingerprint=dict(source.used,previous_manifest=previous.used['evidence/artifact_manifest.json'],
        previous_data=previous.used['data.json'],publication_implementation=digest(Path(__file__).with_name('publication.py')),
        forecast_projection_implementation=digest(__file__))
    run=PublicationRun(output,fingerprint,resume,spec=FS);atomic_json(run.path/'evidence/history_before.json',protected)
    units=[]
    for group in groups:
        def produce(group=group):
            meta=group['identity'];root_name=meta['sector_name'];objects=[group]+group['children']
            forecasts=[];values=[];audit={}
            for obj in objects:
                identity=obj['identity'];code=identity['sector_code'];rank=ranked[code]
                if rank['sector_name']!=identity['sector_name'] or rank['financial']!=identity['financial']:
                    raise ValueError('Frozen score identity mismatch')
                values.append(score_row(rank,root_name))
                if identity['financial']:continue
                for kind,f in obj['forecasts'].items():
                    if kind!=f['kind']:raise ValueError('Frozen forecast kind mismatch')
                    forecasts.append(model_row(f,identity,root_name))
                    audit[code+'_'+kind]={'codes':f['codes'],'n':f['n'],'sample_id':f['sample_id'],
                        'exact':{k:f.get(k) for k in SUM_KEYS}}
            return {'identity':meta,'forecasts':forecasts,'values':values,'audit':audit,'reconciliation':reconcile_models(group)}
        units.append(run.unit(group['identity']['sector_code'],produce))
    snapshot=deepcopy(old);queries=snapshot['queries']
    for level in ('1','2'):
        def add(name,rows,label,definition,files):
            queries[name]={'rows':rows,'source':{'label':label,'scope':'2026全年条件预测；财务2026-11-01冻结，公司归属及估值2026-10-30；东财2025年末体系',
                'files':files,'filters':['原公司范围、可比排除、缺报与扣非历史版本处理保留'],
                'metricDefinitions':[{'label':label,'definition':definition}],
                'caveats':['预测沿2024/2025两年Q4季节规律；情景范围没有赋予发生概率。','P、D、C及评分各用自己的可比公司，金额与比率不跨范围拼接。']}}
        add('forecast_'+level,[r for u in units for r in u['forecasts'] if r['层级']==level], '全年收入、归母、扣非与现金流预测',
            'Q4收入：两年季节法与上年Q4按最新Q3同比外推各50%；利润率按已确认季节变化。全年=9M实际+Q4预测，先二级计算再向一级加总。正常利润同比要求基期正、本期非负及基期利润率≥0.1%；其余以状态和金额展示。覆盖提示不是重新筛选。',['formal_20261101_01/calculations/groups.json'])
        by_name={r['行业']:r for u in units for r in u['values'] if r['层级']==level}
        add('value_'+level,[by_name[r['sector_name']] for r in ranks[level]],'投资价值综合比较',
            '沿冻结同层级原资格公司、原分数及精确并列。估值/前景/质量/风险各25%。七项为预测扣非盈利收益率、预测收入增长、扣非利润率变化、现金流率、扣非TTM净资产收益率、资产负债率与模型内下行幅度；后两项低为好。所有原值只取本评分行同一批公司，市值已是元，不再乘10000。',['formal_20261101_01/calculations/ranking.json'])
        wr,mr,hr=sens[level]
        add('weights_'+level,wr,'权重敏感性', '原四维权重15%—35%且合计100%的85组组合；不改变原候选。名次越小越靠前；前20%组合占比是模型组合频次，不是上涨概率。',['formal_20261101_01/calculations/sensitivity.json'])
        add('model_weights_'+level,mr,'收入估计方法敏感性','分别沿用季节法25%、50%、75%的冻结排名；同一完整候选组，不因失效删行业重排。',['formal_20261101_01/calculations/sensitivity.json'])
        add('head_companies_'+level,hr,'剔除头部公司后的资格变化','按冻结2025全年收入前三公司情形；原评分候选全体不再满足完整比较条件，所以不提供替代名次。一级剔所属一级前三，二级剔所属二级前三；覆盖仍以原行业为分母。',['formal_20261101_01/calculations/sensitivity.json'])
    # Summary reuses the approved three-year amounts, not the forecast cohorts.
    history=old['queries']['history_comparison']['rows'];overall=[r for r in history if r['行业']=='非金融整体'];summary=[]
    for year in ('2025','2026'):
        a=next(r for r in overall if r['年份']==str(int(year)-1));b=next(r for r in overall if r['年份']==year)
        for label,field in (('营业收入','收入（亿元）'),('归母净利润','归母净利润（亿元）')):
            summary.append({'指标':label,'年份':year,'同比增长（%）':float((D(str(b[field]))/D(str(a[field]))-1)*100),'可比公司数':b['可比公司数']})
    queries['summary_growth']={'rows':summary,'source':deepcopy(old['queries']['history_comparison']['source'])}
    queries['summary_growth']['source']['metricDefinitions']=[{'label':'总结同期增长','definition':'沿已确认5275家非金融公司三年前三季金额，分别计算2025/2026同期增长；不改变历史查询，不混用季度或模型公司范围。'}]
    selected={}
    for level,limit in ((1,FS.primary_top),(2,FS.secondary_top)):
        objects=groups if level==1 else [c for g in groups for c in g['children']]
        for measure in ('income','profit'):
            candidates=[]
            for obj in objects:
                if obj['identity']['financial']:continue
                f=obj['forecasts']['P'];v=None
                if measure=='income' and D(f['R25'])>0:v=(D(f['R_base'])/D(f['R25'])-1)*100
                elif measure=='profit':v=profit_change(D(f['X_base']),D(f['X25']),D(f['R25']))[0]
                candidates.append({'name':obj['identity']['sector_name'],'code':obj['identity']['sector_code'],'value':v})
            selected[str(level)+'_'+measure]=[x['name'] for x in cutoff_ties(candidates,limit)]
    snapshot['study']['stage']='forecast';snapshot['study']['forecast']={'tops':selected,'primaryTop':FS.primary_top,'secondaryTop':FS.secondary_top,
        'predictionColor':FS.prediction_color,'rawNames':list(RAW_NAMES),'dimensions':list(DIMENSIONS)}
    snapshot['buildStatus']='updating'
    if any(snapshot['queries'][k]!=v for k,v in old['queries'].items()):raise ValueError('Accepted earlier query changed')
    validate_snapshot(snapshot,inherited_sample())
    for level,n in (('1',29),('2',124)):
        if len(queries['forecast_'+level]['rows'])!=n*3:raise ValueError('Forecast coverage changed')
    atomic_json(run.path/'data.json',snapshot);atomic_json(run.path/'evidence/environment.json',env)
    atomic_json(run.path/'evidence/source_manifest.json',{'files':source.used,'previous_run':previous_output.name,
        'previous_files':previous.used,'aggregate_bytes':size,'source_connections':0,'income_physical_bytes':0})
    atomic_json(run.path/'evidence/forecast_acceptance.json',{'old_queries_unchanged':True,'model_identities_and_parent_sums_valid':True,
        'eligible_primary':24,'eligible_secondary':89,'weight_combinations':85,'source_connections':0,
        'models_or_scores_recomputed':False,'income_or_valuation_scanned':False,'peak_python_bytes':rss_bytes(),
        'projection_seconds':time.monotonic()-started,'query_rows':{k:len(v['rows']) for k,v in queries.items() if k not in old['queries']}})
    if protect_history()!=protected:raise ValueError('Protected historical artifact changed')
    run.save(status='FORECAST_PROJECTED');run.check();print('FORECAST_PROJECTED',run.path,flush=True)
