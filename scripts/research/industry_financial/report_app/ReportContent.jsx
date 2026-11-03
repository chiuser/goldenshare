import React from 'react';
import {RichNarrative, ReportSection, EvidenceChart, ChartTooltip, chartConfigEntries, useDataApp} from '../../data-app-public.jsx';
import './report.css';
import {HistoryChapters,HistoryDetails} from './HistoryChapters.jsx';
import {ExecutiveSummary,ForecastChapters,ForecastDetails} from './ForecastChapters.jsx';

const nr=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
const signed=v=>(v>0?'+':'')+nr(v);
const value=v=>v===null||v===undefined?'暂无可比数据':nr(v);
const ratio=(a,b)=>b>0?(a/b-1)*100:null;
const sorted=(rows,field)=>[...rows].sort((a,b)=>(b[field]??-Infinity)-(a[field]??-Infinity));
const precision=v=>v!==0&&Math.abs(v)<.01?(v>0?'增加不足0.01':'下降不足0.01'):signed(v);
const stateTitles=['收入增长 · 利润率提高','收入增长 · 利润率下降','收入下降 · 利润率提高','收入下降 · 利润率下降'];
const tones=['good','mixed','repair','weak'];
function tooltipFor(fields,unit='',options={}){
  return props=>{
    const row=props.payload?.find(p=>p.payload?.行业)?.payload;
    if(!props.active||!row)return null;
    const details=fields.map(field=>({label:field,value:row[field]===null||row[field]===undefined?'暂无可比数据':precision(row[field]*(options.fraction?100:1))+unit}));
    if(options.topNames&&row.前三大公司)details.unshift({label:'前三大公司',value:row.前三大公司});
    if(options.receivable){
      for(const field of ['2025年9月末应收账款（亿元）','2026年9月末应收账款（亿元）'])details.push({label:field,value:value(row[field])+(row[field]==null?'':'亿元')});
      details.push({label:'应收账款同比',value:value(row['应收账款同比（%）'])+(row['应收账款同比（%）']==null?'':'%')});
    }
    if(row.所属一级行业)details.unshift({label:'所属一级行业',value:row.所属一级行业});
    if(row.单位)details.unshift({label:row.指标,value:value(row.数值)+row.单位});
    if(row.可比公司数!==undefined)details.push({label:'可比公司',value:`${row.可比公司数}家`});
    const coverage=row['本期已知收入覆盖（%）']??row['当期已知收入覆盖（%）']??row['已知营业总收入覆盖（%）'];
    if(coverage!==undefined)details.push({label:'本期已知收入覆盖',value:value(coverage)+'%'});
    if(row['本期已知应收余额覆盖（%）']!==undefined)details.push({label:'本期已知应收余额覆盖',value:value(row['本期已知应收余额覆盖（%）'])+'%'});
    return <ChartTooltip active label={row.行业} details={details}/>;
  };
}
function Quadrant(){
  const {snapshot,reviewedRows,visible}=useDataApp();const rows=reviewedRows('industry_quadrant');
  const [chart]=chartConfigEntries({id:'industry-quadrant',title:'一级行业景气四象限',rows,spec:snapshot.study.quadrantSpec,height:560});
  if(!visible('industry-quadrant'))return null;
  return <EvidenceChart {...chart} queryId="industry_quadrant" sourceRows={rows}
    description="2026年1—9月较2025年同期。29个非金融一级行业；两轴使用同一批收入、扣非利润均可比的公司。"
    chartOptions={{tooltipContent:tooltipFor(['收入增长（%）','利润率变化（百分点）','本期扣非利润率（%）','本期扣非利润（亿元）'])}}
    renderPlot={plot=><div className="quadrant-layout"><div className="quad-caption top"><span>↖ 收入下降 · 利润率提高</span><span>收入增长 · 利润率提高 ↗</span></div>{plot}<div className="quad-caption bottom"><span>↙ 收入下降 · 利润率下降</span><span>收入增长 · 利润率下降 ↘</span></div><div className="quadrant-legend" aria-label="四象限图例"><span><i className="legend-point"/>一级行业</span><span><i className="legend-zero"/>零线：收入或利润率同比持平</span></div></div>}/>;
}
function Bars({id,queryId,title,fields,rows:provided,unit='',note,height,percentageLabels=false,topNames=false,receivable=false}){
  const {snapshot,reviewedRows,visible}=useDataApp();const sourceRows=provided||reviewedRows(queryId);
  if(!visible(id))return null;
  const rows=sourceRows.filter(r=>fields.some(f=>r[f]!==null&&r[f]!==undefined)).map(r=>percentageLabels?{...r,...Object.fromEntries(fields.map(f=>[f,r[f]==null?null:r[f]/100]))}:r);
  const colors=Object.fromEntries(fields.map((f,i)=>[f,i?snapshot.study.colors.teal:snapshot.study.colors.blue]));
  const values=rows.flatMap(r=>fields.map(f=>r[f]).filter(v=>v!=null));
  const low=Math.min(0,...values),high=Math.max(0,...values),padding=(high-low||1)*.75;
  const spec={type:'horizontalBar',x:fields.length>1?fields:fields[0],y:'行业',showLegend:true,showValues:true,stackable:false,
    xLabel:unit,colors,valueFormat:{style:percentageLabels?'percent':'decimal',maximumFractionDigits:2},yOrder:rows.map(r=>r.行业),...(receivable?{xDomain:[low-padding,high+padding]}:{})};
  const [chart]=chartConfigEntries({id,title,rows,spec,height:height||Math.max(250,rows.length*(fields.length>1?29:23)+60)});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={sourceRows} description={note}
    chartOptions={{tooltipContent:tooltipFor(fields,unit,{fraction:percentageLabels,topNames,receivable})}}>{fields.length===1&&<div className="business-legend" aria-label="图例"><i style={{background:colors[fields[0]]}}/>{fields[0]}</div>}</EvidenceChart>;
}
function SourceNote({id,children}){return <RichNarrative id={id} className="sample-note" value={children}/>;}
function Receivables({level}){
  const {snapshot,reviewedRows}=useDataApp();const queryId=level==='primary'?'primary_receivable_balance':'secondary_receivable_balance';
  if(!snapshot.queries[queryId])return null;
  const rows=reviewedRows(queryId),ordered=sorted(rows,'应收账款增减（亿元）'),positive=ordered.filter(r=>r['应收账款增减（亿元）']>0),negative=[...ordered].reverse().filter(r=>r['应收账款增减（亿元）']<0);
  const total=field=>rows.reduce((sum,r)=>sum+(r[field]??0),0),now=total('2026年9月末应收账款（亿元）'),prior=total('2025年9月末应收账款（亿元）');
  const highlights=rs=>rs.slice(0,3).map(r=>`${r.行业}${nr(Math.abs(r['应收账款增减（亿元）']))}亿元`).join('、');
  return <div className="receivable-section">
    <RichNarrative id={`receivable:${level}:heading`} value={level==='primary'?'### 一级行业应收账款同比增加，行业间存在差异':'### 二级行业应收账款增加与回落分化'}/>
    <ReportSection id={`receivable-${level}-findings`} queryId={queryId} title="应收账款期末余额变动" sourceRows={rows} showHeading={false}>
      <RichNarrative id={`receivable:${level}:finding`} value={level==='primary'?`**非金融可比公司的应收账款由${nr(prior)}亿元增至${nr(now)}亿元，同比${now>=prior?'增加':'减少'}${nr(Math.abs(now-prior))}亿元（${nr(Math.abs(ratio(now,prior)))}%）。** ${positive.length}个一级行业余额增加，增加额较大的包括${highlights(positive)}；回落额较大的包括${highlights(negative)}。`:`**124个非金融二级行业中，${positive.length}个应收账款余额增加、${negative.length}个减少。** 增加额较大的包括${highlights(positive)}；回落额较大的包括${highlights(negative)}。`}/>
    </ReportSection>
    {level==='primary'?<Bars id="primary-receivable-balance" queryId={queryId} title="一级行业应收账款同比增减额" fields={['应收账款增减（亿元）']} rows={ordered} unit="亿元" receivable note="2026年9月末较2025年9月末；正值为余额增加，负值为减少。"/>:
      <div className="contribution-grid">{snapshot.study.heatGroups.map((group,i)=><Bars key={i} id={`secondary-receivable-balance-${i}`} queryId={queryId} title={group.parents.join(' · ')} fields={['应收账款增减（亿元）']} rows={rows.filter(r=>group.industries.includes(r.行业))} unit="亿元" receivable note="应收账款同比增减额；2026年9月末较2025年9月末。"/>)}</div>}
    <SourceNote id={`receivable:${level}:scope`}>应收账款为两年9月30日的期末余额，增减按两期应收均有效的同一批公司计算，保留原缺报与可比性排除；与收入和周转天数图的公司范围可能不同。金额单位亿元，不含金融行业。</SourceNote>
  </div>;
}
function FinanceChart({level,field,id,title}){
  const {snapshot,reviewedRows,visible}=useDataApp();if(!visible(id))return null;
  const sourceRows=reviewedRows('financial_current').filter(r=>r.层级===level),names=[...new Set(sourceRows.map(r=>r.行业))];
  const rows=names.map(name=>{const rs=sourceRows.filter(r=>r.行业===name),a=rs.find(r=>r.年份==='2025'),b=rs.find(r=>r.年份==='2026');return {行业:name,'2025年':a[field],'2026年':b[field],可比公司数:b.可比公司数,'已知营业总收入覆盖（%）':b['已知营业总收入覆盖（%）']};});
  const [chart]=chartConfigEntries({id,title,rows,spec:{type:'horizontalBar',x:['2025年','2026年'],y:'行业',showLegend:true,showValues:true,stackable:false,
    xLabel:'亿元',colors:{'2025年':snapshot.study.yearColors['2025'],'2026年':snapshot.study.yearColors['2026']},valueFormat:{style:'decimal',maximumFractionDigits:0}},height:Math.max(260,names.length*65+80)});
  return <EvidenceChart {...chart} queryId="financial_current" sourceRows={sourceRows}
    description="两个年度均为前三季度；两期营业总收入、归母利润使用同一批公司。金额单位：亿元。"
    chartOptions={{tooltipContent:tooltipFor(['2025年','2026年'],'亿元')}}/>;
}
function SectorHeat({queryId,group,index,title}){
  const {snapshot,reviewedRows,visible}=useDataApp();const id=`${queryId}-${index}`;
  if(!visible(id))return null;
  const rows=reviewedRows(queryId).filter(r=>group.industries.includes(r.行业));
  const bound=snapshot.study.heatDomains[queryId][1];
  const colorBands=[{max:-bound*2/3,color:'#a64252',legendGroup:'减少'},{max:-bound/3,color:'#cb6d78',legendGroup:'减少'},{max:0,color:'#e9a6ae',legendGroup:'减少'},
    {max:Number.MIN_VALUE,color:'#a5a9b0',legendGroup:'持平'},{max:bound/3,color:'#9cd5c9',legendGroup:'增加'},{max:bound*2/3,color:'#46ac96',legendGroup:'增加'},{color:'#08745f',legendGroup:'增加'}];
  const [chart]=chartConfigEntries({id,title,rows,spec:{type:'heatmap',x:'指标',y:'行业',value:'数值',
    yOrder:group.industries,reverseRows:true,yLabel:'行业',showYAxisLabel:true,colorDomain:snapshot.study.heatDomains[queryId],colorBands,showValues:true,hideMissingCells:false,missingValues:'gap',valueFormat:{style:'decimal',maximumFractionDigits:4}},height:90+group.industries.length*27});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={rows} description={queryId==='secondary_income'?'2026年前三季收入同比，%。':'2026年前三季较上年同期变化，百分点。'} chartOptions={{tooltipContent:tooltipFor([])}}/>;
}
function CurrentPrimary(){
  const {snapshot,reviewedRows}=useDataApp();const s=snapshot.study.stats;
  const profit=sorted(reviewedRows('primary_profit'),'归母利润增减（亿元）'),leaders=profit.slice(0,3);
  const leading=leaders.reduce((v,r)=>v+r['归母利润增减（亿元）'],0),others=s.profit_delta-leading;
  const quality=reviewedRows('primary_quality'),joint=quality.filter(r=>r['扣非利润率变化（百分点）']>0&&r['经营现金流率变化（百分点）']>0);
  const receiv=sorted(reviewedRows('primary_receivable'),'周转天数变化（天）'),inventory=sorted(reviewedRows('primary_inventory'),'周转天数变化（天）');
  const breadth=sorted(reviewedRows('primary_breadth'),'利润改善公司比例（%）');const broadCount=breadth.filter(r=>r['利润改善公司比例（%）']>50).length;
  const concentrated=profit.filter(r=>r['归母利润增减（亿元）']>0&&r['前三大收入公司贡献（亿元）']>r['归母利润增减（亿元）']);
  const capex=sorted(reviewedRows('primary_capex'),'现金流扣除资本开支（亿元）');
  return <section id="current-primary" className="sample-chapter">
    <RichNarrative id="current:heading" value="## 2.1.1　一级行业：增长与盈利改善仍有分化"/>
    <ReportSection id="quadrant-findings" title="收入增长与盈利改善" queryId="industry_quadrant" sourceRows={reviewedRows('industry_quadrant')} showHeading={false}>
      <RichNarrative id="current:lead" value={`**29个非金融一级行业中，${s.revenue_up}个收入增长，${s.counts[snapshot.study.states[0]]}个收入与扣非利润率同步改善。** 另有${s.counts[snapshot.study.states[1]]}个行业增收但利润率下降，增长尚未普遍转化为盈利能力改善。`}/>
    </ReportSection>
    <div className="state-cards" data-reviewed-rows>{stateTitles.map((title,i)=><div className={`state-card ${tones[i]}`} key={title}><span className="state-count">{s.counts[snapshot.study.states[i]]}<small>个行业</small></span><span className="state-title">{title}</span></div>)}</div>
    <Quadrant/>
    <RichNarrative id="current:interpretation" value="**电子、有色金属收入与利润率同步改善；食品饮料增收但利润率承压。** 房地产利润率略有提高，仍然亏损；电力设备利润率下降不足0.01个百分点，接近零线。"/>
    <SourceNote id="current:scope">比较期间：2026年1—9月与2025年同期。扣非利润率＝扣非归母净利润÷营业收入；各行业先合计可比公司金额，再计算增速和利润率。行业分类采用东财2025年末体系，公司归属固定2026年10月30日。</SourceNote>
    <RichNarrative id="profit:heading" value="### 利润增量主要集中在电子、有色金属和石油石化"/>
    <ReportSection id="profit-findings" title="归母利润增减" queryId="primary_profit" sourceRows={profit} showHeading={false}>
      <RichNarrative id="profit:finding" value={`**${leaders.map(r=>r.行业).join('、')}合计增加归母利润${nr(leading)}亿元，高于非金融行业净增的${nr(s.profit_delta)}亿元。** 其余行业合计${others>=0?'增加':'减少'}${nr(Math.abs(others))}亿元，行业之间的增减抵消明显。`}/>
    </ReportSection>
    <Bars id="primary_profit" queryId="primary_profit" title="各一级行业归母净利润增减" fields={['归母利润增减（亿元）']} rows={profit} unit="亿元" note="2026年前三季度较2025年同期；收入与归母利润两期均可比的公司。负值为利润减少。"/>
    <SourceNote id="profit:scope">归母利润比较要求两期收入、归母利润同时可比；与四象限的收入、扣非利润公司范围可能不同。</SourceNote>
    <RichNarrative id="quality:heading" value="### 盈利与现金流同步改善的行业仍然有限"/>
    <ReportSection id="quality-findings" title="盈利与现金" queryId="primary_quality" sourceRows={quality} showHeading={false}>
      <RichNarrative id="quality:finding" value={`**扣非利润率与经营现金流率同时提高的有${joint.length}个行业**，包括${joint.map(r=>r.行业).join('、')}。行业收入增长、利润增加之外，现金流表现仍需分别观察。`}/>
    </ReportSection>
    <Bars id="primary_quality" queryId="primary_quality" title="利润率与经营现金流率的同比变化" fields={['扣非利润率变化（百分点）','经营现金流率变化（百分点）']} unit="百分点" note="2026年前三季度较2025年同期；两种比率使用收入、扣非及经营现金流均可比的同一批公司。"/>
    <RichNarrative id="turnover:heading" value="### 多数行业回款或库存占用时间延长"/>
    <ReportSection id="turnover-findings" title="应收与库存周转" queryId="primary_receivable" queryIds={['primary_receivable','primary_inventory']} sourceRowsByQuery={{primary_receivable:receiv,primary_inventory:inventory}} showHeading={false}>
      <RichNarrative id="turnover:finding" value={`应收账款周转天数延长的有**${s.receivable_longer}个行业**，${receiv[0].行业}延长${nr(receiv[0]['周转天数变化（天）'])}天；存货周转天数延长的有**${s.inventory_longer}个行业**，${inventory[0].行业}延长${nr(inventory[0]['周转天数变化（天）'])}天。周转时间延长，意味着相对于收入或成本，资金占用时间增加。`}/>
    </ReportSection>
    <div className="current-chart-pair">
      <Bars id="primary_receivable" queryId="primary_receivable" title="应收账款周转天数变化" fields={['周转天数变化（天）']} rows={receiv} unit="天" note="正值为回款周期延长，负值为缩短。"/>
      <Bars id="primary_inventory" queryId="primary_inventory" title="存货周转天数变化" fields={['周转天数变化（天）']} rows={inventory} unit="天" note="正值为存货周转变慢，负值为加快。"/>
    </div>
    <SourceNote id="turnover:scope">均按各年年初与9月末余额的平均值计算；应收以收入为分母，存货以营业成本为分母，前三季度按270天折算。两项使用各自的可比公司范围。</SourceNote>
    <Receivables level="primary"/>
    <RichNarrative id="breadth:heading" value="### 改善覆盖范围与头部公司贡献各有差异"/>
    <ReportSection id="breadth-findings" title="改善范围和利润贡献" queryId="primary_breadth" queryIds={['primary_breadth','primary_profit']} sourceRowsByQuery={{primary_breadth:breadth,primary_profit:profit}} showHeading={false}>
      <RichNarrative id="breadth:finding" value={`扣非利润同比改善覆盖过半公司的有**${broadCount}个行业**。${concentrated.length?`${concentrated.map(r=>r.行业).join('、')}的归母利润净增低于行业前三大收入公司的贡献，说明其余公司合计拖累了利润增量。`:'各行业前三大公司与其余公司的利润贡献存在明显差异。'}`}/>
    </ReportSection>
    <Bars id="primary_breadth" queryId="primary_breadth" title="扣非利润同比改善的公司比例" fields={['利润改善公司比例（%）']} rows={breadth} unit="%" percentageLabels note="超过50%表示在本项可比公司中，利润改善者过半。"/>
    <Bars id="primary_concentration" queryId="primary_profit" title="前三大收入公司与其余公司的归母利润贡献" fields={['前三大收入公司贡献（亿元）','其余公司贡献（亿元）']} rows={profit} unit="亿元" topNames note="前三大按2025年前三季度收入确定，名单固定；两组增减金额相加等于行业净增减。"/>
    <RichNarrative id="capital:heading" value="### 固定资产扩张与收入增长并不同步"/>
    <Bars id="primary_fixed" queryId="primary_fixed" title="固定资产与收入同比增长" fields={['收入增长（%）','固定资产增长（%）']} unit="%" note="2026年9月末固定资产较上年同期；收入为对应前三季度，两项采用同一批公司。"/>
    <ReportSection id="capex-findings" title="资本开支后的现金结余" queryId="primary_capex" sourceRows={capex} showHeading={false}>
      <RichNarrative id="capex:finding" value={`**${s.capex_positive}个行业的经营现金流能够覆盖当期资本开支。** ${capex[0].行业}结余${nr(capex[0]['现金流扣除资本开支（亿元）'])}亿元；${capex[capex.length-1].行业}缺口${nr(Math.abs(capex[capex.length-1]['现金流扣除资本开支（亿元）']))}亿元。`}/>
    </ReportSection>
    <Bars id="primary_capex" queryId="primary_capex" title="经营现金流扣除资本开支后的结余" fields={['现金流扣除资本开支（亿元）']} rows={capex} unit="亿元" note="2026年前三季度；正值为结余，负值为缺口。资本开支取购建固定资产、无形资产和其他长期资产支付的现金。"/>
  </section>;
}
function CurrentSecondary(){
  const {snapshot,reviewedRows}=useDataApp();const groups=snapshot.study.heatGroups,cases=reviewedRows('secondary_cases');
  return <section id="current-secondary" className="sample-chapter">
    <RichNarrative id="secondary:heading" value="## 2.1.2　二级行业：增长与经营压力呈现分化"/>
    <ReportSection id="secondary-findings" title="细分行业差异" queryId="secondary_cases" sourceRows={cases} showHeading={false}>
      <RichNarrative id="secondary:lead" value={`**一级行业内部，细分行业的利润变化并不一致。** ${cases.slice(0,2).map(r=>`${r.行业}归母利润${r['归母利润增减（亿元）']>=0?'增加':'减少'}${nr(Math.abs(r['归母利润增减（亿元）']))}亿元`).join('；')}。下列全览覆盖124个非金融二级行业，金融4个二级行业在后文单列。`}/>
    </ReportSection>
    <SourceNote id="secondary:scope">各图均为2026年前三季度与2025年同期比较。红色为减少，绿色为增加，深色表示幅度更大；每项指标使用全体细分行业统一、以0为中心的分档。灰色数值0为持平，灰色“—”为缺少可比数据。收入图单位为%，利润率与现金流率图单位为百分点。</SourceNote>
    <nav className="group-index" aria-label="二级行业分组目录">{groups.map((g,i)=><a key={i} href={`#secondary-group-${i}`}>{g.parents.join(' · ')}</a>)}</nav>
    {groups.map((g,i)=><div id={`secondary-group-${i}`} className="heat-group" key={i}>
      <RichNarrative id={`secondary:group:${i}`} value={`### ${g.parents.join(' · ')}`}/>
      <div className="current-heat-grid"><SectorHeat queryId="secondary_income" group={g} index={i} title="营业收入增长（%）"/><SectorHeat queryId="secondary_margin" group={g} index={i} title="扣非利润率变化（%）"/><SectorHeat queryId="secondary_cash" group={g} index={i} title="经营现金流率变化（%）"/></div>
    </div>)}
    <RichNarrative id="cases:heading" value="### 主要利润贡献与承压行业"/>
    <div className="case-grid">{cases.map(r=><ReportSection key={r.行业} id={`case-${r.行业}`} title={r.行业} queryId="secondary_cases" sourceRows={[r]} showHeading={false}>
      <RichNarrative id={`case:prose:${r.行业}`} value={`#### ${r.行业}\n\n${r.所属一级行业}下属行业。收入同比${r['收入同比（%）']>=0?'增长':'下降'}${nr(Math.abs(r['收入同比（%）']))}%，归母利润${r['归母利润增减（亿元）']>=0?'增加':'减少'}${nr(Math.abs(r['归母利润增减（亿元）']))}亿元。${r['归母利润（亿元）']<0?`当期亏损${nr(Math.abs(r['归母利润（亿元）']))}亿元。`:`当期归母利润${nr(r['归母利润（亿元）'])}亿元。`}`}/>
    </ReportSection>)}</div>
    <Receivables level="secondary"/>
  </section>;
}
function Financial(){
  const {reviewedRows}=useDataApp();const rows=reviewedRows('financial_current'),bank=rows.filter(r=>r.行业==='银行'),nonbank=rows.filter(r=>r.行业==='非银金融');
  const change=(rs,f)=>ratio(rs.find(r=>r.年份==='2026')[f],rs.find(r=>r.年份==='2025')[f]);
  return <section id="financial-sector" className="sample-chapter">
    <RichNarrative id="financial:heading" value="## 金融行业：银行增长，非银金融内部出现分化"/>
    <ReportSection id="financial-findings" title="金融收入与利润" queryId="financial_current" sourceRows={rows.filter(r=>r.层级==='一级')} showHeading={false}>
      <RichNarrative id="financial:lead" value={`银行营业总收入同比${change(bank,'营业总收入（亿元）')>=0?'增长':'下降'}${nr(Math.abs(change(bank,'营业总收入（亿元）')))}%，归母利润同比${change(bank,'归母净利润（亿元）')>=0?'增长':'下降'}${nr(Math.abs(change(bank,'归母净利润（亿元）')))}%；非银金融营业总收入同比${change(nonbank,'营业总收入（亿元）')>=0?'增长':'下降'}${nr(Math.abs(change(nonbank,'营业总收入（亿元）')))}%，归母利润同比${change(nonbank,'归母净利润（亿元）')>=0?'增长':'下降'}${nr(Math.abs(change(nonbank,'归母净利润（亿元）')))}%。`}/>
    </ReportSection>
    <div className="current-chart-pair"><FinanceChart id="finance-income-primary" level="一级" field="营业总收入（亿元）" title="金融一级行业｜营业总收入"/><FinanceChart id="finance-profit-primary" level="一级" field="归母净利润（亿元）" title="金融一级行业｜归母净利润"/></div>
    <RichNarrative id="financial:secondary-heading" value="### 金融二级行业：证券利润增加，保险利润下降"/>
    <div className="current-chart-pair"><FinanceChart id="finance-income-secondary" level="二级" field="营业总收入（亿元）" title="金融二级行业｜营业总收入"/><FinanceChart id="finance-profit-secondary" level="二级" field="归母净利润（亿元）" title="金融二级行业｜归母净利润"/></div>
    <SourceNote id="financial:scope">均为各年前三季度。银行42家、非银金融78家两期可比公司；金融使用营业总收入，与前文非金融营业收入分开比较。银行Ⅱ是银行一级的唯一二级，不与一级重复加总。</SourceNote>
  </section>;
}
function ContributionAppendix(){
  const {snapshot,reviewedRows}=useDataApp();const all=reviewedRows('secondary_profit');
  return <section id="contribution-details" className="sample-chapter">
    <RichNarrative id="appendix:heading" value="## 二级行业利润贡献全览"/>
    <SourceNote id="appendix:scope">2026年前三季度较2025年同期的归母净利润增减，单位：亿元。正值贡献利润增量，负值拖累；各组保留全部行业，金额刻度按本组设置。</SourceNote>
    <div className="contribution-grid">{snapshot.study.heatGroups.map((g,i)=><Bars key={i} id={`secondary-profit-${i}`} queryId="secondary_profit" title={g.parents.join(' · ')} fields={['归母利润增减（亿元）']} rows={all.filter(r=>g.industries.includes(r.行业))} unit="亿元"/>)}</div>
    <SourceNote id="report:scope">数据范围：2024年以来研究中的当前公司范围，本章比较2026年与2025年前三季度。财务为2026年11月1日冻结版本，公司归属固定10月30日。各图采用对应字段两期均有效的可比公司；原缺报及可比性排除规则保留，缺失不填零。金融4个二级与前述124个非金融二级合计覆盖固定分类树的128个二级行业。</SourceNote>
  </section>;
}
export function ReportContent(){
  const {appTitle,canEdit,mode,setAppTitle,snapshot}=useDataApp();
  return <article className="report-content chapter-samples industry-current">
    <header className="sample-hero"><RichNarrative id="samples:eyebrow" value="A股行业财务分析 · 2026年前三季度"/>
      <h1 data-data-app-title contentEditable={canEdit&&mode==='edit'} suppressContentEditableWarning onBlur={canEdit&&mode==='edit'?e=>setAppTitle(e.currentTarget.textContent?.trim()||appTitle):undefined}>{appTitle}</h1>
      <nav className="sample-nav" aria-label="报告目录">{snapshot.study.stage==='forecast'&&<a href="#report-summary">总结</a>}<a href="#current-primary">前三季一级行业</a><a href="#current-secondary">前三季二级行业</a><a href="#financial-sector">金融行业</a>{['history','forecast'].includes(snapshot.study.stage)&&<><a href="#history-primary">2024年以来一级行业</a><a href="#history-secondary">2024年以来二级行业</a><a href="#history-financial">金融历史</a></>}{snapshot.study.stage==='forecast'&&<><a href="#forecast-level-1">全年一级预测</a><a href="#forecast-level-2">全年二级预测</a><a href="#value-level-1">一级投资价值</a><a href="#value-level-2">二级投资价值</a></>}<a href="#contribution-details">二级利润贡献全览</a></nav>
    </header>
    <ExecutiveSummary/>{snapshot.study.stage==='forecast'&&<RichNarrative id="financial-overview:part-heading" value="## 2　各行业财务情况概览"/>}<CurrentPrimary/><CurrentSecondary/><Financial/><HistoryChapters/><ForecastChapters/><ContributionAppendix/><HistoryDetails/><ForecastDetails/>
  </article>;
}
