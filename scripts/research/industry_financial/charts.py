"""Nine reviewed quadrant coordinates, passed to the installed Data renderer."""
from decimal import Decimal as D
from statistics import median
import html
import json
from pathlib import Path
import subprocess
from .storage import atomic_json,load,digest
from .spec import SPEC

TITLES={1:'事实：收入与归母利润',2:'事实：单季增长与变化方向',3:'事实：盈利与现金',4:'事实：行业合计与改善范围',
        5:'预测：盈利前景与估值',6:'预测：利润率改善与模型内下行幅度',7:'事实：收入与应收',8:'事实：收入与存货',9:'事实：收入与固定资产'}
LABELS={1:('收入同比（%）','归母利润增量/上年收入（%）'),2:('2026Q3收入同比（%）','较2026Q2增速变化（百分点）'),
        3:('扣非归母利润率同比变化（百分点）','经营现金流率同比变化（百分点）'),
        4:('扣非归母利润率同比变化（百分点）','扣非归母利润改善公司占比（%）'),
        5:('盈利前景G（分）','估值吸引力V（分）'),6:('预测全年扣非归母利润率变化（百分点）','模型内全年利润下行幅度（%）'),
        7:('收入同比（%）','应收周转天数同比变化（天）'),8:('收入同比（%）','存货周转天数同比变化（天）'),9:('收入同比（%）','固定资产合计同比（%）')}


def quadrant(x,y,bx,by):
    if x==bx or y==by:return '边界'
    return ('右' if x>bx else '左')+('上' if y>by else '下')


def chart_rows(groups,ranking,level,number):
    objects=groups if level==1 else [child for group in groups for child in group['children']]
    scoremap={r['sector_code']:r for r in ranking[str(level)]}
    bx=D(50) if number==5 else D(0);by=D(50) if number in (4,5) else D(0)
    rows=[];missing=[]
    for group in objects:
        identity=group['identity'];code=identity['sector_code'];source=None
        if identity.get('financial'):
            missing.append({'sector_code':code,'reason':'financial_industry_observation_only'});continue
        if number in (5,6):
            source=scoremap.get(code) if number==5 else group['forecasts']['D']
            if number==5:
                if not source or not source.get('score_available'):
                    missing.append({'sector_code':code,'reason':(source or {}).get('score_reason','no_score'),'failures':(source or {}).get('qualification_failures',[])});continue
                x,y=map(D,(source['dimensions'][1],source['dimensions'][0]))
            else:
                if not source or not source.get('available') or D(source['X_base'])<=0:
                    missing.append({'sector_code':code,'reason':'no_positive_base_deducted_forecast'});continue
                x=(D(source['X_base'])/D(source['R_base'])-D(source['X25'])/D(source['R25']))*100
                y=(D(source['X_base'])-D(source['X_low']))/D(source['X_base'])*100
        else:
            source=group['facts']['plots'].get(str(number),group['facts']['plots'].get(number))
            if not source or not source.get('available'):
                missing.append({'sector_code':code,'reason':(source or {}).get('reason','no_complete_axes')});continue
            x,y=D(source['x']),D(source['y'])
        if not x.is_finite() or not y.is_finite():raise ValueError('Non-finite scatter coordinates')
        cv=source['coverage_current']['value'];pv=source['coverage_previous']['value']
        raw=source.get('raw',{k:source.get(k) for k in ('R9','X9','R25','X25','R_base','X_base','X_low','X_high','market_value_yuan') if k in source})
        if number==5:
            raw=dict(zip(('forecast_earnings_yield','forecast_revenue_growth','forecast_margin_change','cashflow_margin','deducted_ttm_roe','debt_asset_ratio','model_downside'),raw))
        rows.append({'raw_values':json.dumps(raw,ensure_ascii=False,default=str),'name':identity['sector_name'],'row_id':code,'root':identity['root'],'x':float(x),'y':float(y),
                     'x_exact':str(x),'y_exact':str(y),'sample_id':source['sample_id'],'样本数':source['n'],'候选数':source['candidate_n'],
                     '样本内当期收入覆盖':None if cv is None else str(D(cv)*100)+'%',
                     '样本内上年收入覆盖':None if pv is None else str(D(pv)*100)+'%',
                     '期间':'FY2026条件预测' if number in (5,6) else '2026Q3单季' if number==2 else '2026前三季同比'})
    if number==6:
        if len(rows)<SPEC.min_peers:
            missing += [{'sector_code':r['row_id'],'reason':'fewer_than_5_model_peers_for_relative_downside'} for r in rows]
            return [],missing,bx,None
        by=median(D(r['y_exact']) for r in rows)
    for row in rows:row['象限']=quadrant(D(row['x_exact']),D(row['y_exact']),bx,by)
    if len(rows)+len(missing)!=len(objects):raise AssertionError('Chart coverage does not reconcile')
    return rows,missing,bx,by


