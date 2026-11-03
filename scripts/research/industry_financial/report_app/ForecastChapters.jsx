import React from 'react';
import {RichNarrative,ReportSection,EvidenceChart,ChartTooltip,chartConfigEntries,useDataApp} from '../../data-app-public.jsx';
const n=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
const signed=v=>(v>0?'+':'')+n(v);
const delta=v=>(v>=0?'增加':'减少')+n(Math.abs(v));
const chunk=(rows,size=16)=>Array.from({length:Math.ceil(rows.length/size)},(_,i)=>rows.slice(i*size,(i+1)*size));
const available=s=>s.study.stage==='forecast';
function Note({id,children}){return <RichNarrative id={id} className="sample-note" value={children}/>;}
function Tip({active,payload,label,fields=[]}){
  const {snapshot}=useDataApp();if(!active||!payload?.length)return null;const r=payload.find(p=>p.payload)?.payload;if(!r)return null;
  if(r.维度)fields=[...fields,r.维度+'得分'];const details=fields.map(f=>({label:f,value:r[f]==null?'—':n(r[f])}));
  if(r.指标)details.unshift({label:'模型',value:r.指标+'模型'});
  if(r.利润变化状态)details.push({label:'利润变化状态',value:r.利润变化状态});
  if(r.名次!=null)details.push({label:'原综合名次',value:String(r.名次)});
  if(r.可比公司数!=null)details.push({label:'可比公司数',value:r.可比公司数+'家'});
  if(r['本期已知收入覆盖（%）']!=null)details.push({label:'本期已知收入覆盖',value:n(r['本期已知收入覆盖（%）'])+'%'});
  if(r['上期已知收入覆盖（%）']!=null)details.push({label:'上期已知收入覆盖',value:n(r['上期已知收入覆盖（%）'])+'%'});
  if(r.覆盖提示)details.push({label:'覆盖',value:r.覆盖提示});
  if(r.评分状态==='合格')for(const f of snapshot.study.forecast.rawNames)if(!fields.includes(f))details.push({label:f,value:n(r[f])});
  if(r['前20%组合数']!==undefined)details.push({label:'进入前20%的权重组合',value:r['前20%组合数']+'/85（'+n(r['前20%组合占比（%）'])+'%）'});
  if(r.未评分原因)details.push({label:'未评分原因',value:r.未评分原因});
  return <ChartTooltip active label={r.行业||label} details={details}/>;
}
function Bars({id,queryId,rows,fields,title,unit='亿元',percent=false,range=null,rankRange=false,colors=null,note,sourceRows:providedSource}){
  const {snapshot,visible}=useDataApp();if(!visible(id))return null;
  const sourceRows=providedSource||rows,plot=rows.map(r=>({...r,...(percent?Object.fromEntries(fields.map(f=>[f,r[f]==null?null:r[f]/100])):{})}));
  const colorMap=colors||Object.fromEntries(fields.map((f,i)=>[f,[snapshot.study.colors.blue,snapshot.study.forecast.predictionColor,snapshot.study.colors.teal][i%3]]));
  const values=rows.flatMap(r=>fields.map(f=>r[f]).concat(range?[r[range[0]],r[range[1]]]:[])).filter(v=>v!=null);
  const lo=Math.min(0,...values),hi=Math.max(0,...values),pad=(hi-lo||1)*.38;
  const spec={type:'horizontalBar',x:fields.length===1?fields[0]:fields,y:'行业',xLabel:unit,showLegend:fields.length>1,showValues:fields.length===1||rows.length<=6,stackable:false,
    yOrder:rows.map(r=>r.行业),colors:colorMap,valueFormat:{style:percent?'percent':'decimal',maximumFractionDigits:2},
    ...(percent?{}:{xDomain:[lo<0?lo-pad:0,hi+pad]}),
    ...(range?{uncertainty:{lower:range[0],upper:range[1],style:'bars',label:rankRange?'权重变化下的名次范围':'模型情景范围'}}:{})};
  const [chart]=chartConfigEntries({id,title,rows:plot,spec,height:Math.min(800,Math.max(260,90+rows.length*(fields.length>1?42:25)))});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={sourceRows} description={note||`2026全年基准预测，${unit}；各行业使用本项模型的固定可比公司。`}
    chartOptions={{tooltipContent:props=>{if(percent){const payload=props.payload?.map(p=>({...p,payload:{...p.payload,...Object.fromEntries(fields.map(f=>[f,p.payload[f]==null?null:p.payload[f]*100]))}}));return <Tip {...props} payload={payload} fields={[...fields,...(range||[])]}/>;}return <Tip {...props} fields={[...fields,...(range||[])]}/>;}}}>
    {fields.length===1&&<div className="business-legend" aria-label="图例"><i style={{background:colorMap[fields[0]]}}/>{range?(rankRange?'柱为基准名次；线段为最好—最差名次':'柱为全年基准预测；线段为模型低—高情景'):fields[0]}</div>}
  </EvidenceChart>;
}
function valueTop(rows,limit){return rows.filter(r=>r.评分状态==='合格'&&r.名次<=limit);}
function unqualifiedText(rows){const groups=new Map();for(const row of rows.filter(r=>r.评分状态!=='合格')){const reason=row.未评分原因;groups.set(reason,[...(groups.get(reason)||[]),row.行业]);}return [...groups].map(([reason,names])=>`- ${reason}：${names.join('、')}。`).join('\n');}
function pRows(reviewedRows,level){return reviewedRows('forecast_'+level).filter(r=>r.指标==='归母净利润');}
function ordered(rows,names){return names.map(name=>rows.find(r=>r.行业===name)).filter(Boolean);}
function Dimensions({id,queryId,rows,title}){
  const {snapshot,visible}=useDataApp();if(!visible(id))return null;
  const plot=rows.flatMap(r=>snapshot.study.forecast.dimensions.map(f=>({...r,维度:f.replace('得分',''),分数:r[f]})));
  const [chart]=chartConfigEntries({id,title,rows:plot,spec:{type:'heatmap',x:'维度',y:'行业',value:'分数',xOrder:['估值','前景','质量','风险'],yOrder:rows.map(r=>r.行业),reverseRows:true,
    colorDomain:[0,100],colorBands:[{max:25,color:'#e3e9ee',legendGroup:'0—25分'},{max:50,color:'#b6d0d9',legendGroup:'25—50分'},{max:75,color:'#72b4ad',legendGroup:'50—75分'},{color:'#287c70',legendGroup:'75—100分'}],showValues:true,hideMissingCells:false,valueFormat:{style:'decimal',maximumFractionDigits:1}},height:110+rows.length*28});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={rows} description="四维分别为0—100分，各占综合分25%；分数越高，在本层级合格行业中相对越有利。风险得分高表示本模型内风险较低。" chartOptions={{tooltipContent:props=><Tip {...props} fields={['综合得分']}/>}}/>;
}
export function ExecutiveSummary(){
  const {snapshot,reviewedRows}=useDataApp();if(!available(snapshot))return null;
  const growth=reviewedRows('summary_growth'),q=reviewedRows('history_quarter_overall'),p=pRows(reviewedRows,'1'),v=reviewedRows('value_1'),v2=reviewedRows('value_2');
  const rg=(year,metric)=>growth.find(r=>r.年份===year&&r.指标===metric)['同比增长（%）'];
  const rows=['营业收入','归母净利润'].map(name=>({行业:name,'2025年前三季':rg('2025',name),'2026年前三季':rg('2026',name),可比公司数:5275}));
  const ar=reviewedRows('primary_receivable_balance');const sum=key=>ar.reduce((s,r)=>s+r[key],0);const arGrowth=(sum('2026年9月末应收账款（亿元）')/sum('2025年9月末应收账款（亿元）')-1)*100;
  return <section id="report-summary" className="sample-chapter forecast-chapter">
    <RichNarrative id="summary:heading" value="## 1　总结"/>
    <ReportSection id="summary-growth-findings" title="整体经营修复与季度放缓" queryId="summary_growth" queryIds={['summary_growth','history_quarter_overall']} sourceRowsByQuery={{summary_growth:growth,history_quarter_overall:q}} showHeading={false}>
      <RichNarrative id="summary:growth" value={`**2026年前三季度经营增长较2025年回升，但第三季度利润增速放缓。** 固定5,275家非金融公司收入同比增长${n(rg('2026','营业收入'))}%、归母利润增长${n(rg('2026','归母净利润'))}%；2025年同期分别增长${n(rg('2025','营业收入'))}%和${n(rg('2025','归母净利润'))}%。固定5,192家季度可比公司中，归母利润同比增速从2026年Q2的21.98%降至Q3的4.32%。`}/>
    </ReportSection>
    <Bars id="summary-growth" queryId="summary_growth" rows={rows} fields={['2025年前三季','2026年前三季']} title="非金融整体前三季收入与归母利润同比增长" unit="%" percent note="同一批5,275家公司，均为1—9月与上年同期比较。" colors={{'2025年前三季':snapshot.study.yearColors['2025'],'2026年前三季':snapshot.study.yearColors['2026']}}/>
    <ReportSection id="summary-quality-findings" title="增长分化及经营质量" queryId="industry_quadrant" queryIds={['industry_quadrant','primary_receivable_balance','primary_receivable','primary_quality']} sourceRowsByQuery={{industry_quadrant:reviewedRows('industry_quadrant'),primary_receivable_balance:ar,primary_receivable:reviewedRows('primary_receivable'),primary_quality:reviewedRows('primary_quality')}} showHeading={false}>
      <RichNarrative id="summary:quality" value={`**行业改善并不普遍。** 29个非金融一级行业中，21个收入增长，11个收入与扣非利润率同步改善；7个行业利润率与现金流率同时提高。应收账款可比公司期末余额同比增加${n(arGrowth)}%，16个一级行业应收周转时间延长。`}/>
    </ReportSection>
    <ReportSection id="summary-forecast-findings" title="全年高增与价值排序" queryId="forecast_1" queryIds={['forecast_1','value_1']} sourceRowsByQuery={{forecast_1:p,value_1:v}} showHeading={false}>
      <RichNarrative id="summary:forecast" value="**全年归母利润高增集中在电子、有色金属和石油石化，综合价值排序则以煤炭、有色金属、石油石化居前。** 电子归母利润基准预测同比增长92.70%，综合名次为第7；煤炭归母利润预计增长27.22%，综合第1。增长榜反映业绩变化，综合排序同时计入10月30日估值、经营质量和模型内风险。食品饮料的综合名次为并列第5，归母利润仍预计下降5.60%，其排名更多来自估值、质量与风险维度。"/>
    </ReportSection>
    <ReportSection id="summary-secondary-findings" title="细分行业的价值与覆盖差异" queryId="value_2" queryIds={['value_2','forecast_2']} sourceRowsByQuery={{value_2:v2,forecast_2:reviewedRows('forecast_2').filter(r=>r.指标==='归母净利润')}} showHeading={false}>
      <RichNarrative id="summary:secondary" value="**二级行业综合比较中，航运港口、煤炭开采、工业金属居前。** 半导体归母利润基准预测增长215.09%，但本项可比公司仅覆盖当前已知收入的66.24%，综合评分未达到覆盖门槛。"/>
    </ReportSection>
    <Note id="summary:scope">财务沿2026年11月1日冻结版本；公司归属及估值固定2026年10月30日，东财2025年末分类体系。全年为条件预测，参考2024、2025两个第四季度；金融通用财务单列，不参加本轮预测和综合排序。</Note>
  </section>;
}
function ForecastLevel({level}){
  const {snapshot,reviewedRows}=useDataApp();const spec=snapshot.study.forecast,rows=pRows(reviewedRows,level),queryId='forecast_'+level;
  const income=ordered(rows,spec.tops[level+'_income']),profit=ordered(rows,spec.tops[level+'_profit']),leaders=profit.slice(0,3);
  const unusual=rows.filter(r=>r['全年利润增长（%）']==null),low=profit.filter(r=>r['本期已知收入覆盖（%）']<90||r.可比公司数<5);
  const d=ordered(reviewedRows(queryId).filter(r=>r.指标==='扣非净利润'),spec.tops[level+'_profit']);
  const title=level==='1'?'一级':'二级';
  return <section id={'forecast-level-'+level} className="sample-chapter forecast-chapter">
    <RichNarrative id={`forecast:${level}:heading`} value={`## 3.1.${level}　${title}行业全年高增预测`}/>
    <ReportSection id={`forecast-${level}-findings`} title={title+'全年基准预测'} queryId={queryId} sourceRows={rows} showHeading={false}>
      <RichNarrative id={`forecast:${level}:finding`} value={`按归母利润基准预测同比增速，${leaders.map(r=>`${r.行业}（${n(r['全年利润增长（%）'])}%）`).join('、')}居前。${level==='1'?'电子与有色金属预计增加归母利润1,617.08亿元和1,626.03亿元。':'汽车服务预计增长198.83%，对应利润增加4.79亿元；工业金属预计增加1,291.06亿元，增速与增量金额呈现不同侧重。'}`}/>
    </ReportSection>
    <div className="current-chart-pair">
      <Bars id={`forecast-income-growth-${level}`} queryId={queryId} rows={income} fields={['全年收入增长（%）']} title={'全年营业收入预测增长｜'+title} unit="%" percent/>
      <Bars id={`forecast-profit-growth-${level}`} queryId={queryId} rows={profit} fields={['全年利润增长（%）']} title={'全年归母利润预测增长｜'+title} unit="%" percent/>
    </div>
    {low.length>0&&<Note id={`forecast:${level}:coverage`}>{'增长榜内，'+low.map(r=>`${r.行业}${r.可比公司数}家可比公司，当前已知收入覆盖${n(r['本期已知收入覆盖（%）'])}%`).join('；')+'。预测对应上述公司范围。'}</Note>}
    <Note id={`forecast:${level}:scope`}>各行业先按自身可比公司合计金额再计算增长；一级主文前10、二级前15，真实同值并列全部保留。负利润、接近零基数及转亏情形在后文按状态与金额展示。</Note>
    <RichNarrative id={`forecast:${level}:composition-heading`} value="### 前三季实际与第四季度预测共同构成全年基准"/>
    <Bars id={`forecast-composition-${level}`} queryId={queryId} rows={profit} fields={['前三季实际（亿元）','第四季度基准预测（亿元）','全年基准预测（亿元）']} title={title+'高增行业归母利润构成'} note="2026全年基准=前三季实际+第四季度基准预测；亿元。负预测保留负柱，各行业使用归母模型可比公司。"/>
    <Bars id={`forecast-scenario-${level}`} queryId={queryId} rows={profit} fields={['全年基准预测（亿元）']} title={title+'行业归母利润模型情景范围'} range={['全年低情景（亿元）','全年高情景（亿元）']} colors={{'全年基准预测（亿元）':spec.predictionColor}} note="2026全年，亿元。线段为两种收入估计与两年季节利润率路径组合的低—高情景，不代表概率区间。"/>
    <RichNarrative id={`forecast:${level}:deducted-heading`} value="### 扣非利润预测补充反映持续盈利表现"/>
    <Bars id={`forecast-deducted-${level}`} queryId={queryId} rows={d} fields={['2025全年实际（亿元）','全年基准预测（亿元）']} title={title+'高增行业扣非净利润比较'} note="2025全年实际与2026全年基准预测，亿元；本图使用扣非模型公司范围，与前述归母模型分别固定。"/>
    <Note id={`forecast:${level}:deducted-limit`}>已识别的扣非Q4冲突沿原规则排除；尚未解释的历史扣非版本差异，仍可能影响扣非预测和综合评分。</Note>
    <RichNarrative id={`forecast:${level}:states-heading`} value="### 亏损与基数异常行业保留金额比较"/>
    {chunk(unusual).map((rs,i)=><div className="forecast-group" key={i}><Bars id={`forecast-states-${level}-${i}`} queryId={queryId} rows={rs} fields={['2025全年实际（亿元）','全年基准预测（亿元）']} title={title+'行业亏损状态与利润金额'} note="各行业两年使用同一批归母模型公司，亿元；未以负数或接近零的利润基数计算正常增长率。"/>
      <Note id={`forecast:${level}:states:${i}`}>{rs.map(r=>`${r.行业}：${r.利润变化状态}，利润${delta(r['全年增减（亿元）'])}亿元`).join('；')+'。'}</Note></div>)}
    <p className="group-index"><a href="#forecast-details">完整行业预测全览 ↓</a></p>
  </section>;
}
function CashForecast(){
  const {reviewedRows}=useDataApp();const rows=ordered(reviewedRows('forecast_1').filter(r=>r.指标==='经营现金流'),['煤炭','有色金属','石油石化','电子']);
  return <section className="sample-chapter forecast-chapter"><RichNarrative id="forecast:cash:heading" value="### 重点行业全年经营现金流预测"/>
    <Bars id="forecast-cash" queryId="forecast_1" rows={rows} fields={['前三季实际（亿元）','第四季度基准预测（亿元）','全年基准预测（亿元）']} title="重点一级行业经营现金流" note="2026全年基准=前三季实际+Q4预测，亿元；现金流采用独立模型公司范围，不与归母或扣非金额拼接计算比率。"/>
  </section>;
}
function ValueLevel({level}){
  const {snapshot,reviewedRows}=useDataApp();const limit=level==='1'?snapshot.study.forecast.primaryTop:snapshot.study.forecast.secondaryTop;
  const queryId='value_'+level,rows=reviewedRows(queryId),top=valueTop(rows,limit),eligible=rows.filter(r=>r.评分状态==='合格');
  const weights=ordered(reviewedRows('weights_'+level),top.map(r=>r.行业)),models=ordered(reviewedRows('model_weights_'+level),top.map(r=>r.行业));const name=level==='1'?'一级':'二级';
  const rawFields=['预测扣非盈利收益率（%）','预测收入增长（%）','预测扣非利润率变化（百分点）'];
  return <section id={'value-level-'+level} className="sample-chapter forecast-chapter">
    <RichNarrative id={`value:${level}:heading`} value={`## 3.2.${level}　${name}行业投资价值比较`}/>
    <ReportSection id={`value-${level}-findings`} title={name+'综合价值与分项'} queryId={queryId} sourceRows={rows} showHeading={false}>
      <RichNarrative id={`value:${level}:finding`} value={`**${eligible.length}个${name}行业具备综合评分资格。** ${top.slice(0,3).map(r=>`${r.行业}${n(r.综合得分)}分`).join('、')}居前。${level==='1'?'有色金属预测扣非盈利收益率8.64%，高于煤炭的5.49%；煤炭经营现金流率24.73%、模型内下行幅度0.39%，质量和风险分项支撑其综合领先。电子前景得分97.83分，但盈利收益率为2.50%，综合列第7。食品饮料与基础化工保留原并列第5名。':'航运港口预测扣非盈利收益率9.47%，经营现金流率28.23%，资产负债率40.43%；工业金属盈利收益率更高，为11.42%，但经营现金流率8.32%、资产负债率51.27%，综合得分低于航运港口。'}`}/>
    </ReportSection>
    <div className="current-chart-pair"><Bars id={`value-score-${level}`} queryId={queryId} rows={top} fields={['综合得分']} title={name+'行业综合得分'} unit="分" note="同层级原合格行业；四维各25%，原名次及并列保留，分数越高综合比较越有利。"/>
      <Dimensions id={`value-dimensions-${level}`} queryId={queryId} rows={top} title={name+'行业四维得分'}/></div>
    <RichNarrative id={`value:${level}:raw-heading`} value="### 估值收益率与盈利前景分别比较"/>
    <div className="forecast-raw-grid">{rawFields.map((field,i)=><Bars key={field} id={`value-raw-${level}-${i}`} queryId={queryId} rows={top} fields={[field]} title={field.replace('（百分点）','')} unit={i===2?'百分点':'%'} percent={i!==2} note="本图所有原值均来自该行业评分所用的同一批公司，不能与归母预测金额互相推导。"/>)}</div>
    <Note id={`value:${level}:raw-scope`}>预测扣非盈利收益率=评分同集全年扣非预测÷10月30日同集市值。质量维度由现金流率与扣非TTM净资产收益率构成，风险维度由资产负债率与模型内下行幅度构成；各维度内部两项等权。七项原值在各行业悬停及来源中保留，不同层级的得分分别标准化。</Note>
    <RichNarrative id={`value:${level}:sensitivity-heading`} value="### 权重变化下的排名稳定性"/>
    <div className="current-chart-pair"><Bars id={`value-weight-range-${level}`} queryId={'weights_'+level} rows={weights} fields={['基准名次']} range={['最好名次','最差名次']} title={name+'行业名次变化范围'} unit="名次" rankRange note="原85组四维权重组合，名次越小越靠前；保留同一完整候选组。"/>
      <Bars id={`value-weight-top-${level}`} queryId={'weights_'+level} rows={weights} fields={['前20%组合占比（%）']} title="进入同层级前20%的权重组合比例" unit="%" percent note="进入前20%的组合数÷85，不是上涨概率；截止名次并列全部纳入。"/></div>
    <Bars id={`value-model-ranks-${level}`} queryId={'model_weights_'+level} rows={models} fields={['季节法25%名次','季节法50%名次','季节法75%名次']} title={name+'行业收入估计方法变化下的名次'} unit="名次" note="分别沿用季节法25%、50%、75%的冻结结果，同一原合格候选组；名次越小越靠前。"/>
    <p className="group-index"><a href="#value-details">完整评分、原值及未评分原因 ↓</a><a href="#sensitivity-details">完整排名敏感性 ↓</a></p>
  </section>;
}
function HeadSensitivity(){
  const {reviewedRows}=useDataApp();const a=reviewedRows('head_companies_1'),b=reviewedRows('head_companies_2');
  const rows=[['一级行业',a],['二级行业',b]].map(([name,rs])=>({行业:name,'原合格行业数':rs.length,'剔除头部后失效行业数':rs.filter(r=>r.剔除头部后资格==='失效').length}));
  return <section id="head-sensitivity" className="sample-chapter forecast-chapter"><RichNarrative id="head:sensitivity:heading" value="### 剔除头部公司后，原评分名单不再具备比较条件"/>
    <ReportSection id="head-sensitivity-findings" title="头部公司影响" queryId="head_companies_1" queryIds={['head_companies_1','head_companies_2']} sourceRowsByQuery={{head_companies_1:a,head_companies_2:b}} showHeading={false}>
      <RichNarrative id="head:sensitivity:finding" value="剔除各行业2025全年收入前三家公司后，原24个一级、89个二级合格行业均不再满足评分资格，主要受收入覆盖门槛影响。该情形无法维持原候选组，因此没有可比的替代名次；不能据此重排剩余行业。"/>
    </ReportSection>
    <div className="current-chart-pair">{[a,b].map((source,i)=><Bars key={i} id={`head-sensitivity-counts-${i}`} queryId={'head_companies_'+(i+1)} rows={[rows[i]]} sourceRows={source} fields={['原合格行业数','剔除头部后失效行业数']} title={(i===0?'一级':'二级')+'原评分名单与剔除头部后的失效数量'} unit="个行业" note="剔除所属层级行业的前三大收入公司，仍以原行业收入作为覆盖分母。"/>)}</div>
  </section>;
}
export function ForecastChapters(){const {snapshot}=useDataApp();if(!available(snapshot))return null;return <><RichNarrative id="forecast:part-heading" value="## 3　2026全年业绩预期高增行业预测"/><ForecastLevel level="1"/><ForecastLevel level="2"/><CashForecast/><ValueLevel level="1"/><ValueLevel level="2"/><HeadSensitivity/></>;}
function ForecastHeat({id,queryId,rows,title}){
  const fields=['全年收入增长（%）','全年利润增长（%）'],plot=rows.flatMap(r=>fields.map(f=>({...r,项目:f==='全年收入增长（%）'?'营业收入增长':'归母利润增长',同比:r[f]})));
  const bound=Math.max(50,...plot.map(r=>Math.abs(r.同比??0)));
  const [chart]=chartConfigEntries({id,title,rows:plot,spec:{type:'heatmap',x:'项目',y:'行业',value:'同比',xOrder:['营业收入增长','归母利润增长'],yOrder:rows.map(r=>r.行业),reverseRows:true,colorDomain:[-bound,bound],
    colorBands:[{max:-50,color:'#a64252',legendGroup:'下降'},{max:-20,color:'#cb6d78',legendGroup:'下降'},{max:0,color:'#e9a6ae',legendGroup:'下降'},{max:Number.MIN_VALUE,color:'#a5a9b0',legendGroup:'持平'},{max:20,color:'#9cd5c9',legendGroup:'增长'},{max:50,color:'#46ac96',legendGroup:'增长'},{color:'#08745f',legendGroup:'增长'}],showValues:true,hideMissingCells:false,valueFormat:{style:'decimal',maximumFractionDigits:2}},height:110+rows.length*28});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={rows} description="2026全年基准预测较2025全年实际，%；每行业归母模型固定公司。深浅以20%、50%分档，原数值未截尾；利润基数不适用时留空、保留状态。" chartOptions={{tooltipContent:props=><Tip {...props} fields={['全年收入增长（%）','全年利润增长（%）','全年基准预测（亿元）','全年增减（亿元）']}/>}}/>;
}
export function ForecastDetails(){
  const {snapshot,reviewedRows}=useDataApp();if(!available(snapshot))return null;
  const primaryNames=reviewedRows('forecast_1').filter(r=>r.指标==='归母净利润').map(r=>r.行业);
  const groups=[...chunk(primaryNames).map((names,i)=>({level:'1',names,title:'一级行业 '+(i+1)})),...snapshot.study.heatGroups.map(g=>({level:'2',names:g.industries,title:g.parents.join(' · ')}))];
  const valueGroups=groups.map(g=>({...g,rows:reviewedRows('value_'+g.level).filter(r=>g.names.includes(r.行业)&&r.评分状态==='合格')})).filter(g=>g.rows.length);
  return <>
    <section id="forecast-details" className="sample-chapter forecast-chapter"><RichNarrative id="forecast:details:heading" value="## 预测附录：全部非金融行业全年基准与情景范围"/>
      <Note id="forecast:details:scope">全部29个一级、124个二级行业直接展开；各模型保持自身公司范围。热图为归母模型的收入和利润增长，金额图分别列归母、扣非与经营现金流，均为2026全年条件预测。</Note>
      {groups.map((g,i)=><div className="forecast-group" key={i}><RichNarrative id={`forecast:details:${i}:heading`} value={'### '+g.title}/>
        <ForecastHeat id={`forecast-details-growth-${i}`} queryId={'forecast_'+g.level} rows={ordered(pRows(reviewedRows,g.level),g.names)} title="全年营业收入与归母利润预测增长（%）"/>
        <div className="forecast-amount-grid">{['归母净利润','扣非净利润','经营现金流'].map((metric,j)=><Bars key={metric} id={`forecast-details-amount-${i}-${j}`} queryId={'forecast_'+g.level} rows={ordered(reviewedRows('forecast_'+g.level).filter(r=>r.指标===metric),g.names)} fields={['全年基准预测（亿元）']} range={['全年低情景（亿元）','全年高情景（亿元）']} title={metric+'｜全年基准与情景范围'} colors={{'全年基准预测（亿元）':snapshot.study.forecast.predictionColor}}/>)}</div>
      </div>)}
    </section>
    <section id="value-details" className="sample-chapter forecast-chapter"><RichNarrative id="value:details:heading" value="## 价值附录：完整综合评分、四维与七项原值"/>
      <Note id="value:details:scope">原24个一级、89个二级合格行业完整保留；各行业原综合名次显示于悬停，七项业务原值、公司数及收入覆盖可直接核对。各层级单独比较，未合格者在下方说明原因。</Note>
      {valueGroups.map((g,i)=><div className="forecast-group" key={i}><RichNarrative id={`value:details:${i}:heading`} value={'### '+g.title}/><div className="current-chart-pair">
        <Bars id={`value-details-score-${i}`} queryId={'value_'+g.level} rows={g.rows} fields={['综合得分']} title="完整合格行业综合得分" unit="分" note="保留原分数和并列名次，未重新打分；同层级分数越高越有利。"/>
        <Dimensions id={`value-details-dimensions-${i}`} queryId={'value_'+g.level} rows={g.rows} title="估值、前景、质量与风险分项"/>
      </div></div>)}
      <RichNarrative id="value:unqualified:heading" value="### 未评分行业及具体原因"/>
      {['1','2'].map(level=><ReportSection id={'value-unqualified-'+level} key={level} title="未评分原因" queryId={'value_'+level} sourceRows={reviewedRows('value_'+level).filter(r=>r.评分状态!=='合格')} showHeading={false}><RichNarrative id={`value:unqualified:${level}`} value={unqualifiedText(reviewedRows('value_'+level))}/></ReportSection>)}
    </section>
    <section id="sensitivity-details" className="sample-chapter forecast-chapter"><RichNarrative id="sensitivity:details:heading" value="## 敏感性附录：全部合格行业的名次变化"/>
      {['1','2'].flatMap(level=>chunk(reviewedRows('weights_'+level),30).map((rs,i)=><div className="forecast-group" key={level+i}><RichNarrative id={`sensitivity:details:${level}:${i}`} value={'### '+(level==='1'?'一级':'二级')+'行业 '+(i+1)}/>
        <div className="current-chart-pair"><Bars id={`sensitivity-details-weight-${level}-${i}`} queryId={'weights_'+level} rows={rs} fields={['基准名次']} range={['最好名次','最差名次']} title="85组权重下的名次范围" unit="名次" rankRange/>
        <Bars id={`sensitivity-details-model-${level}-${i}`} queryId={'model_weights_'+level} rows={ordered(reviewedRows('model_weights_'+level),rs.map(r=>r.行业))} fields={['季节法25%名次','季节法50%名次','季节法75%名次']} title="三种收入估计权重下的名次" unit="名次"/></div>
      </div>))}
    </section>
  </>;
}
