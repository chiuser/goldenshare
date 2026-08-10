#!/usr/bin/env python3
"""Build a self-contained, offline HTML overview of A-share power companies."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd


REPORT_DIR = Path(__file__).resolve().parent
PREFIX = "a_share_power_industry_20260803_"
OUTPUT = REPORT_DIR / "a_share_power_industry_research_20260803.html"

BIG_FUND_TEXT = "国家集成电路产业投资基金"


def text(value: object, fallback: str = "—") -> str:
    if value is None or pd.isna(value):
        return fallback
    value = str(value).strip()
    return value if value else fallback


def number(value: object, digits: int = 1, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}{suffix}"


def pct(value: object, digits: int = 1) -> str:
    return number(value, digits, "%")


def power_path(row: pd.Series) -> tuple[str, str]:
    code = row.ts_code
    name = row["name"]
    business = text(row.main_business, "").lower()
    industry = text(row.csrc_industry, "")
    if code in {"003816.SZ", "601985.SH"}:
        return "核电", "核电站投资、建设与运营"
    if code == "600995.SH":
        return "抽蓄/水电/电网侧储能", "调峰储能与水电、配售电"
    if code == "003035.SZ":
        return "综合能源服务", "节能改造与综合能源项目运营，非传统电源运营商"
    if code == "000958.SZ":
        return "清洁能源+产融", "电力热力与产业金融并行"
    if code in {"600475.SH", "002617.SZ", "601908.SH", "300125.SZ", "603105.SH"}:
        return "设备/光伏材料/分布式能源", "行业成分，但非以大型电站运营为核心"
    if code in {"002310.SZ", "600226.SH", "000631.SZ", "000595.SZ", "002480.SZ", "000803.SZ", "600052.SH", "000507.SZ"}:
        return "转型/多元经营", "行业成分中含能源主题，主营并非单一发电业务"
    if "垃圾" in business or ("生物质" in business and industry == "供气供热"):
        return "生物质/垃圾焚烧热电", "固废处置或生物质供热发电"
    if industry == "供气供热":
        return "热电联产/集中供热", "热力供应为主，部分电力上网"
    if industry == "水力发电":
        return "水电" if "供电" not in business else "水电/配售电", "水电开发运营或区域配售电"
    if industry == "火力发电":
        return "火电/热电", "煤电或热电联产为主，部分公司配置新能源"
    if "风" in business and ("光伏" in business or "太阳能" in business):
        return "风光综合", "风电与光伏项目开发、投资及运营"
    if "风" in business:
        return "风电为主", "风电项目开发、建设及运营"
    if "光伏" in business or "太阳能" in business:
        return "光伏为主", "光伏电站投资、建设及运营"
    if industry == "新型电力":
        return "新能源综合", "以新能源项目开发或综合能源业务为主"
    return "综合能源", f"按 Prod 行业/主营描述归类：{name}"


def ownership(row: pd.Series) -> str:
    kind = text(row.controller_type)
    controller = text(row.actual_controller)
    if kind == "中央国企":
        return f"央企｜{controller}"
    if kind == "地方国企":
        return f"地方国资｜{controller}"
    if kind == "自然人":
        return f"民营/自然人｜{controller}"
    if kind == "无":
        return "无实际控制人"
    return f"待核实｜{controller}"


def ownership_group(kind: object) -> str:
    value = text(kind)
    return {"中央国企": "央企", "地方国企": "地方国资", "自然人": "民营/自然人", "无": "无实控人"}.get(value, "待核实")


def prosperity(row: pd.Series) -> tuple[str, str]:
    margin, profit, revenue = row.netprofit_margin, row.netprofit_yoy, row.tr_yoy
    if pd.isna(margin) or pd.isna(profit) or pd.isna(revenue):
        return "待补", "2025 年报指标不可用"
    if margin < 0:
        return ("亏损修复" if profit >= 0 else "亏损承压"), "销售净利率为负，需结合亏损收窄/扩大判断"
    if profit >= 30 and revenue >= 0:
        return "高景气", "营收、归母净利同比均向上，且利润增速较快"
    if profit >= 0 and revenue >= 0:
        return "温和向上", "营收、归母净利同比均为正"
    if profit >= 0:
        return "利润改善", "归母净利同比为正，但营收同比偏弱"
    if profit > -20:
        return "盈利承压", "归母净利同比小幅回落"
    return "显著承压", "归母净利同比降幅较大"


def clean_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        path, role = power_path(row)
        state, signal = prosperity(row)
        records.append(
            {
                "code": text(row.ts_code),
                "name": text(row["name"]),
                "market": text(row.market),
                "list_date": text(row.list_date),
                "power_path": path,
                "business_role": role,
                "ownership": ownership(row),
                "ownership_group": ownership_group(row.controller_type),
                "top_holder": text(row.top_holder),
                "top_holder_ratio": None if pd.isna(row.top_holder_ratio) else round(float(row.top_holder_ratio), 2),
                "big_fund_top10": bool(row.big_fund_top10),
                "market_cap_yi": None if pd.isna(row.total_mv) else round(float(row.total_mv) / 10000, 2),
                "pe_ttm": None if pd.isna(row.pe_ttm) else round(float(row.pe_ttm), 2),
                "pb": None if pd.isna(row.pb) else round(float(row.pb), 2),
                "dividend_yield_ttm": None if pd.isna(row.dv_ttm) else round(float(row.dv_ttm), 2),
                "net_margin_2025": None if pd.isna(row.netprofit_margin) else round(float(row.netprofit_margin), 2),
                "gross_margin_2025": None if pd.isna(row.grossprofit_margin) else round(float(row.grossprofit_margin), 2),
                "roe_2025": None if pd.isna(row.roe) else round(float(row.roe), 2),
                "net_profit_yoy_2025": None if pd.isna(row.netprofit_yoy) else round(float(row.netprofit_yoy), 2),
                "revenue_yoy_2025": None if pd.isna(row.tr_yoy) else round(float(row.tr_yoy), 2),
                "debt_to_assets_2025": None if pd.isna(row.debt_to_assets) else round(float(row.debt_to_assets), 2),
                "prosperity": state,
                "prosperity_signal": signal,
                "valuation_date": text(row.valuation_date),
                "annual_report_ann_date": text(row.ann_date),
            }
        )
    return records


def report_html(data: list[dict[str, object]], meta: dict[str, object]) -> str:
    counts = pd.DataFrame(data)
    ownership_counts = counts.ownership_group.value_counts().to_dict()
    power_counts = counts.power_path.value_counts().to_dict()
    total_cap = counts.market_cap_yi.sum()
    full_data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    power_count_data = json.dumps(power_counts, ensure_ascii=False)
    ownership_count_data = json.dumps(ownership_counts, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股电力行业全景研究｜2026-08-03</title>
<style>
:root{{--ink:#142039;--muted:#667085;--line:#e6eaf0;--paper:#fff;--bg:#f5f7fb;--blue:#2768d8;--teal:#009f9a;--orange:#d97706;--red:#c24138;--green:#147a4a}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1440px;margin:auto;padding:32px 28px 56px}} .hero{{display:grid;grid-template-columns:1.35fr .65fr;gap:24px;align-items:end;padding:30px 32px;border-radius:20px;background:linear-gradient(125deg,#12305e,#2774db);color:#fff;box-shadow:0 14px 36px #14203924}}
h1{{font-size:32px;line-height:1.18;margin:0 0 10px;letter-spacing:.01em}} h2{{font-size:20px;margin:0 0 12px}} h3{{font-size:15px;margin:0 0 8px}} p{{margin:7px 0}} .subtitle{{font-size:16px;color:#dceaff}} .asof{{text-align:right;color:#e8f1ff}} .asof b{{display:block;font-size:22px;color:#fff}}
.notice{{margin:18px 0;padding:13px 16px;border-left:4px solid var(--orange);border-radius:8px;background:#fff7e6;color:#694d15}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}
.card,.panel{{background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 2px 5px #12203b05}} .card{{padding:16px 18px}} .k{{font-size:12px;color:var(--muted)}} .v{{font-size:26px;font-weight:720;margin-top:3px}} .small{{font-size:12px;color:var(--muted)}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}} .panel{{padding:18px}} .barrow{{display:grid;grid-template-columns:116px 1fr 35px;gap:8px;align-items:center;margin:8px 0}} .bar{{height:10px;border-radius:99px;background:#e9eef6;overflow:hidden}} .bar i{{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--blue),var(--teal))}}
.sector{{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;margin:18px 0}} .narrative ul{{margin:8px 0 0;padding-left:20px}} .narrative li{{margin:5px 0}}
.controls{{display:flex;flex-wrap:wrap;gap:10px;padding:15px;border-bottom:1px solid var(--line)}} input,select{{border:1px solid #cfd7e5;border-radius:8px;background:#fff;padding:8px 10px;color:var(--ink);font:inherit}} input{{min-width:230px;flex:1}} select{{min-width:160px}} .table-wrap{{overflow:auto;max-height:850px}} table{{width:100%;border-collapse:collapse;min-width:1270px}} th{{position:sticky;top:0;background:#f7f9fc;z-index:1;color:#475467;font-size:12px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line);padding:9px 10px}} td{{padding:10px;border-bottom:1px solid #edf0f4;vertical-align:top}} tr:hover td{{background:#f8fbff}} .code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#52627b}} .company{{font-weight:650;white-space:nowrap}} .sub{{display:block;margin-top:2px;font-size:11px;color:var(--muted);max-width:260px;white-space:normal}} .right{{text-align:right;white-space:nowrap}}
.badge{{display:inline-block;padding:2px 7px;border-radius:999px;background:#eef2f7;color:#4b5565;font-size:11px;white-space:nowrap}} .badge.央企{{background:#e8f0ff;color:#255fc3}} .badge.地方国资{{background:#e8f7f1;color:#16704d}} .badge.民营\\/自然人{{background:#fff1e8;color:#b65312}} .high{{background:#e6f7ed;color:#147a4a}} .up{{background:#e7f0ff;color:#2f68c7}} .down{{background:#fff0ed;color:#bd4537}} .loss{{background:#fcecf2;color:#a62a50}}
.scatter{{width:100%;height:300px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(#fff,#fafcff)}} .legend{{display:flex;flex-wrap:wrap;gap:12px;color:var(--muted);font-size:12px;margin-top:8px}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}} .foot{{margin-top:18px;color:var(--muted);font-size:12px}} .sources li{{margin:7px 0}} a{{color:#1d64c8}} .hidden{{display:none}}
@media(max-width:900px){{.hero,.two,.sector{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,1fr)}}.asof{{text-align:left}}.wrap{{padding:16px}}h1{{font-size:26px}}}}
</style>
</head>
<body><main class="wrap">
<section class="hero"><div><h1>A 股电力行业上市公司全景</h1><div class="subtitle">发电方式 · 国资与大基金 · 市值 · 2025 年报利润率 · 景气代理指标</div></div><div class="asof"><span>报告生成日</span><b>2026-08-03</b><span>估值数据截至 2026-07-31</span></div></section>
<div class="notice"><b>行业口径：</b>Prod 东方财富二级行业“电力”（BK0428.DC）截至 2026-07-31 的在市 A 股，剔除 B 股，共 {len(data)} 家。它不是申万“电力”或“公用事业”口径，部分“设备/转型/多元经营”成分已在表内显著标注。</div>
<section class="grid"><div class="card"><div class="k">成分公司</div><div class="v">{len(data)}</div><div class="small">当前在市 A 股</div></div><div class="card"><div class="k">国资控股</div><div class="v">{ownership_counts.get('央企',0)+ownership_counts.get('地方国资',0)}</div><div class="small">央企 {ownership_counts.get('央企',0)} · 地方国资 {ownership_counts.get('地方国资',0)}</div></div><div class="card"><div class="k">样本合计市值</div><div class="v">{total_cap/10000:,.2f} 万亿</div><div class="small">按 2026-07-31 总市值相加</div></div><div class="card"><div class="k">大基金前十大持股</div><div class="v">0</div><div class="small">2025-12-31 前十大股东范围内</div></div></section>
<section class="two"><div class="panel"><h2>发电/主营方式分布</h2><div id="power-bars"></div><p class="small">分类来自 Prod 的证监会行业与主营描述；“设备/转型”不应与纯发电资产运营商并列比较。</p></div><div class="panel"><h2>实际控制人性质</h2><div id="ownership-bars"></div><p class="small">央企/地方国资判断来自 Prod `actual_controller`、`controller_type` 字段。</p></div></section>
<section class="sector"><div class="panel narrative"><h2>2025 年行业景气：需求稳增，绿电供给扩张更快</h2><ul><li>全国全社会用电量 10.37 万亿千瓦时，同比增长 <b>5.0%</b>；第三产业和城乡居民生活用电对增量贡献达 50%。</li><li>可再生能源新增装机 4.52 亿千瓦，约占新增电力装机 83%；风光新增 4.38 亿千瓦，风光累计装机历史性超过火电。</li><li>可再生能源发电量 3.99 万亿千瓦时，同比增长 15%；但 6000 千瓦及以上电厂平均利用小时 3,119 小时，同比少 312 小时。</li><li><b>解读：</b>需求面偏正向，新能源装机/电量扩张强，但电量消纳、利用小时、电价和资本开支是公司间分化的关键，不能把行业高增长直接等同于单家公司盈利高景气。</li></ul></div><div class="panel"><h2>公司“景气度”怎么读</h2><p>表内是 <b>2025 年报回溯代理指标</b>，不是投资评级或预测：</p><p><span class="badge high">高景气</span> 营收同比≥0、归母净利同比≥30%</p><p><span class="badge up">温和向上/利润改善</span> 归母净利同比为正</p><p><span class="badge down">盈利承压</span> 归母净利同比小幅回落</p><p><span class="badge loss">亏损/显著承压</span> 净利率为负或利润同比降幅较大</p><p class="small">请结合电源结构、利用小时、煤价/电价、来水、装机投产与债务水平复核。</p></div></section>
<section class="panel"><h2>盈利能力与增速分布</h2><svg class="scatter" viewBox="0 0 1000 300" aria-label="2025 销售净利率与归母净利同比散点图" id="scatter"></svg><div class="legend"><span><i class="dot" style="background:#1e73d8"></i>央企</span><span><i class="dot" style="background:#15966a"></i>地方国资</span><span><i class="dot" style="background:#e07a28"></i>民营/自然人</span><span><i class="dot" style="background:#9aa4b2"></i>其他/待核实</span><span>横轴：销售净利率（2025）；纵轴：归母净利同比（2025）。悬停查看公司。</span></div></section>
<section class="panel"><h2>公司明细</h2><div class="controls"><input id="search" placeholder="搜索代码、简称、实控人、前十大最大股东、主营方式"><select id="power-filter"><option value="">全部主营方式</option></select><select id="ownership-filter"><option value="">全部控制人性质</option></select><select id="prosperity-filter"><option value="">全部景气状态</option></select><select id="sort"><option value="cap">按市值（高到低）</option><option value="margin">按净利率（高到低）</option><option value="profit">按净利增速（高到低）</option><option value="name">按代码</option></select></div><div class="table-wrap"><table><thead><tr><th>公司</th><th>发电/主营方式</th><th>实控人与性质</th><th>前十大最大股东<br><span class="small">年末披露</span></th><th>大基金<br><span class="small">前十大范围</span></th><th class="right">总市值<br><span class="small">亿元</span></th><th class="right">PE TTM</th><th class="right">2025 销售<br>净利率</th><th class="right">2025 ROE</th><th class="right">2025 净利<br>同比</th><th>景气代理判断</th></tr></thead><tbody id="rows"></tbody></table></div><p class="foot" id="result-count"></p></section>
<section class="panel sources"><h2>数据来源、口径与限制</h2><ol><li><b>Prod（内部）</b>：`core_serving.dc_member`/`raw_tushare.stock_basic`/`raw_tushare.stock_company`/`raw_tushare.daily_basic`，显式字段、只读查询；行业和市值截点均为 2026-07-31。`total_mv` 单位万元，报告换算为亿元。</li><li><b>公开公司披露聚合</b>：Tushare Pro 的 <a href="https://tushare.pro/document/2?doc_id=79" target="_blank" rel="noreferrer">财务指标</a> 与 <a href="https://tushare.pro/document/2?doc_id=61" target="_blank" rel="noreferrer">前十大股东</a>，报告期 2025-12-31；全体 {meta.get('financial_rows',0)} 家有财务数据，{meta.get('shareholder_rows',0)} 条前十大股东明细覆盖 108 家。单家公司年报公告日可在表数据中追溯。</li><li><b>行业背景</b>：国家能源局 <a href="https://www.nea.gov.cn/20260121/715f79826488476a9162da7c8bd77c80/c.html" target="_blank" rel="noreferrer">2025 年全社会用电量</a>、<a href="https://www.nea.gov.cn/20260212/742b8c6a078347b0b39de676c05c5d58/c.html" target="_blank" rel="noreferrer">2025 年可再生能源并网运行</a>、<a href="https://www.nea.gov.cn/20260129/6874f211acd0417eab7ac10c3061a7c2/c.html" target="_blank" rel="noreferrer">2025 年全国电力统计数据</a>。</li><li><b>大基金限制</b>：仅对披露的年末前十大股东名称检索“国家集成电路产业投资基金”；“未出现”不能证明其没有低于前十大门槛的持仓，也不涵盖基金产品、穿透持股或报告期后的变动。</li><li><b>不构成投资建议。</b>市值、估值和股东结构均会变动；电力公司还受来水、煤价、市场化电价、消纳、项目核准与资本开支影响，应以最新公告复核。</li></ol></section>
</main><script>
const data={full_data}; const powerCounts={power_count_data}; const ownerCounts={ownership_count_data};
const esc=s=>String(s??'—').replace(/[&<>"']/g,x=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[x]));
const n=(x,d=1)=>x===null||x===undefined?'—':Number(x).toLocaleString('zh-CN',{{maximumFractionDigits:d,minimumFractionDigits:d}});
const p=(x,d=1)=>x===null||x===undefined?'—':n(x,d)+'%';
function bars(el, obj){{const max=Math.max(...Object.values(obj));document.getElementById(el).innerHTML=Object.entries(obj).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="barrow"><span>${{esc(k)}}</span><div class="bar"><i style="width:${{v/max*100}}%"></i></div><b>${{v}}</b></div>`).join('')}}
bars('power-bars',powerCounts);bars('ownership-bars',ownerCounts);
for(const id of ['power-filter','ownership-filter','prosperity-filter']){{const key=id==='power-filter'?'power_path':id==='ownership-filter'?'ownership_group':'prosperity';const vals=[...new Set(data.map(x=>x[key]))].sort();document.getElementById(id).insertAdjacentHTML('beforeend',vals.map(x=>`<option value="${{esc(x)}}">${{esc(x)}}</option>`).join(''))}}
function badge(s){{let c=s.includes('高')?'high':s.includes('向上')||s.includes('改善')?'up':s.includes('亏损')||s.includes('显著')?'loss':'down';return `<span class="badge ${{c}}">${{esc(s)}}</span>`}}
function render(){{const q=document.getElementById('search').value.trim().toLowerCase(),pf=document.getElementById('power-filter').value,of=document.getElementById('ownership-filter').value,sf=document.getElementById('prosperity-filter').value,sort=document.getElementById('sort').value;let rows=data.filter(x=>!q||[x.code,x.name,x.power_path,x.ownership,x.top_holder].join(' ').toLowerCase().includes(q)).filter(x=>!pf||x.power_path===pf).filter(x=>!of||x.ownership_group===of).filter(x=>!sf||x.prosperity===sf);const key={{cap:'market_cap_yi',margin:'net_margin_2025',profit:'net_profit_yoy_2025',name:'code'}}[sort];rows.sort((a,b)=>sort==='name'?a.code.localeCompare(b.code):((b[key]??-Infinity)-(a[key]??-Infinity)));document.getElementById('rows').innerHTML=rows.map(x=>`<tr><td><span class="company">${{esc(x.name)}}</span><span class="code">${{esc(x.code)}}</span><span class="sub">上市：${{esc(x.list_date)}}</span></td><td>${{esc(x.power_path)}}<span class="sub">${{esc(x.business_role)}}</span></td><td><span class="badge ${{esc(x.ownership_group)}}">${{esc(x.ownership_group)}}</span><span class="sub">${{esc(x.ownership)}}</span></td><td>${{esc(x.top_holder)}}<span class="sub">${{p(x.top_holder_ratio)}} · 公告：${{esc(x.annual_report_ann_date)}}</span></td><td>${{x.big_fund_top10?'<span class="badge high">出现</span>':'<span class="badge">未出现</span>'}}</td><td class="right">${{n(x.market_cap_yi,1)}}</td><td class="right">${{n(x.pe_ttm,1)}}</td><td class="right">${{p(x.net_margin_2025)}}</td><td class="right">${{p(x.roe_2025)}}</td><td class="right">${{p(x.net_profit_yoy_2025)}}</td><td>${{badge(x.prosperity)}}<span class="sub">${{esc(x.prosperity_signal)}}</span></td></tr>`).join('');document.getElementById('result-count').textContent=`显示 ${{rows.length}} / ${{data.length}} 家；请优先比较同类电源与相近商业模式。`}}
['search','power-filter','ownership-filter','prosperity-filter','sort'].forEach(id=>document.getElementById(id).addEventListener(id==='search'?'input':'change',render));render();
function scatter(){{const s=document.getElementById('scatter'),w=1000,h=300,pad={{l:58,r:22,t:20,b:42}},xs=data.map(d=>d.net_margin_2025).filter(Number.isFinite),ys=data.map(d=>d.net_profit_yoy_2025).filter(Number.isFinite),range=(v,a)=>[Math.floor(Math.min(...v)/a)*a,Math.ceil(Math.max(...v)/a)*a],xr=range(xs,10),yr=range(ys,50),sx=x=>pad.l+(x-xr[0])/(xr[1]-xr[0])*(w-pad.l-pad.r),sy=y=>h-pad.b-(y-yr[0])/(yr[1]-yr[0])*(h-pad.t-pad.b),color={{'央企':'#1e73d8','地方国资':'#15966a','民营/自然人':'#e07a28'}};let out=`<line x1="${{pad.l}}" y1="${{h-pad.b}}" x2="${{w-pad.r}}" y2="${{h-pad.b}}" stroke="#9aa8ba"/><line x1="${{pad.l}}" y1="${{pad.t}}" x2="${{pad.l}}" y2="${{h-pad.b}}" stroke="#9aa8ba"/>`;for(let i=0;i<=4;i++){{let x=xr[0]+(xr[1]-xr[0])*i/4,y=yr[0]+(yr[1]-yr[0])*i/4;out+=`<text x="${{sx(x)}}" y="${{h-16}}" text-anchor="middle" font-size="11" fill="#667085">${{x.toFixed(0)}}%</text><text x="${{pad.l-8}}" y="${{sy(y)+4}}" text-anchor="end" font-size="11" fill="#667085">${{y.toFixed(0)}}%</text><line x1="${{sx(x)}}" y1="${{pad.t}}" x2="${{sx(x)}}" y2="${{h-pad.b}}" stroke="#edf1f6"/><line x1="${{pad.l}}" y1="${{sy(y)}}" x2="${{w-pad.r}}" y2="${{sy(y)}}" stroke="#edf1f6"/>`}}out+=`<text x="${{w/2}}" y="${{h-2}}" text-anchor="middle" font-size="11" fill="#667085">销售净利率（%）</text><text x="14" y="${{h/2}}" transform="rotate(-90 14 ${{h/2}})" text-anchor="middle" font-size="11" fill="#667085">归母净利同比（%）</text>`;data.filter(d=>Number.isFinite(d.net_margin_2025)&&Number.isFinite(d.net_profit_yoy_2025)).forEach(d=>{{out+=`<circle cx="${{sx(d.net_margin_2025)}}" cy="${{sy(d.net_profit_yoy_2025)}}" r="4" fill="${{color[d.ownership_group]||'#9aa4b2'}}" fill-opacity=".78"><title>${{d.name}} (${{d.code}})\n销售净利率：${{p(d.net_margin_2025)}}\n归母净利同比：${{p(d.net_profit_yoy_2025)}}</title></circle>`}});s.innerHTML=out}}scatter();
</script></body></html>"""


