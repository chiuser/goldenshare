"""Two approved report samples from frozen aggregates; never opens a source connection."""
import argparse
from dataclasses import dataclass,asdict
from datetime import datetime
from decimal import Decimal as D,ROUND_CEILING
from pathlib import Path
import json
import resource
import shutil
import subprocess
import time
from zoneinfo import ZoneInfo
from .storage import OUTPUT_ROOT,load,digest,atomic_json
from .spec import SPEC as RESEARCH_SPEC

@dataclass(frozen=True)
class SampleChapterSpec:
    source_run:str='formal_20261101_01'
    periods:tuple=('2024-09-30','2025-09-30','2026-09-30')
    financial_names:tuple=('银行','非银金融')
    input_bytes:int=50*1024*1024
    memory_bytes:int=256*1024*1024
    calculation_seconds:int=60
    money_tolerance_yuan:str='1'
    default_industry:str='非金融整体'
    near_zero_profit:str=RESEARCH_SPEC.near_zero_profit
    annotation_names:tuple=('电子','有色金属','煤炭','通信','食品饮料','房地产','农林牧渔','纺织服饰')
    featured_names:tuple=('电子','煤炭','食品饮料','农林牧渔')

SPEC=SampleChapterSpec()
STATES=('收入增长、利润率提高','收入增长、利润率下降','收入下降、利润率提高','收入下降、利润率下降','持平边界')
NODE='/Users/congming/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
PLUGIN=Path('/Users/congming/.codex/plugins/cache/openai-curated-remote/data-analytics/1.1.1-exp-components.2')


def classification(x,y):
    if x==0 or y==0:return STATES[4]
    return STATES[(0 if x>0 else 2)+(0 if y>0 else 1)]


def quadrant_row(group):
    if group['identity']['sector_name'] in SPEC.financial_names:return None
    point=group['facts']['plots']['4']
    if not point.get('available'):raise ValueError('Missing current R/D common-company result')
    raw=point['raw'];r0,r1,p0,p1=[D(raw[k]) for k in ('prior_revenue','revenue','prior_deducted_profit','deducted_profit')]
    if r0<=0 or r1<=0:raise ValueError('Nonpositive industry revenue')
    x=(r1/r0-1)*100;y=(p1/r1-p0/r0)*100
    if abs(y-D(point['x']))>D('1e-20'):raise ValueError('Frozen common-company margin does not reconcile')
    loss='已盈利' if p1>0 else '盈亏平衡' if p1==0 else '亏损收窄' if p1>p0 else '亏损扩大' if p1<p0 else '仍亏损'
    row={'行业':group['identity']['sector_name'],'收入增长（%）':float(x),'利润率变化（百分点）':float(y),
         '上年扣非利润率（%）':float(p0/r0*100),'本期扣非利润率（%）':float(p1/r1*100),
         '本期收入（亿元）':float(r1/100000000),'上年收入（亿元）':float(r0/100000000),
         '本期扣非利润（亿元）':float(p1/100000000),'上年扣非利润（亿元）':float(p0/100000000),
         '可比公司数':point['n'],'候选公司数':point['candidate_n'],
         '当期已知收入覆盖（%）':float(D(point['coverage_current']['value'])*100),
         '上年已知收入覆盖（%）':float(D(point['coverage_previous']['value'])*100),
         '经营状态':classification(x,y),'盈亏情况':loss}
    audit={'industry':row['行业'],'sample_id':point['sample_id'],'codes':point['codes'],
           'x_exact':x,'y_exact':y,'raw_amounts_yuan':raw}
    return row,audit


def history_rows(panel):
    rows=[]
    for r in panel['sector_rows']:
        rows.append({'行业':r['行业'],'年份':r['报告期'][:4],
          '收入（亿元）':float(D(str(r['收入亿元']))),'归母净利润（亿元）':float(D(str(r['归母利润亿元']))),
          '可比公司数':r['共同公司数']})
    for date,v in panel['overall_exact'].items():
        subset=[r for r in rows if r['年份']==date[:4]]
        for key,exact_key in (('收入（亿元）','revenue'),('归母净利润（亿元）','parent_profit')):
            total=sum((D(str(r[key]))*100000000 for r in subset),D(0))
            if abs(total-D(v[exact_key]))>D(SPEC.money_tolerance_yuan):raise ValueError('Three-year display amounts do not reconcile')
        if sum(r['可比公司数'] for r in subset)!=v['n']:raise ValueError('Three-year sample counts do not reconcile')
        rows.append({'行业':SPEC.default_industry,'年份':date[:4],'收入（亿元）':float(D(v['revenue'])/100000000),
                     '归母净利润（亿元）':float(D(v['parent_profit'])/100000000),'可比公司数':v['n']})
    for name in {r['行业'] for r in rows}:
        subset=[r for r in rows if r['行业']==name]
        if len(subset)!=3 or len({r['可比公司数'] for r in subset})!=1:raise ValueError('Three-year same-company panel changed')
    return rows


