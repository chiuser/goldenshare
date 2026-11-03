"""Reviewed report snapshot and CSVs, sharing frozen company sets and Decimal facts."""
from decimal import Decimal as D
from pathlib import Path
import csv
import json
import shutil
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from .spec import SPEC
from .storage import atomic_json,load,digest
from .metrics import Book,R,P,DED,C,descriptor

YEARS=('2024-09-30','2025-09-30','2026-09-30')


def number(value,scale=1):return None if value is None else float(D(value)/D(scale))
def formatted(value,scale=1,suffix=''):
    return 'NA' if value is None else format(D(value)/D(scale),',.2f')+suffix

def write_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)


def write_snapshot(store):
    groups=load(store.path/'calculations/groups.json');ranks=load(store.path/'calculations/ranking.json')
    samples=load(store.path/'calculations/sample.json');queries={}
    def query(name,rows,definition,files):
        queries[name]={'rows':rows,'source':{'label':'Prod冻结输入与本地计算','provider':'Goldenshare Prod','files':files,
            'filters':['2024Q1—2026Q3，固定5571候选','东财2025年末体系；2026-10-30归属和价格'],
            'caveats':['财报为提取时最新修订；非原子跨表快照','NA不补零，历史Q4扣非冲突按原规则排除相关预测'],
            'scope':'2024Q1—2026Q3；10/30当前候选，固定东财分类体系与10/30归属/价格；最新修订财务',
            'metricDefinitions':[{'label':name,'definition':definition,'componentIds':[name]}],
            'evidenceFlow':[{'title':'冻结输入','detail':'按已批准的5571候选和11报告期取白名单字段；实际SQL及指纹见evidence/query_plan.json与source_check.json。'},
                            {'title':'计算','detail':'metrics.py按共同公司做同比和季度差分；forecast.py二级金额向上加总；ranking.py按四维七项固定权重。'}]},
            'methods':[{'language':'text','code':definition}]}
        index=1 if name.startswith('three_year') else 5 if name=='financial_observations' else 3 if name.startswith(('rank_','forecast_')) or name.endswith('sensitivity') or name.endswith(('chart5','chart6')) else 4 if name=='quality_exclusions' else 2
        queries[name]['source']['label']={1:'[1] 三年固定面板',2:'[2] 行业财务事实',3:'[3] 条件预测与评分',4:'[4] 历史扣非冲突',5:'[5] 金融通用事实'}[index]
        component_ids={'three_year_totals':['three-year-totals','report-summary'],'three_year_panel':['three-year-industries'],
            'sector_facts':['current-sector-facts','report-summary','report-discussion'],'history_1':['industry-history'],
            'financial_observations':['financial-observations'],'quality_exclusions':['quality-exclusions','report-summary'],
            'rank_1':['ranking-1','ranking-raw-1','report-summary'],'rank_2':['ranking-2','ranking-raw-2'],
            'forecast_1':['forecast-1'],'forecast_2':['forecast-2'],'weight_sensitivity':['weight-sensitivity'],
            'model_sensitivity':['model-sensitivity']}
        queries[name]['source']['metricDefinitions'][0]['componentIds']=component_ids.get(name,[name,name+':values'])
    panel=[];root_table=[];financial=[];losses=[];overall={d:{'revenue':D(0),'parent_profit':D(0),'n':0} for d in YEARS}
    for group in groups:
        store.check();meta=group['identity'];codes=[s['ts_code'] for s in samples if s['root']==meta['sector_code']]
        if meta['financial']:
            for metric in ('parent_profit','deducted_profit','cashflow'):
                for row in group['series']:
                    if row['metric']==metric and row['period'] in YEARS:
                        financial.append({'行业':meta['sector_name'],'报告期':row['period'],'指标':{'parent_profit':'归母净利润','deducted_profit':'扣非净利润','cashflow':'经营现金流'}[metric],'金额亿元':number(row['amount'],100000000),'有效公司数':row['n'],'集合ID':row['sample_id']})
            continue
        book=Book.from_run(store,codes)
        common=book.common(codes,[(f,d) for f in (R,P) for d in YEARS])
        for date in YEARS:
            revenue=book.total(R,common,date);profit=book.total(P,common,date)
            panel.append({'行业':meta['sector_name'],'root':meta['sector_code'],'报告期':date,'收入亿元':number(revenue,100000000),'归母利润亿元':number(profit,100000000),'共同公司数':len(common),'候选数':len(codes),'集合ID':descriptor(book,common,codes)['sample_id']})
            if revenue is not None:overall[date]['revenue']+=revenue
            if profit is not None:overall[date]['parent_profit']+=profit
            overall[date]['n']+=len(common)
        plot=group['facts']['plots']['1'];quality=group['facts']['plots']['3'];breadth=group['facts']['plots']['4'];metrics={r['metric']:r for r in group['facts']['metrics']}
        root_table.append({'行业':meta['sector_name'],'行业代码':meta['sector_code'],'候选数':len(codes),'同比共同公司数':plot['n'],
            '收入亿元':number(plot.get('raw',{}).get('revenue'),100000000),'归母利润亿元':number(plot.get('raw',{}).get('parent_profit'),100000000),
            '收入同比%':number(plot.get('x')),'利润增量占上年收入%':number(plot.get('y')),
            '扣非利润率变化pp':number(quality.get('x')),'现金流率变化pp':number(quality.get('y')),
            '扣非改善公司占比%':number(breadth.get('y')),'收入同比中位数%':number(metrics['company_median_revenue_yoy']['value'],D('.01')),
            '景气方向':group['facts']['trend']['label'],'N_RP':plot['n'],'N_DC':quality['n']})
        for kind,f in group['forecasts'].items():
            losses.extend({'行业':meta['sector_name'],'模型':kind,**r} for r in f.get('sample_losses',[]))
        del book
    total_rows=[]
    for date,vals in overall.items():total_rows.append({'报告期':date,'收入亿元':number(vals['revenue'],100000000),'归母利润亿元':number(vals['parent_profit'],100000000),'共同公司数':vals['n']})
    atomic_json(store.path/'calculations/three_year_common_panel.json',{'years':YEARS,'overall_exact':overall,'sector_rows':panel,'definition':'same R/P-valid nonfinancial company set across all three 9M periods per root, known comparability exclusions applied; not the pairwise YoY set'})
    query('three_year_totals',total_rows,'每行业2024/2025/2026前三季R/P共同公司，按金额合计；金融不混入收入比较；固定面板不是当时全市场。',['calculations/three_year_common_panel.json'])
    query('three_year_panel',panel,'三个报告期共用每行业同一R/P公司集，金额亿元；N/集合ID附列。',['calculations/three_year_common_panel.json'])
    query('sector_facts',root_table,'2026与2025前三季共同公司；收入/归母用R/P集，扣非/现金用R/D/C集，N_RP与N_DC分列；不能拼接不同集合的金额。',['calculations/groups.json'])
    query('financial_observations',financial,'金融仅列现有通用字段的有效金额，不新增金融专项，不进入非金融预测及评分。',['calculations/groups.json'])
    history=[]
    metric_names={'revenue':'营业收入','parent_profit':'归母净利润','deducted_profit':'扣非净利润','cashflow':'经营现金流','accounts_receivable':'应收账款','inventory':'存货','fixed_assets':'固定资产','assets':'总资产'}
    for group in groups:
        if group['identity']['financial']:continue
        for r in group['series']:
            history.append({'行业':group['identity']['sector_name'],'root':group['identity']['sector_code'],'报告期':r['period'],
                '指标':metric_names[r['metric']],'金额亿元':number(r['amount'],100000000),'有效公司数':r['n'],
                '同集同比%':number(r['yoy'],D('.01')),'同比公司数':r['comparison_n'],'集合ID':r['sample_id']})
    query('history_1',history,'流量为年内累计，余额为期末；各行有效公司集不同，不把跨期余额相减当经营变化；同比另用共同公司集，见源计算明细。',['calculations/groups.json'])
    write_csv(store.path/'calculations/history_L1.csv',history)
    for level in (1,2):
        objects=groups if level==1 else [child for g in groups for child in g['children']]
        rows=[]
        for g in objects:
            if g['identity']['financial']:continue
            for kind,f in g['forecasts'].items():
                rows.append({'行业':g['identity']['sector_name'],'指标':{'P':'归母净利润','D':'扣非净利润','C':'经营现金流'}[kind],
                    'N':f['n'],'当年收入覆盖%':number(f['coverage_current']['value'],D('.01')),'上年收入覆盖%':number(f['coverage_previous']['value'],D('.01')),
                    '前三季实际亿元':number(f.get('X9'),100000000),'Q4基准亿元':number(f.get('X4_base'),100000000),
                    '全年基准亿元':number(f.get('X_base'),100000000),'全年低情景亿元':number(f.get('X_low'),100000000),
                    '全年高情景亿元':number(f.get('X_high'),100000000),'同集预测收入亿元':number(f.get('R_base'),100000000),
                    '原因':f.get('reason',''),'集合ID':f['sample_id']})
        query(f'forecast_{level}',rows,'P/D/C按各自共同历史及当前样本分别预测；二级金额加总一级。X为对应指标；不得跨行集合相除；低高情景非概率。',['calculations/groups.json'])
        write_csv(store.path/'calculations'/f'forecast_L{level}.csv',rows)
    ranking_tables={}
    for level,rows in ranks.items():
        table=[]
        for r in rows:
            raw=r.get('raw') or [None]*7;cov=r['coverage_current']['value'];pcov=r['coverage_previous']['value']
            table.append({'行业':r['sector_name'],'行业代码':r['sector_code'],'root':r['root'],'合格':bool(r.get('eligible')),'名次':r.get('rank'),'总分':number(r.get('total_score')),
               'V估值':number((r.get('dimensions') or [None]*4)[0]),'G前景':number((r.get('dimensions') or [None]*4)[1]),'Q质量':number((r.get('dimensions') or [None]*4)[2]),'K风险':number((r.get('dimensions') or [None]*4)[3]),
               'N':r['n'],'当年收入覆盖%':number(cov,D('.01')),'上年收入覆盖%':number(pcov,D('.01')),
               '预测收入亿元':number(r.get('R_base'),100000000),'预测扣非亿元':number(r.get('X_base'),100000000),
               '扣非低情景亿元':number(r.get('X_low'),100000000),'扣非高情景亿元':number(r.get('X_high'),100000000),
               '预测盈利收益率%':number(raw[0],D('.01')),'预测收入增长%':number(raw[1],D('.01')),'预测利润率变化pp':number(raw[2],D('.01')),
               '现金流率%':number(raw[3],D('.01')),'扣非TTM_ROE%':number(raw[4],D('.01')),'资产负债率%':number(raw[5],D('.01')),'模型内下行%':number(raw[6],D('.01')),
               '原因':'；'.join(r.get('qualification_failures',[])) or r.get('score_reason',''),'集合ID':r['sample_id']})
        ranking_tables[level]=table
        query('rank_'+level,table,'同层级非金融完整资格集合；V/G/Q/K各25%；七项原始指标用共同S_score计算，再转百分位。正利润/权益/覆盖及N门槛不足不强排名；情景不是概率。',['calculations/ranking.json','calculations/sensitivity.json'])
        write_csv(store.path/'calculations'/f'ranking_L{level}.csv',table)
    chart_configs=[]
    for level in (1,2):
        for n in range(1,10):
            stem=f'L{level}_chart{n}';p=json.loads((store.path/'charts'/f'{stem}.json').read_text());audit=load(store.path/'charts'/f'{stem}_audit.json')
            chart_configs.append({'id':stem,'title':p['title'],'spec':p['spec'],'level':level,'number':n,'missing':audit['not_plotted'],'reference_set':audit['reference_set']})
            query(stem,p['rows'],'逐点共同样本与原值见行内N、候选数、两期已知收入覆盖、sample_id及raw_values；坐标单位见轴标签。零线/50/同行中位数参考线不因筛选重算；金融旁表。',[f'charts/{stem}.json',f'charts/{stem}_audit.json','calculations/groups.json'])
            queries[stem]['payloadColumns']=['raw_values']
    write_csv(store.path/'calculations/sector_facts.csv',root_table);write_csv(store.path/'calculations/three_year_panel.csv',panel)
    current=overall['2026-09-30'];prior=overall['2025-09-30'];old=overall['2024-09-30']
    growth=(current['revenue']/prior['revenue']-1)*100;profit_growth=(current['parent_profit']/prior['parent_profit']-1)*100
    growth25=(prior['revenue']/old['revenue']-1)*100;profit_growth25=(prior['parent_profit']/old['parent_profit']-1)*100
    positive=sum(r['收入同比%'] is not None and r['收入同比%']>0 for r in root_table)
    leaders=sorted((r for r in root_table if r['收入同比%'] is not None),key=lambda r:r['收入同比%'],reverse=True)
    joint_up=sum(r['扣非利润率变化pp'] is not None and r['现金流率变化pp'] is not None and r['扣非利润率变化pp']>0 and r['现金流率变化pp']>0 for r in root_table)
    discussion='## 行业差异怎么读\n\n'+'；'.join(f'{r["行业"]}收入增长{formatted(r["收入同比%"])}%，扣非利润率变化{formatted(r["扣非利润率变化pp"])}个百分点，经营现金流率变化{formatted(r["现金流率变化pp"])}个百分点' for r in leaders[:3])+'。这些是各图各自共同样本上的变化，不能仅按收入增速排景气。\n\n'
    discussion=discussion.replace('## 行业差异怎么读\n\n',f'## 行业差异怎么读\n\n三年固定面板中，2025年前三季收入增长{formatted(growth25)}%、归母利润增长{formatted(profit_growth25)}%；2026年分别为{formatted(growth)}%和{formatted(profit_growth)}%，名义经营增速较2025年提高。行业间仍然分化。\n\n')
    cash_up=[r['行业'] for r in root_table if r['扣非利润率变化pp'] is not None and r['现金流率变化pp'] is not None and r['扣非利润率变化pp']>0 and r['现金流率变化pp']>0]
    discussion+='利润率与现金流率同时改善的行业为'+ '、'.join(cash_up)+'。在这些行业内部，还要用图4检查改善公司占比，用图7/8检查应收与库存周转，避免行业合计被少数公司主导。\n\n'
    discussion+='综合评分中，食品饮料与基础化工并列第5，但来源不同：应结合G前景、Q质量及七项原值判断，不能将综合名次等同于当期景气方向。前三名的领先也可能依赖周期和当前市值；本模型没有推演商品价格，缺少宏观因果证据。'
    top=[r for r in ranking_tables['1'] if r['名次'] is not None and r['名次']<=5]
    sensitivity=load(store.path/'calculations/sensitivity.json');sensitive_rows=[];model_rows=[]
    for lev,data in sensitivity.items():
        names={r['行业代码']:r['行业'] for r in ranking_tables[lev]}
        for r in data['weight_sensitivity'].get('rows',[]):
            sensitive_rows.append({'层级':lev,'行业':names[r['sector_code']],'最低名次':r['min_rank'],'最高名次':r['max_rank'],
                '进入前20%次数':r['top20_combinations'],'权重组合数':data['weight_sensitivity']['combinations'],'进入前20%占比%':number(r['top20_fraction'],D('.01'))})
        for k,v in data['model_sensitivity'].items():
            model_rows.append({'层级':lev,'情形':{'0.25':'季节法25%','0.75':'季节法75%','exclude_top3':'剔除各行业收入前三公司'}[k],
                '可比排名':v['comparable_ranking'],'失效原候选数':len(v.get('failed_original_candidates',[]))})
    query('weight_sensitivity',sensitive_rows,'四维权重15%—35%，步长5%，合计100%；85组合；固定原候选集合；原同分并列规则。',['calculations/sensitivity.json'])
    query('model_sensitivity',model_rows,'模型占比25/75与75/25；剔除收入前三。若任一原候选失效，不过滤后重排。',['calculations/sensitivity.json'])
    conflicts=load(store.path/'evidence/formal_q4_conflicts.json')
    identities={r['ts_code']:r for r in samples}
    excluded=[{'公司':identities[r['code']]['name'],'股票代码':r['code'],'行业':identities[r['code']]['root_name'],
        '报告期':r['period'],'原因':'直接Q4扣非与全年减前三季相差超1元','处理':'累计事实保留，排除对应历史Q4及依赖它的预测/评分'} for r in conflicts['conflicts']]
    query('quality_exclusions',excluded,'23公司年份、21家公司；仅限制相应历史扣非季度及预测，不从所有事实中删除公司。此前22项审计与本次全范围23项不是同一范围。',['evidence/formal_q4_conflicts.json','evidence/quality.json'])
    summary=(f'## 主要发现\n\n在三年同一批{current["n"]:,}家非金融公司中，2026年前三季收入{formatted(current["revenue"],100000000)}亿元，较2025年增长{formatted(growth)}%；归母利润{formatted(current["parent_profit"],100000000)}亿元，增长{formatted(profit_growth)}%。这是固定当前公司范围的名义经营比较，不能当作GDP或历史当时全部上市公司。\n\n'
       f'29个非金融一级行业中，{positive}个行业在各自2025/2026共同样本上收入增长；{joint_up}个行业同时出现扣非利润率和经营现金流率同比改善。收入增长较快的包括'+ '、'.join(r['行业'] for r in leaders[:3])+'；增长与现金质量需要分开看。\n\n'
       f'按既定四维七项，{sum(r["合格"] for r in ranking_tables["1"])}个一级、{sum(r["合格"] for r in ranking_tables["2"])}个二级满足评分资格。一级研究优先级靠前的是'+ '、'.join(r['行业'] for r in top)+'。该顺序依赖2026全年条件预测与10月30日市值，不是目标收益率或买入建议。\n\n'
       f'本次冻结输入发现{conflicts["company_years"]}个历史Q4扣非冲突公司年份，按原门槛限制对应预测/评分，累计事实保留。采用现有数据计算，没有补数；部分历史重述尚未逐份公告核清。')
    paragraphs=summary.split('\n\n')
    for i,link in enumerate(('[1](#evidence-three-year)','[2](#evidence-sector-facts)','[3](#evidence-ranking)','[4](#evidence-quality)'),start=1):paragraphs[i]+=' '+link
    summary='\n\n'.join(paragraphs)
    methods='''## 读数口径与限制

报告期仅2024Q1—2026Q3，完整同比从2025年开始。东财采用2025年末体系，固定10月30日公司归属及估值，财务使用之后取得的最新修订值，不代表10月30日当时已知的全部信息。

主文比较非金融；银行和非银金融只保留通用事实旁表。每张图两轴共用该图的公司集合。三年固定面板、两年同比、R/P预测、D预测、C预测和七项评分的共同集合分别保存，不能将不同集合金额直接相除。金融和亏损/恢复、小样本或覆盖不足不强制综合排名，未排名不等于基本面差。

Q4收入由历史季节法与近期增长法各占50%；Q4利润率为2026Q3利润率加2024/2025两年Q4相对Q3变化的平均值；现金流采用此前确认方案中的前三季现金流率季节调整。二级先算金额再加总一级。两年历史只能提供透明基准，不证明预测精度；情景上下界不是概率或置信区间。四维等权；利润相关指标并非相互独立，排名须连同现金、负债和敏感性看。

Q4直接扣非与累计差分超1元的，保持现有剔除规则，不因找到更正公告或精度差就自动放行。湖北宜化保留已确认重述边界。其他公司未完成全部重述核验，历史收入、成本等也可能涉及调整；不能把全部财报差异都归为扣非不准。缺失为NA，不填零；2024平均余额需要2023期初的部分不算，不向前补数据。

收入是名义收入，不能仅据本报告区分销量、价格、合并范围与行业周期的因果贡献。上市母子公司和上下游交易仍可能重复加总。应收/库存的货币余额增长不单独证明需求、补库或现金恶化；须结合周转天数、利润与现金共同观察。未使用新增宏观数据、在建工程、ROIC、季度折旧或金融专项。

估值/成长图右上通常表示本套指标相对靠前；应收/库存周转天数及情景下行越低通常越好，不能把九图右上统一当作最好。图5与图6采用不同共同样本，同一行业两个点不能直接推导同一金额。敏感性若有原候选失效，不删除失效者后重排假装可比。'''
    snapshot={'surface':'report','title':'A股行业景气度：2024—2026年前三季度','generatedAt':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'status':'reviewed','buildStatus':'creating','filters':[],
      'report':{'asOf':'2026-11-01'},'queries':queries,'study':{'summary':summary,'discussion':discussion,'methods':methods,'chartConfigs':chart_configs,'roots':[{'code':g['identity']['sector_code'],'name':g['identity']['sector_name']} for g in groups],
       'companies':5571,'financial_rows':store.state.get('financial_rows'),'source_limitations':'现有财报、历史扣非冲突/重述、金融旁表；非实时定价','evidence_as_of':'财报提取时段见run.json与源回执；10/30价格/归属'}}
    atomic_json(store.path/'calculations/report_snapshot.json',snapshot)
    atomic_json(store.path/'calculations/report_findings.json',{'fixed_panel_n':current['n'],'fixed_panel_revenue_growth_pct':growth,'fixed_panel_parent_profit_growth_pct':profit_growth,'positive_revenue_industries':positive,'profit_cash_joint_improvement':joint_up,'top_research_priority':[r['行业'] for r in top]})
    (store.path/'report.md').write_text('# A股行业景气度：2024—2026年前三季度\n\n'+summary.replace('](#evidence-','](report.html#evidence-')+'\n\n'+discussion+'\n\n'+methods+'\n\n完整行业表和九类象限图见report.html；计算明细见calculations下CSV/JSON，原始投影和SQL在inputs及evidence。\n')
    store.save(status='REPORT_SNAPSHOT_SAVED')
    return snapshot


