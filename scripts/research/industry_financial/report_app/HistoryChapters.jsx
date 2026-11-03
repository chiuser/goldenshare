import React from 'react';
import {RichNarrative,ReportSection,EvidenceChart,ChartTooltip,chartConfigEntries,useDataApp} from '../../data-app-public.jsx';
const yr=['2024','2025','2026'];
const num=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
const sign=v=>(v>0?'+':'')+num(v);
const grow=(a,b)=>b>0?(a/b-1)*100:null;
const money='归母净利润（亿元）',revenue='营业收入（亿元）';
function Note({id,children}){return <RichNarrative id={id} className="sample-note" value={children}/>;}
function Hover({active,payload,label}){
  if(!active||!payload?.length)return null;
  const row=payload.find(x=>x.payload)?.payload;if(!row)return null;
  const details=[];
  for(const y of yr){if(row[y+'年']!==undefined)details.push({label:y+'年',value:row[y+'年']==null?'尚无实际':num(row[y+'年'])+(row.展示单位||'亿元')});}
  if(row.数值!==undefined){details.push({label:row.指标,value:row.数值==null?'—':sign(row.数值)+'%'});if(row.数值==null)details.push({label:'利润状态',value:row.利润变化状态});}
  if(row.年份){details.push({label:'比较期间',value:row.年份+(row.单季?'年'+row.季度:'年前三季度')});details.push({label:'归母利润',value:num(row[money])+'亿元'});if(row['归母利润增减（亿元）']!=null)details.push({label:'归母利润同比增减',value:sign(row['归母利润增减（亿元）'])+'亿元'});}
  if(row.可比公司数!==undefined)details.push({label:'可比公司数',value:row.可比公司数+'家'});
  if(row.覆盖说明)details.push({label:'已知累计收入覆盖',value:row.覆盖说明});
  if(row['已知累计收入覆盖（%）']!==undefined)details.push({label:'当期已知累计收入覆盖',value:num(row['已知累计收入覆盖（%）'])+'%'});
  return <ChartTooltip active label={row.行业||label} details={details}/>;
}
function AmountBars({id,queryId,rows,field,title,scale=1,unit='亿元'}){
  const {snapshot,visible}=useDataApp();if(!visible(id))return null;
  const names=[...new Set(rows.map(r=>r.行业))];
  const display=names.map(name=>{const rs=rows.filter(r=>r.行业===name),out={行业:name,可比公司数:rs[0].可比公司数,展示单位:unit};
    for(const y of yr){const r=rs.find(v=>v.年份===y);out[y+'年']=r?.[field]==null?null:r[field]/scale;}
    out.覆盖说明=rs.filter(r=>r['已知累计收入覆盖（%）']!=null).map(r=>`${r.年份}年${num(r['已知累计收入覆盖（%）'])}%`).join('；');return out;});
  const fields=yr.map(y=>y+'年'),values=display.flatMap(r=>fields.map(f=>r[f]).filter(v=>v!=null));
  const low=Math.min(0,...values),high=Math.max(0,...values),pad=(high-low||1)*.5;
  const [chart]=chartConfigEntries({id,title,rows:display,height:Math.min(800,Math.max(240,names.length*40+110)),spec:{type:'horizontalBar',x:fields,y:'行业',showLegend:true,showValues:names.length<=4,stackable:false,
    colors:Object.fromEntries(yr.map(y=>[y+'年',snapshot.study.yearColors[y]])),xLabel:unit,xDomain:[low<0?low-pad:0,high+pad],valueFormat:{style:'decimal',maximumFractionDigits:2}}});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={rows} description={`各年1—9月，三个年份同一批公司；单位：${unit}。`} chartOptions={{tooltipContent:props=><Hover {...props}/>}}/>;
}
function Trend({id,queryId,rows,field,title,scale=1,unit='亿元'}){
  const {snapshot,visible}=useDataApp();if(!visible(id))return null;
  const plot=['Q1','Q2','Q3','Q4'].map(q=>{const v={季度:q,行业:rows[0].行业,可比公司数:rows[0].可比公司数,展示单位:unit};
    for(const y of yr){const row=rows.find(r=>r.年份===y&&r.季度===q);v[y+'年']=row?.[field]==null?null:row[field]/scale;}
    return v;});
  const [chart]=chartConfigEntries({id,title,rows:plot,height:290,spec:{type:'line',x:'季度',xScale:'category',y:yr.map(y=>y+'年'),showLegend:true,showValues:false,yLabel:unit,
    colors:Object.fromEntries(yr.map(y=>[y+'年',snapshot.study.yearColors[y]])),valueFormat:{style:'decimal',maximumFractionDigits:2}}});
  return <EvidenceChart {...chart} queryId={queryId} sourceRows={rows} description={`单季金额；2024Q1—2026Q3，共同${rows[0].可比公司数}家公司。2026Q4尚无实际。单位：${unit}。`} chartOptions={{tooltipContent:props=><Hover {...props}/>}}/>;
}
function Heat({id,queryId,names,field,title,year=null}){
  const {snapshot,reviewedRows,visible}=useDataApp();if(!visible(id))return null;
  const quarterly=queryId.includes('quarter');
  const all=reviewedRows(queryId),full=all.filter(r=>r.年份!=='2024'),sourceRows=all.filter(r=>names.includes(r.行业));
  const shown=sourceRows.filter(r=>r.年份!=='2024'&&(!year||r.年份===year));
  const rows=shown.map(r=>({...r,单季:quarterly,比较期间:quarterly?r.季度:r.年份+'年前三季',指标:field,数值:r[field]}));
  const bound=Math.max(1,...full.map(r=>Math.abs(r[field]??0)));
  const bands=[{max:-50,color:'#a64252',legendGroup:'下降'},{max:-20,color:'#cb6d78',legendGroup:'下降'},{max:0,color:'#e9a6ae',legendGroup:'下降'},
    {max:Number.MIN_VALUE,color:'#a5a9b0',legendGroup:'持平'},{max:20,color:'#9cd5c9',legendGroup:'增长'},{max:50,color:'#46ac96',legendGroup:'增长'},{color:'#08745f',legendGroup:'增长'}];
  const [chart]=chartConfigEntries({id,title,rows,height:110+names.length*28,spec:{type:'heatmap',x:'比较期间',y:'行业',value:'数值',
    xOrder:year?(year==='2025'?['Q1','Q2','Q3','Q4']:['Q1','Q2','Q3']):['2025年前三季','2026年前三季'],yOrder:names,reverseRows:true,
    yLabel:'行业',showYAxisLabel:true,colorDomain:[-bound,bound],colorBands:bands,hideMissingCells:false,missingValues:'gap',showValues:true,valueFormat:{style:'decimal',maximumFractionDigits:4}}});
  const exceptional=field==='归母利润同比（%）'?shown.filter(r=>r[field]==null):[];
  return <div className="history-heat-item"><EvidenceChart {...chart} queryId={queryId} sourceRows={sourceRows}
    description={`${quarterly?year+'年单季同比':'各年前三季同比'}，%；${quarterly?'11期':'三年同期'}使用同一批公司。颜色依20%和50%分档，超过50%为最深色，数值未截尾。`}
    chartOptions={{tooltipContent:props=><Hover {...props}/>}}/>
    {exceptional.length>0&&<Note id={id+':states'}>{exceptional.map(r=>`${r.行业}（${quarterly?r.年份+r.季度:r.年份}）：${r.利润变化状态}，利润${sign(r['归母利润增减（亿元）'])}亿元`).join('；')+'。'}</Note>}
  </div>;
}
function GrowthGroups({level}){
  const {snapshot}=useDataApp();const queryId='history_'+level;
  const groups=level==='primary'?snapshot.study.history.primaryGroups.map((names,i)=>({industries:names,parents:[`一级行业 ${i+1}`]})):snapshot.study.heatGroups;
  return <div className="history-growth-groups">{groups.map((g,i)=><div key={i} className="history-group" id={`history-${level}-group-${i}`}>
    {level==='secondary'&&<RichNarrative id={`history:${level}:${i}:heading`} value={'#### '+g.parents.join(' · ')}/>}
    <div className="current-chart-pair">{['收入同比（%）','归母利润同比（%）'].map((field,j)=><Heat key={field} id={`history-${level}-growth-${i}-${j}`} queryId={queryId} names={g.industries} field={field} title={field==='收入同比（%）'?'营业收入同比（%）':'归母利润同比（%）'}/>)}</div>
  </div>)}</div>;
}
function CaseTrend({name,queryId,id,primary=false}){
  const {reviewedRows}=useDataApp();const rows=reviewedRows(queryId).filter(r=>r.行业===name),nine=reviewedRows(primary?'history_primary':'history_secondary').filter(r=>r.行业===name),latest=nine.find(r=>r.年份==='2026');
  const q=rows.filter(r=>r.年份==='2026'),last=q[q.length-1],before=q[q.length-2];
  const change=(row,field)=>row[field]==null?row.利润变化状态:(row[field]>0?'增长':row[field]<0?'下降':'持平')+(row[field]===0?'':num(Math.abs(row[field]))+'%');
  const profitChange=row=>row['归母利润同比（%）']==null?'归母利润'+row.利润变化状态:'归母利润同比'+change(row,'归母利润同比（%）');
  const caveat=latest['已知累计收入覆盖（%）']<90?` 三年前三季可比公司覆盖2026年已知收入的${num(latest['已知累计收入覆盖（%）'])}%。`:'';
  return <div className="history-case" id={id}>
    <RichNarrative id={id+':heading'} value={'### '+name}/>
    <ReportSection id={id+'-finding'} title={name+'同期与单季变化'} queryId={queryId} queryIds={[queryId,primary?'history_primary':'history_secondary']}
      sourceRowsByQuery={{[queryId]:rows,[primary?'history_primary':'history_secondary']:nine}} showHeading={false}>
      <RichNarrative id={id+':finding'} value={`2026年前三季收入同比${change(latest,'收入同比（%）')}，归母净利润${num(latest[money])}亿元，较上年同期${latest['归母利润增减（亿元）']>=0?'增加':'减少'}${num(Math.abs(latest['归母利润增减（亿元）']))}亿元。第三季度单季收入同比${change(last,'收入同比（%）')}，${profitChange(last)}；第二季度${profitChange(before)}。${caveat}`}/>
    </ReportSection>
    <div className="current-chart-pair"><Trend id={id+'-revenue'} queryId={queryId} rows={rows} field={revenue} title={name+'｜单季营业收入'}/><Trend id={id+'-profit'} queryId={queryId} rows={rows} field={money} title={name+'｜单季归母净利润'}/></div>
    <Note id={id+':scope'}>{`曲线覆盖同一批${rows[0].可比公司数}家公司；三年前三季比较覆盖${latest.可比公司数}家。两类图各自保持公司范围固定。`}</Note>
  </div>;
}
function Primary(){
  const {snapshot,reviewedRows}=useDataApp();const rows=reviewedRows('history_comparison').filter(r=>r.行业==='非金融整体'),one=y=>rows.find(r=>r.年份===y),a=one('2024'),b=one('2025'),c=one('2026');
  const q=reviewedRows('history_quarter_overall'),q26=q.filter(r=>r.年份==='2026');
  const latest=reviewedRows('history_primary').filter(r=>r.年份==='2026');
  return <section id="history-primary" className="sample-chapter history-chapter">
    <RichNarrative id="history:primary:heading" value="## 2.2.1　2024年以来一级行业：整体修复，季度增速与行业表现分化"/>
    <ReportSection id="history-overall-findings" title="三年前三季整体变化" queryId="history_comparison" sourceRows={rows} showHeading={false}>
      <RichNarrative id="history:overall:finding" value={`**同一批5,275家非金融公司，2026年前三季营业收入${num(c['收入（亿元）']/10000)}万亿元，归母利润${num(c[money]/10000)}万亿元。** 2025年收入同比增长${num(grow(b['收入（亿元）'],a['收入（亿元）']))}%、归母利润增长${num(grow(b[money],a[money]))}%；2026年分别增长${num(grow(c['收入（亿元）'],b['收入（亿元）']))}%和${num(grow(c[money],b[money]))}%，较2025年的低增速有所修复。`}/>
    </ReportSection>
    <div className="current-chart-pair"><AmountBars id="history-overall-revenue" queryId="history_comparison" rows={rows} field="收入（亿元）" scale={10000} unit="万亿元" title="非金融整体｜前三季营业收入"/><AmountBars id="history-overall-profit" queryId="history_comparison" rows={rows} field={money} scale={10000} unit="万亿元" title="非金融整体｜前三季归母净利润"/></div>
    <Note id="history:overall:scope">各年均为1—9月，同一批5,275家公司；行业采用东财2025年末体系，归属固定2026年10月30日。金额沿用已确认的三年汇总，金融单列。</Note>
    <RichNarrative id="history:primary:growth-heading" value="### 同期收入增长与利润改善分布在不同行业"/>
    <ReportSection id="history-primary-growth-findings" queryId="history_primary" sourceRows={latest} title="一级行业三年同期" showHeading={false}>
      <RichNarrative id="history:primary:growth-finding" value={`2026年前三季，${latest.filter(r=>r['收入同比（%）']>0).length}个一级行业收入增长、${latest.filter(r=>r['归母利润增减（亿元）']>0).length}个行业归母利润增加。电子收入同比增长33.41%、归母利润增长85.16%；煤炭利润较2025年回升28.07%，仍低于2024年同期；食品饮料归母利润连续两年减少，农林牧渔转为亏损。`}/>
    </ReportSection>
    <GrowthGroups level="primary"/>
    <Note id="history:primary:growth-scope">2024年为基准，不计算2024同比。归母利润上年为负、接近零或本期转亏时不展示正常增长率，状态及金额在图下列出。颜色以20%、50%分档，最深色表示绝对增减超过50%，数值保持原值。</Note>
    <RichNarrative id="history:quarter:heading" value="### 2026年第三季度利润增长较第二季度放缓"/>
    <ReportSection id="history-quarter-overall-findings" queryId="history_quarter_overall" sourceRows={q} title="整体单季变化" showHeading={false}>
      <RichNarrative id="history:quarter:finding" value={`**固定5,192家公司的单季归母利润同比增速，在2026年Q1、Q2、Q3分别为${q26.map(r=>num(r['归母利润同比（%）'])+'%').join('、')}。** 收入同比增速分别为${q26.map(r=>num(r['收入同比（%）'])+'%').join('、')}。前三季累计增长改善，但最新单季利润增速已较第二季度放缓。`}/>
    </ReportSection>
    <div className="current-chart-pair"><Trend id="history-overall-quarter-revenue" queryId="history_quarter_overall" rows={q} field={revenue} scale={10000} unit="万亿元" title="非金融整体｜单季营业收入"/><Trend id="history-overall-quarter-profit" queryId="history_quarter_overall" rows={q} field={money} scale={10000} unit="万亿元" title="非金融整体｜单季归母净利润"/></div>
    <Note id="history:quarter:scope">单季曲线采用11期收入与归母利润均完整且可比的5,192家公司，与前三季三年比较范围不同。2024/2025四季可加回全年，2026三季可加回前三季；2026Q4尚无实际，曲线留空。</Note>
    <RichNarrative id="history:quarter:heat-heading" value="### 各行业单季同比显示改善持续性差异"/>
    {snapshot.study.history.primaryGroups.map((names,i)=><div key={i} className="history-group">
      {['2025','2026'].map(year=><div className="current-chart-pair" key={year}>
        <Heat id={`history-quarter-growth-${i}-${year}-revenue`} queryId="history_quarter_primary" names={names} field="收入同比（%）" year={year} title={year+'年｜单季收入同比（%）'}/>
        <Heat id={`history-quarter-growth-${i}-${year}-profit`} queryId="history_quarter_primary" names={names} field="归母利润同比（%）" year={year} title={year+'年｜单季归母利润同比（%）'}/>
      </div>)}
    </div>)}
    <RichNarrative id="history:featured:heading" value="### 四个代表行业的三年规模与单季变化"/>
    {snapshot.study.history.featured.map((name,i)=>{const rows=reviewedRows('history_comparison').filter(r=>r.行业===name);return <div className="history-feature" key={name}>
      <div className="current-chart-pair"><AmountBars id={`history-feature-${i}-revenue`} queryId="history_comparison" rows={rows} field="收入（亿元）" title={name+'｜前三季营业收入'}/><AmountBars id={`history-feature-${i}-profit`} queryId="history_comparison" rows={rows} field={money} title={name+'｜前三季归母净利润'}/></div>
      <CaseTrend name={name} primary queryId="history_quarter_primary" id={`history-feature-quarter-${i}`}/>
    </div>;})}
    <p className="group-index"><a href="#history-quarter-appendix">其余一级行业单季金额曲线全览 ↓</a></p>
  </section>;
}
function Secondary(){
  const {snapshot,reviewedRows}=useDataApp();const rows=reviewedRows('history_secondary'),latest=rows.filter(r=>r.年份==='2026'),current=reviewedRows('secondary_profit').filter(r=>r.行业==='半导体');
  return <section id="history-secondary" className="sample-chapter history-chapter">
    <RichNarrative id="history:secondary:heading" value="## 2.2.2　2024年以来二级行业：细分增长与亏损变化并存"/>
    <ReportSection id="history-secondary-findings" title="二级三年同期比较" queryId="history_secondary" queryIds={['history_secondary','secondary_profit']} sourceRowsByQuery={{history_secondary:rows,secondary_profit:current}} showHeading={false}>
      <RichNarrative id="history:secondary:finding" value={`**124个非金融二级行业中，2026年前三季有${latest.filter(r=>r['收入同比（%）']>0).length}个收入增长、${latest.filter(r=>r['归母利润增减（亿元）']>0).length}个归母利润增加。** 工业金属、炼化及贸易、半导体的归母利润增量分别为991.05、729.27、682.55亿元；养殖业由盈转亏，利润减少441.40亿元。半导体三年比较覆盖169家公司、2026年已知收入的66.74%；前文两年同比覆盖186家，增量差异来自不同的可比公司范围。`}/>
    </ReportSection>
    <p className="group-index">{snapshot.study.heatGroups.map((g,i)=><a key={i} href={`#history-secondary-group-${i}`}>{g.parents.join(' · ')}</a>)}<a href="#history-secondary-amounts">三年金额全览 ↓</a></p>
    <GrowthGroups level="secondary"/>
    <Note id="history:secondary:scope">每个二级行业三个年份使用相同公司，合计与一级三年汇总一致；未额外要求全部季度或扣非、现金流完整。收入和利润同比各自单独展示；亏损及近零基数以状态和增减金额保留。</Note>
    <RichNarrative id="history:secondary:case-heading" value="### 六个细分行业的单季变化"/>
    {snapshot.study.history.cases.map((name,i)=><CaseTrend name={name} queryId="history_quarter_secondary" id={`history-secondary-case-${i}`} key={name}/>)}
  </section>;
}
function FinancialHistory(){
  const {reviewedRows}=useDataApp();const rows=reviewedRows('history_financial');
  return <section id="history-financial" className="sample-chapter history-chapter">
    <RichNarrative id="history:financial:heading" value="## 金融行业历史：银行稳步增长，非银利润回落"/>
    <ReportSection id="history-financial-findings" title="金融三年同期" queryId="history_financial" sourceRows={rows} showHeading={false}>
      <RichNarrative id="history:financial:finding" value="银行归母利润由2024年前三季的16,584.78亿元，增至2025年的16,831.03亿元和2026年的17,467.90亿元。非银金融2025年归母利润增长39.03%，2026年回落15.92%，仍高于2024年同期。"/>
    </ReportSection>
    {['一级','二级'].map(level=><div key={level} className="current-chart-pair"><AmountBars id={'history-finance-revenue-'+level} queryId="history_financial" rows={rows.filter(r=>r.层级===level)} field="营业总收入（亿元）" title={'金融'+level+'｜前三季营业总收入'}/><AmountBars id={'history-finance-profit-'+level} queryId="history_financial" rows={rows.filter(r=>r.层级===level)} field={money} title={'金融'+level+'｜前三季归母净利润'}/></div>)}
    <Note id="history:financial:scope">三年均为1—9月，银行42家、非银金融78家共同可比公司；使用营业总收入，与非金融营业收入分列。一级与其下属二级不重复加总。</Note>
  </section>;
}
function HistoryAppendix(){
  const {snapshot,reviewedRows}=useDataApp();const rows=reviewedRows('history_secondary'),other=reviewedRows('history_quarter_primary');
  return <>
    <section id="history-secondary-amounts" className="sample-chapter history-chapter">
      <RichNarrative id="history:secondary:amounts-heading" value="## 历史附录：二级行业三年前三季金额全览"/>
      <Note id="history:secondary:amounts-scope">各年均为1—9月，同一行业三个年份公司范围固定。收入与归母分别使用亿元，负利润保留；每幅图有独立金额刻度。</Note>
      {snapshot.study.heatGroups.map((g,i)=><div key={i} className="history-group"><RichNarrative id={`history:secondary:amounts:${i}:heading`} value={'### '+g.parents.join(' · ')}/><div className="current-chart-pair">
        <AmountBars id={`history-secondary-amounts-${i}-revenue`} queryId="history_secondary" rows={rows.filter(r=>g.industries.includes(r.行业))} field={revenue} title="三年前三季营业收入"/>
        <AmountBars id={`history-secondary-amounts-${i}-profit`} queryId="history_secondary" rows={rows.filter(r=>g.industries.includes(r.行业))} field={money} title="三年前三季归母净利润"/>
      </div></div>)}
    </section>
    <section id="history-quarter-appendix" className="sample-chapter history-chapter">
      <RichNarrative id="history:quarter:appendix-heading" value="## 历史附录：其余一级行业单季金额全览"/>
      <Note id="history:quarter:appendix-scope">下列25个行业与正文4个代表行业共同覆盖全部29个非金融一级行业。各行业固定11期共同公司；图中2024、2025年均有Q4实际，2026年曲线截至Q3。金额单位亿元，负利润保留。</Note>
      {[...new Set(other.map(r=>r.行业))].filter(name=>!snapshot.study.history.featured.includes(name)).map((name,i)=>{const rs=other.filter(r=>r.行业===name);return <div key={name} className="history-group"><RichNarrative id={`history:quarter:appendix:${i}:heading`} value={'### '+name}/><div className="current-chart-pair">
        <Trend id={`history-quarter-appendix-${i}-revenue`} queryId="history_quarter_primary" rows={rs} field={revenue} title={name+'｜单季营业收入'}/><Trend id={`history-quarter-appendix-${i}-profit`} queryId="history_quarter_primary" rows={rs} field={money} title={name+'｜单季归母净利润'}/>
      </div></div>;})}
    </section>
  </>;
}
export function HistoryChapters(){const {snapshot}=useDataApp();if(!['history','forecast'].includes(snapshot.study.stage))return null;return <><Primary/><Secondary/><FinancialHistory/></>;}
export function HistoryDetails(){const {snapshot}=useDataApp();return ['history','forecast'].includes(snapshot.study.stage)?<HistoryAppendix/>:null;}