def input_manifest(source):
    files=('calculations/groups.json','calculations/three_year_common_panel.json')
    historical=load(source/'evidence/artifact_manifest.json')['files']
    if sum((source/f).stat().st_size for f in files)>SPEC.input_bytes:raise ValueError('Input budget exceeded')
    for f in files:
        if digest(source/f)!=historical[f]:raise ValueError('Frozen source hash changed: '+f)
    return {f:digest(source/f) for f in files}


def prepare(output):
    started=time.monotonic();source=OUTPUT_ROOT/SPEC.source_run;hashes=input_manifest(source)
    groups=load(source/'calculations/groups.json');panel=load(source/'calculations/three_year_common_panel.json')
    points=[];audits=[]
    for g in groups:
        result=quadrant_row(g)
        if result:points.append(result[0]);audits.append(result[1])
    if len(points)!=29:raise ValueError('Nonfinancial industry count changed')
    history=history_rows(panel)
    counts={s:sum(r['经营状态']==s for r in points) for s in STATES}
    if sum(counts.values())!=len(points):raise ValueError('Quadrant coverage')
    def source_meta(label,definition,files,ids):
        return {'label':label,'files':files,'filters':['2026年前三季度与2025同期；三年图仅比较各年前三季度','东财2025年末分类体系，2026-10-30公司归属'],
          'caveats':['按可比公司汇总计算，样本数和收入覆盖随比较范围变化','财报采用2026-11-01冻结版本；收入增长与利润率变化不代表股票收益'],
          'metricDefinitions':[{'label':label,'definition':definition,'componentIds':ids}]}
    qsource=source_meta('[1] 一级行业景气','收入增长=(2026收入/2025收入−1)×100；利润率变化=(2026扣非/收入−2025扣非/收入)×100个百分点。两轴使用同一批R/D可比公司；先合计金额再计算。',[str(source/'calculations/groups.json')],['industry-quadrant','quadrant-findings'])
    hsource=source_meta('[2] 三年前三季度经营','每个行业三个年度使用同一批收入和归母利润均有效且可比的公司；各行业相加为5275家非金融公司。金额沿用已冻结的亿元汇总显示精度。图表只做单位缩放和横向排列。',[str(source/'calculations/three_year_common_panel.json')],['history-revenue','history-profit','history-findings']+[f'history-feature-{i}' for i in range(4)])
    maxx=max(abs(r['收入增长（%）']) for r in points);maxy=max(abs(r['利润率变化（百分点）']) for r in points)
    xbound=int((D(str(maxx))*D('1.12')/10).to_integral_value(rounding=ROUND_CEILING))*10
    ybound=int((D(str(maxy))*D('1.12')).to_integral_value(rounding=ROUND_CEILING))
    spec={'type':'scatter','x':'收入增长（%）','y':'利润率变化（百分点）','rowId':'行业',
      'xLabel':'收入同比增长（%） →','yLabel':'扣非利润率同比变化（百分点） ↑',
      'xDomain':[-xbound,xbound],'yDomain':[-ybound,ybound],
      'referenceLines':[{'axis':'x','value':0,'label':'收入持平'},{'axis':'y','value':0,'label':'利润率持平'}],
      'annotations':[{'id':'industry-label-'+str(i),'kind':'point','rowId':name,'field':'利润率变化（百分点）','label':name} for i,name in enumerate(SPEC.annotation_names)],
      'colors':{'利润率变化（百分点）':'#3276b5'},'valueFormat':{'style':'decimal','maximumFractionDigits':2}}
    snapshot={'surface':'report','title':'行业景气与三年经营变化 · 两个样章','generatedAt':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
      'report':{'asOf':'2026-11-01'},'status':'reviewed','buildStatus':'creating','filters':[],
      'queries':{'industry_quadrant':{'rows':points,'source':qsource},'history_comparison':{'rows':history,'source':hsource}},
      'study':{'states':STATES,'counts':counts,'quadrantSpec':spec,'industries':[SPEC.default_industry]+[g['identity']['sector_name'] for g in groups if g['identity']['sector_name'] not in SPEC.financial_names],
       'featured':SPEC.featured_names,'defaultIndustry':SPEC.default_industry,'nearZeroProfit':float(SPEC.near_zero_profit),'yearColors':{'2024':'#94a3b8','2025':'#4f78ac','2026':'#0f9185'}}}
    atomic_json(output/'evidence/input_manifest.json',{'source':str(source),'hashes':hashes,'source_manifest_sha256':digest(source/'evidence/artifact_manifest.json'),'spec':asdict(SPEC)})
    atomic_json(output/'evidence/quadrant_exact.json',audits)
    atomic_json(output/'data.json',snapshot)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if rss>SPEC.memory_bytes:raise ValueError('Memory budget exceeded')
    if time.monotonic()-started>SPEC.calculation_seconds:raise ValueError('Calculation budget exceeded')
    validate(output)
    atomic_json(output/'evidence/calculation_receipt.json',{'seconds':time.monotonic()-started,'peak_python_bytes':rss,'input_mib':sum((source/f).stat().st_size for f in hashes)/1024**2,'points':len(points),'history_rows':len(history),'counts':counts,'source_reads':'local frozen aggregates only','source_connections':0})
    return snapshot