def build_report(store,complete=False):
    environment=load(store.path/'evidence/report_environment.json');node=environment['node'];plugin=Path(environment['plugin'])
    app=Path(environment['app'])
    if app.parent!=Path('/private/tmp') or not app.name.startswith('industry_financial_'):raise ValueError('Unsafe temporary app path')
    snapshot=json.loads((store.path/'calculations/report_snapshot.json').read_text())
    snapshot['buildStatus']='complete' if complete else 'creating'
    if not app.exists():
        args=[node,str(plugin/'output_formats/html/scripts/prepare-data-app.mjs'),'--surface','report','--output',str(app),'--snapshot',str(store.path/'calculations/report_snapshot.json')]
        result=subprocess.run(args,capture_output=True,text=True,timeout=30)
        if result.returncode:raise RuntimeError(result.stderr[-1500:])
        atomic_json(store.path/'evidence/report_prepare_receipt.json',json.loads(result.stdout))
    previous=load(app/'src/data.json');snapshot['id']=previous['id']
    atomic_json(app/'src/data.json',snapshot);atomic_json(store.path/'calculations/report_snapshot.json',snapshot)
    source=Path(__file__).parent/'report_app'
    for name in ('ReportContent.jsx','report.css'):shutil.copyfile(source/name,app/'src/content/report'/name)
    cli=plugin/'output_formats/html/scripts/data-app.mjs'
    result=subprocess.run([node,str(cli),'build','--project-dir',str(app),'--separate-data'],capture_output=True,text=True,timeout=45)
    (store.path/'evidence/report_build_stdout.txt').write_text(result.stdout);(store.path/'evidence/report_build_stderr.txt').write_text(result.stderr)
    if result.returncode:raise RuntimeError('Report app build failed: '+result.stderr[-1200:])
    export=app/'.data-app-offline/exports/research.html'
    result=subprocess.run([node,str(cli),'export-html','--project-dir',str(app),'--output',str(export)],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('Report export failed: '+result.stderr[-1000:])
    shutil.copyfile(export,store.path/'report.html')
    atomic_json(store.path/'evidence/report_app.json',{'app':str(app),'id':snapshot['id'],'report_sha256':digest(store.path/'report.html'),'complete':complete,'no_packages_installed':True,'authored_source':[str(source/'ReportContent.jsx'),str(source/'report.css')]})
    store.save(status='REPORT_BUILT' if complete else 'REPORT_PREVIEW_BUILT')
    return app/'dist'
