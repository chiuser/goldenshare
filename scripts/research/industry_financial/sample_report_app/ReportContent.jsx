import React from 'react';
import {RichNarrative, ReportSection, EvidenceChart, ChartTooltip, chartConfigEntries, useDataApp} from '../../data-app-public.jsx';
import './report.css';

const nr=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
const signed=v=>(v>0?'+':'')+nr(v);
const rateText=(v,unit='%')=>v!==0 && Math.abs(v)<0.01 ? `${v>0?'小幅增加':'小幅下降'}（不足0.01${unit}）` : signed(v)+unit;
const stateCopy=[
  {title:'收入增长 · 利润率提高',tone:'good'},
  {title:'收入增长 · 利润率下降',tone:'mixed'},
  {title:'收入下降 · 利润率提高',tone:'repair'},
  {title:'收入下降 · 利润率下降',tone:'weak'}
];
function quadrantTip(props){
  const row=props.payload?.find(p=>p.payload?.行业)?.payload;
  if(!props.active || !row)return null;
  return <ChartTooltip active label={row.行业} details={[
    {label:'经营状态',value:row.经营状态},
    {label:'收入同比',value:rateText(row['收入增长（%）'])},
    {label:'扣非利润率变化',value:rateText(row['利润率变化（百分点）'],'个百分点')},
    {label:'每100元收入的扣非利润',value:`${nr(row['上年扣非利润率（%）'])}元 → ${nr(row['本期扣非利润率（%）'])}元`},
    {label:'当期盈亏',value:row.盈亏情况},
    {label:'可比公司',value:`${row.可比公司数}家`},
    {label:'当期已知收入覆盖',value:nr(row['当期已知收入覆盖（%）'])+'%'}
  ]}/>;
}
function profitChange(oldValue,newValue,oldRevenue,nearZero){
  if(oldValue>0 && oldRevenue>0 && oldValue/oldRevenue<nearZero)return `上年利润基数较低，归母净利润${newValue>=oldValue?'增加':'减少'}${nr(Math.abs(newValue-oldValue))}亿元`;
  if(oldValue>0 && newValue>=0)return `归母净利润同比${newValue>=oldValue?'增长':'下降'}${nr(Math.abs(newValue/oldValue-1)*100)}%`;
  if(oldValue<=0 && newValue>0)return '归母净利润扭亏为盈';
  if(oldValue>=0 && newValue<0)return '归母净利润由盈转亏';
  if(oldValue<0 && newValue<0)return `归母净利润${newValue>oldValue?'亏损收窄':'亏损扩大'}`;
  return '归母净利润处于盈亏平衡附近';
}
function barData(rows,field){
  const max=Math.max(...rows.map(r=>Math.abs(r[field])));
  const scale=max>=10000?10000:1,unit=scale===10000?'万亿元':'亿元';
  const wide={比较期:'前三季度'};
  for(const row of rows)wide[row.年份]=row[field]/scale;
  return {rows:[wide],unit,values:rows.map(r=>r[field]/scale)};
}
function YearBar({id, title, sourceRows,field,height=310}){
  const {snapshot,visible}=useDataApp();
  if(!visible(id))return null;
  const data=barData(sourceRows,field);
  const digits=Math.max(...data.values.map(Math.abs))>=1000?0:2;
  const spec={type:'bar',x:'比较期',y:'2024',fields:['2024','2025','2026'],startAtZero:true,showValues:true,showLegend:true,
    yLabel:data.unit,colors:snapshot.study.yearColors,valueFormat:{style:'decimal',maximumFractionDigits:digits}};
  return <EvidenceChart id={id} title={title} queryId="history_comparison" rows={data.rows} sourceRows={sourceRows} spec={spec} height={height}
    description={`各年前三季度，金额单位：${data.unit}；三年使用同一批公司。`} />;
}
function CurrentChapter(){
  const {snapshot,reviewedRows,visible}=useDataApp();
  const all=reviewedRows('industry_quadrant');
  const rows=all;
  const [chart]=chartConfigEntries({id:'industry-quadrant',title:'一级行业景气四象限',rows,spec:snapshot.study.quadrantSpec,height:560});
  const counts=snapshot.study.counts;
  const up=counts[snapshot.study.states[0]],squeezed=counts[snapshot.study.states[1]];
  return <section className="sample-chapter" id="current-chapter">
    <RichNarrative id="current:heading" value="## 01｜一级行业的收入增长，利润率跟上了吗？"/>
    <ReportSection id="quadrant-findings" title="收入增长与盈利改善" queryId="industry_quadrant" sourceRows={all} showHeading={false}>
      <RichNarrative id="current:lead" value={`**21个行业收入增长，但只有${up}个同时提高了扣非利润率。** 另有${squeezed}个行业收入增长、利润率下降；仅看收入增速，会高估这些行业的经营改善。比较期间为2026年前三季度与2025年同期。`}/>
    </ReportSection>
    <div className="state-cards" data-reviewed-rows>
      {stateCopy.map((c,i)=>{const label=snapshot.study.states[i];return <div key={label} className={`state-card ${c.tone}`}>
        <span className="state-count">{counts[label]}<small>个行业</small></span><span className="state-title">{c.title}</span>
      </div>})}
    </div>
    {visible('industry-quadrant') && <EvidenceChart {...chart} queryId="industry_quadrant" sourceRows={rows} height={560}
      description="29个非金融一级行业。横轴为收入同比，纵轴为扣非净利润率同比变化，两个坐标使用相同可比公司。"
      chartOptions={{tooltipContent:quadrantTip}}
      renderPlot={plot=><div className="quadrant-layout"><div className="quad-caption top"><span>↖ 收入下降 · 利润率提高</span><span>收入增长 · 利润率提高 ↗</span></div>{plot}<div className="quad-caption bottom"><span>↙ 收入下降 · 利润率下降</span><span>收入增长 · 利润率下降 ↘</span></div><div className="quadrant-legend" aria-label="四象限图例"><span><i className="legend-point"/>一级行业</span><span><i className="legend-zero"/>零线：收入或利润率同比持平</span></div></div>}/>
    }
    <RichNarrative id="current:interpretation" value="**电子、有色金属收入与利润率同步改善；食品饮料增收但利润率承压。** 房地产利润率略有提高，仍然亏损。电力设备利润率下降不足0.01个百分点，接近零线。"/>
    <RichNarrative id="current:scope" className="sample-note" value="范围：29个非金融一级行业；银行、非银金融不在本图。扣非利润率为扣除非经常性损益后的归母净利润占收入的比例。各行业按两期均可比的公司汇总，不直接平均各公司增速。"/>
  </section>;
}
function HistoryChapter(){
  const {snapshot,reviewedRows}=useDataApp();
  const industry=snapshot.study.defaultIndustry;
  const history=reviewedRows('history_comparison');const rows=history.filter(r=>r.行业===industry).sort((a,b)=>a.年份.localeCompare(b.年份));
  const [a,b,c]=rows;
  const growth=(c['收入（亿元）']/b['收入（亿元）']-1)*100;
  const oldGrowth=(b['收入（亿元）']/a['收入（亿元）']-1)*100;
  return <section className="sample-chapter history-chapter" id="history-chapter">
    <RichNarrative id="history:heading" value="## 02｜三年前三季度，收入与利润怎样变化？"/>
    <ReportSection id="history-findings" title="2024—2026年同期经营变化" queryId="history_comparison" sourceRows={rows} showHeading={false}>
      <RichNarrative id={`history:change:${industry}`} value={`**2026年前三季度，非金融整体收入同比增长${nr(growth)}%，${profitChange(b['归母净利润（亿元）'],c['归母净利润（亿元）'],b['收入（亿元）'],snapshot.study.nearZeroProfit)}。** 2025年收入同比${oldGrowth>=0?'增长':'下降'}${nr(Math.abs(oldGrowth))}%；${profitChange(a['归母净利润（亿元）'],b['归母净利润（亿元）'],a['收入（亿元）'],snapshot.study.nearZeroProfit)}。`}/>
    </ReportSection>
    <div className="history-main-grid">
      <YearBar id="history-revenue" title={`${industry}｜营业收入`} sourceRows={rows} field="收入（亿元）"/>
      <YearBar id="history-profit" title={`${industry}｜归母净利润`} sourceRows={rows} field="归母净利润（亿元）"/>
    </div>
    <RichNarrative id="history:featured-heading" value="### 行业之间的利润分化\n\n电子利润持续扩张；煤炭回升，尚未恢复到2024年同期；食品饮料连续下滑，农林牧渔由盈转亏。"/>
    <div className="history-feature-grid">
      {snapshot.study.featured.map((name,i)=>{const rs=history.filter(r=>r.行业===name).sort((a,b)=>a.年份.localeCompare(b.年份));return <div className="history-feature" key={name}>
        <YearBar id={`history-feature-${i}`} title={`${name}｜归母净利润`} sourceRows={rs} field="归母净利润（亿元）" height={250}/>
        <RichNarrative id={`history:feature:${name}`} value={`${profitChange(rs[1]['归母净利润（亿元）'],rs[2]['归母净利润（亿元）'],rs[1]['收入（亿元）'],snapshot.study.nearZeroProfit)}。2026年收入同比${rs[2]['收入（亿元）']>=rs[1]['收入（亿元）']?'增长':'下降'}${nr(Math.abs(rs[2]['收入（亿元）']/rs[1]['收入（亿元）']-1)*100)}%。`}/>
      </div>})}
    </div>
    <RichNarrative id="history:scope" className="sample-note" value="比较口径：三年均为1—9月，同一批5,275家非金融公司。各行业图使用各自金额刻度；负柱表示亏损。财报为2026年11月1日冻结版本；与四象限的可比公司范围可能不同。"/>
  </section>;
}
export function ReportContent(){
  const {appTitle,canEdit,mode,setAppTitle}=useDataApp();
  return <article className="report-content chapter-samples">
    <header className="sample-hero"><RichNarrative id="samples:eyebrow" value="A股行业财务分析 · 2026年前三季度"/>
      <h1 data-data-app-title contentEditable={canEdit && mode==='edit'} suppressContentEditableWarning onBlur={canEdit && mode==='edit'?e=>setAppTitle(e.currentTarget.textContent?.trim() || appTitle):undefined}>{appTitle}</h1>
      <nav className="sample-nav" aria-label="样章目录"><a href="#current-chapter">01　一级行业景气四象限</a><a href="#history-chapter">02　三年前三季度对比</a></nav>
    </header>
    <CurrentChapter/><HistoryChapter/>
  </article>;
}