def main() -> None:
    prod = pd.read_csv(REPORT_DIR / f"{PREFIX}prod.csv", dtype={"ts_code": "string"})
    financials = pd.read_csv(REPORT_DIR / f"{PREFIX}financials.csv", dtype={"ts_code": "string"})
    holders = pd.read_csv(REPORT_DIR / f"{PREFIX}shareholders.csv", dtype={"ts_code": "string"})
    meta = json.loads((REPORT_DIR / f"{PREFIX}public_extract_meta.json").read_text(encoding="utf-8"))

    top_holders = (
        holders.sort_values(["ts_code", "hold_ratio"], ascending=[True, False])
        .drop_duplicates("ts_code")
        .rename(columns={"holder_name": "top_holder", "hold_ratio": "top_holder_ratio"})
        [["ts_code", "top_holder", "top_holder_ratio"]]
    )
    big_fund = (
        holders.assign(big_fund_top10=holders.holder_name.fillna("").str.contains(BIG_FUND_TEXT, regex=False))
        .groupby("ts_code", as_index=False).big_fund_top10.any()
    )
    merged = prod.merge(financials, on="ts_code", how="left").merge(top_holders, on="ts_code", how="left").merge(big_fund, on="ts_code", how="left")
    merged["big_fund_top10"] = merged.big_fund_top10.fillna(False)
    data = clean_records(merged)
    OUTPUT.write_text(report_html(data, meta), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