def write_preview(store,renderer):
    renderer=Path(renderer).resolve()
    if not renderer.is_file():raise ValueError('Installed Data renderer unavailable; no installation allowed')
    groups=load(store.path/'calculations/groups.json');ranking=load(store.path/'calculations/ranking.json')
    receipts=[];panels={1:[],2:[]};configs=[];level2_payloads=[]
    formal=store.scope.name=='formal'
    for level in (1,2):
        for number in range(1,10):
            store.check()
            rows,missing,bx,by=chart_rows(groups,ranking,level,number)
            stem=f'L{level}_chart{number}';name=stem+'.json'
            refs=[{'axis':'x','value':float(bx),'label':'零线' if bx==0 else '50分'}]
            if by is not None:refs.append({'axis':'y','value':float(by),'label':'同行中位数' if number==6 else '50%' if number==4 else '50分' if number==5 else '零线'})
            spec={'type':'scatter','x':'x','y':'y','xLabel':LABELS[number][0],'yLabel':LABELS[number][1],
                  'rowId':'row_id','referenceLines':refs,'valueFormat':{'style':'decimal','maximumFractionDigits':3}}
            if number==5:spec.update(xDomain=[0,100],yDomain=[0,100])
            payload={'id':stem,'title':f'{"行业研究" if formal else "试算样本"} · {"一级" if level==1 else "二级"} · '+TITLES[number],
                     'height':400,'spec':spec,'rows':rows,'description':'当前候选范围；财报最新修订、价格/归属2026-10-30；金融旁表；扣非冲突保留。' if formal else '固定100家代码顺序样本，非全行业结论；财报最新修订、价格/归属2026-10-30。'}
            atomic_json(store.path/'charts'/name,payload)
            atomic_json(store.path/'charts'/f'{stem}_audit.json',{'plotted':len(rows),'not_plotted':missing,'reference_set':[r['row_id'] for r in rows],
                        'reference_x':bx,'reference_y':by,'quadrant_counts':{q:sum(r['象限']==q for r in rows) for q in ('右上','右下','左上','左下','边界')},'not_formal_industry_ranking':not formal})
            dest=store.path/'charts'/f'{stem}.html'
            proc=subprocess.run(['node',str(renderer),'--input',str(store.path/'charts'/name),'--output',str(dest),'--surface','html'],capture_output=True,text=True,timeout=15)
            if proc.returncode:raise RuntimeError('Data renderer failed '+stem+': '+proc.stderr[:500])
            receipts.append(json.loads(proc.stdout))
            detail=''.join('<tr data-root="'+html.escape(row['root'])+'">'+''.join('<td>'+html.escape(str(row.get(k,'')))+'</td>' for k in ('name','x_exact','y_exact','样本数','样本内当期收入覆盖','象限'))+'</tr>' for row in rows)
            missing_detail='；'.join(m['sector_code']+': '+m['reason'] for m in missing)
            plot_html=f'<iframe title="{stem}" src="charts/{stem}.html" height="480"></iframe>' if level==1 else f'<div id="{stem}" data-data-chart data-viz-composition><div data-viz-container style="min-height:400px"></div></div>'
            if level==2:level2_payloads.append(payload)
            panel=f'<section><h3>{number}. {html.escape(TITLES[number])}</h3><p>全参考集点数 {len(rows)}；未绘制 {len(missing)}。'+html.escape(missing_detail)+f'</p>{plot_html}<details><summary>精确数值及共同样本</summary><table><thead><tr><th>行业</th><th>横轴</th><th>纵轴</th><th>N</th><th>试算样本内覆盖</th><th>象限</th></tr></thead><tbody>{detail}</tbody></table></details></section>'
            panels[level].append(panel)
            configs.append({'level':level,'number':number,'rows':len(rows),'missing':len(missing)})
    text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股行业研究 · 有限试算核验</title><style>body{font:16px system-ui;margin:24px auto;max-width:1250px;padding:0 20px;color:#20252b;background:#f7f8fa}h1{font-size:26px}.notice{background:#fff3d6;padding:16px;border-radius:8px}main{display:grid;grid-template-columns:1fr 1fr;gap:18px}section{background:white;border:1px solid #dbe0e5;border-radius:10px;padding:16px;min-width:0}iframe{border:0;width:100%;background:white}table{border-collapse:collapse;font-size:12px;width:100%}td,th{border:1px solid #ddd;padding:5px;overflow-wrap:anywhere}p{line-height:1.6}details{margin:16px 0}@media(max-width:850px){main{grid-template-columns:1fr}}</style><h1>A股行业研究 · 有限试算核验</h1><p class="notice">仅用于验证计算与图表：5行业各20家，共100家，按代码顺序选取，非行业代表样本。覆盖分母仅为本次选定代码。图5/6为条件预测；无目标价或正式投资价值结论。</p><p>2024Q1—2026Q3；行业/估值固定2026-10-30；最新修订财务。湖北宜化2024/2025跨期及2025Q1已知重述差异按规则排除相关比较，原始事实保留。一级仅4个评分合格同行，图5按门槛显示无得分；不改变门槛凑图。</p><p>数字均来自同一冻结输入与已保存金额表。模型内上下界不是概率；图7/8周转天数越低通常越好。三份公告核验不能代替逐家公司审计。</p><h2>一级行业 · 试算</h2><main>'''+''.join(panels[1])+'''</main><details id="level2"><summary>展开二级行业 · 试算（含原始值及评分验证）</summary><main>'''+''.join(panels[2])+'''</main></details><p>数据明细：<a href="calculations/groups.json">事实及预测</a> · <a href="calculations/ranking.json">七项原值/资格与试算分数</a> · <a href="evidence/announcement_checks.json">公告核对</a> · <a href="evidence/quality.json">已知可比性问题</a></p></html>'''
    root_names={g['identity']['sector_code']:g['identity']['sector_name'] for g in groups}
    options='<option value="">全部二级</option>'+''.join('<option value="'+html.escape(k)+'">'+html.escape(v)+'</option>' for k,v in root_names.items())
    control='<p><label>查看一级下的二级行业：<select id="root-filter">'+options+'</select></label> <span id="filter-note">参考线/分数固定为全二级参考集，筛选不重排。</span></p>'
    text=text.replace('<main>'+''.join(panels[2]),control+'<main>'+''.join(panels[2]),1)
    payload_json=json.dumps(level2_payloads,ensure_ascii=False).replace('<','\\u003c')
    script="""<script type="module">
import {mountChart} from 'https://persistent.oaistatic.com/plugins/visualize/charts/data-analytics-plugin/1.2.1/charts/element.js';
const inputs=PAYLOADS;
const mounted=inputs.map(config=>({base:config,chart:mountChart(document.getElementById(config.id).querySelector('[data-viz-container]'),config)}));
document.getElementById('root-filter').addEventListener('change',event=>{
 const root=event.target.value;
 for(const item of mounted){const next={...item.base,rows:item.base.rows.filter(row=>!root||row.root===root)};item.chart=mountChart(document.getElementById(item.base.id).querySelector('[data-viz-container]'),next);}
 document.querySelectorAll('#level2 tr[data-root]').forEach(row=>{row.hidden=Boolean(root&&row.dataset.root!==root)});
 document.getElementById('filter-note').textContent='筛选：'+(root||'全部')+'；参考线、原始分数和比较集合保持不变。';
});
</script>""".replace('PAYLOADS',payload_json)
    css=renderer.parents[2]/'assets/chart-host.css'
    if css.exists():text=text.replace('</style>','</style><style>'+css.read_text()+'</style>',1)
    text=text.replace('</html>',script+'</html>')
    (store.path/'report.html').write_text(text)
    atomic_json(store.path/'evidence/chart_render_receipts.json',{'renderer':str(renderer),'renderer_sha256':digest(renderer),'receipts':receipts,'charts':configs,'payload_validation':True,'browser_render_checked':False})
    store.save(status='CHART_PAYLOADS_AND_PREVIEW_SAVED')
    return configs