def validate(output):
    snapshot=json.loads((output/'data.json').read_text())
    forbidden={'sample_id','样本ID','共同样本ID','集合ID','ts_code','root','sector_code','row_id'}
    for q in snapshot['queries'].values():
        for row in q['rows']:
            if forbidden&row.keys():raise ValueError('Internal field leaked into report')
    points=snapshot['queries']['industry_quadrant']['rows'];hist=snapshot['queries']['history_comparison']['rows']
    if len(points)!=29 or len(hist)!=90:raise ValueError('Display coverage changed')
    atomic_json(output/'evidence/data_acceptance.json',{'coordinate_and_history_checks':True,'technical_fields_in_reader_rows':False,'points':len(points),'history_rows':len(hist),'data_sha256':digest(output/'data.json')})


def run_command(args,seconds):
    result=subprocess.run(args,capture_output=True,text=True,timeout=seconds)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    return result.stdout


def build(output,complete=False):
    env=json.loads((output/'evidence/environment.json').read_text());app=Path(env['app']);node=env['node'];plugin=Path(env['plugin'])
    if app.parent!=Path('/private/tmp') or not app.name.startswith('industry_financial_chapter_samples_'):raise ValueError('Unsafe app directory')
    if not app.exists():
        receipt=run_command([node,str(plugin/'output_formats/html/scripts/prepare-data-app.mjs'),'--surface','report','--output',str(app),'--snapshot',str(output/'data.json')],45)
        atomic_json(output/'evidence/prepare_receipt.json',json.loads(receipt))
    data=json.loads((output/'data.json').read_text());previous=json.loads((app/'src/data.json').read_text());data['id']=previous['id'];data['buildStatus']='complete' if complete else 'updating' if (output/'evidence/build_receipt.json').exists() else 'creating'
    atomic_json(output/'data.json',data);atomic_json(app/'src/data.json',data)
    src=Path(__file__).parent/'sample_report_app'
    for name in ('ReportContent.jsx','report.css'):shutil.copyfile(src/name,app/'src/content/report'/name)
    cli=plugin/'output_formats/html/scripts/data-app.mjs'
    stdout=run_command([node,str(cli),'build','--project-dir',str(app),'--separate-data'],45)
    (output/'evidence/build_stdout.txt').write_text(stdout)
    export=app/'.data-app-offline/exports/sample-chapters.html'
    run_command([node,str(cli),'export-html','--project-dir',str(app),'--output',str(export)],45)
    shutil.copyfile(export,output/'report.html');validate(output)
    atomic_json(output/'evidence/build_receipt.json',{'app_id':data['id'],'report_sha256':digest(output/'report.html'),'complete':complete,'no_packages_installed':True})
    return app/'dist'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--build',action='store_true');parser.add_argument('--complete',action='store_true');a=parser.parse_args()
    output=a.output.resolve()
    if output.parent!=OUTPUT_ROOT or not output.name.startswith('chapter_samples_'):raise ValueError('Only a new direct chapter_samples_ study directory is allowed')
    if a.build:
        evidence=load(output/'evidence/input_manifest.json')
        if evidence['spec']!=json.loads(json.dumps(asdict(SPEC))) or evidence['hashes']!=input_manifest(OUTPUT_ROOT/SPEC.source_run):raise ValueError('Input/spec changed before rebuild')
        print(build(output,a.complete));return
    if output.exists():raise ValueError('Existing result directory cannot be overwritten')
    output.mkdir();(output/'evidence').mkdir()
    atomic_json(output/'evidence/environment.json',{'node':NODE,'plugin':str(PLUGIN),'app':'/private/tmp/industry_financial_'+output.name,'source':'installed workspace dependencies, existing Data plugin; no installations'})
    prepare(output);print('Prepared two sample chapters:',output)

if __name__=='__main__':main()
