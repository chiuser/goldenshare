import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  HistoryLineChart,
  LadderStageColumn,
  Panel,
  RangeTabs,
  RankList,
  StockDrawer,
  Tabs,
  TopNav,
  TrendText,
} from "./market-homepage-components";
import {
  historyPoints,
  indexQuotes,
  ladderStages,
  newsByTab,
  sectorLeaders,
  sectorLosers,
  stockGainers,
  stockLosers,
  type LadderStage,
  type NavKey,
} from "./market-homepage-data";
import "./market-homepage.css";

export function MarketHomepagePage() {
  const [activePage, setActivePage] = useState<NavKey>("home");
  const [sectorTab, setSectorTab] = useState("领涨板块");
  const [stockTab, setStockTab] = useState("领涨个股");
  const [newsTab, setNewsTab] = useState("今日热点");
  const [range, setRange] = useState(10);
  const visibleHistory = useMemo(() => historyPoints.slice(-range), [range]);
  const [selectedHistoryIndex, setSelectedHistoryIndex] = useState(visibleHistory.length - 1);
  const [drawerStage, setDrawerStage] = useState<LadderStage | null>(null);

  useEffect(() => {
    setSelectedHistoryIndex(visibleHistory.length - 1);
  }, [visibleHistory.length]);

  useEffect(() => {
    if (!drawerStage) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerStage(null);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [drawerStage]);

  const selectedPoint = visibleHistory[selectedHistoryIndex] ?? visibleHistory.at(-1) ?? historyPoints.at(-1)!;

  const handleNavigate = (page: NavKey) => {
    setActivePage(page === "emotion" ? "emotion" : "home");
  };

  return (
    <div className="market-page">
      <div className="app">
        <TopNav activePage={activePage} onNavigate={handleNavigate} />
        <main>
          {activePage === "emotion" ? (
            <EmotionAnalysisPage
              selectedHistoryIndex={selectedHistoryIndex}
              selectedPoint={selectedPoint}
              setDrawerStage={setDrawerStage}
              setRange={setRange}
              setSelectedHistoryIndex={setSelectedHistoryIndex}
              visibleHistory={visibleHistory}
              range={range}
            />
          ) : (
            <HomePage
              newsTab={newsTab}
              sectorTab={sectorTab}
              setNewsTab={setNewsTab}
              setSectorTab={setSectorTab}
              setStockTab={setStockTab}
              stockTab={stockTab}
            />
          )}
        </main>
        <div className="footer">
          V10 重建说明：此页面基于 V10 HTML 原型工程化还原，当前数据全部为前端 mock。
        </div>
      </div>
      <StockDrawer stage={drawerStage} onClose={() => setDrawerStage(null)} />
    </div>
  );
}

function HomePage({
  newsTab,
  sectorTab,
  setNewsTab,
  setSectorTab,
  setStockTab,
  stockTab,
}: {
  newsTab: string;
  sectorTab: string;
  stockTab: string;
  setNewsTab: (value: string) => void;
  setSectorTab: (value: string) => void;
  setStockTab: (value: string) => void;
}) {
  return (
    <>
      <div className="dashboard">
        <Panel
          meta="更新时间 14:36:08"
          subtitle="低信息密度回答：市场在发生什么、适不适合交易、情绪如何。"
          title="市场总览"
        >
          <div className="summary">
            <div className="tag">今日判断：震荡偏强 · 结构性活跃</div>
            <h2>权重指数偏稳，题材情绪修复，交易机会主要集中在算力、黄金、有色与高股息方向。</h2>
            <p>市场当前并非全面强势普涨，更像是“指数稳、结构热、热点轮动快”的环境。适合顺着主线做聚焦，不适合盲目追高扩散题材。</p>
          </div>
          <div className="metric-grid">
            <MetricCard
              badge="核心指标"
              desc="温度位于偏热区间，市场有可交易性，但还没到极致亢奋。"
              fillClass=""
              label="市场温度"
              mini={<><span className="mini"><span className="up">▲</span>上涨家数 3286</span><span className="mini"><span className="up">▲</span>涨停 71</span></>}
              unit="/100"
              value="73"
            />
            <MetricCard
              badge="必备指标"
              desc="情绪处于修复发酵阶段，连板梯队尚在，但高位分歧开始加大。"
              fillClass="emotion"
              label="情绪指数"
              mini={<><span className="mini"><span className="up">▲</span>连板高度 6</span><span className="mini"><span className="down">▼</span>跌停 8</span></>}
              unit="/100"
              value="62"
            />
            <MetricCard
              badge="交易建议"
              desc="适合围绕已验证主线做低吸与分歧承接，不适合扩大到非主线追涨。"
              fillClass="trade"
              label="是否适合交易"
              mini={<><span className="mini"><span className="flat">•</span>仓位 5~7 成</span><span className="mini"><span className="flat">•</span>追高谨慎</span></>}
              unit="偏适合"
              value="58"
            />
          </div>
        </Panel>

        <Panel meta="4 行 × 3 列" subtitle="指数卡片只保留名称、点位、涨跌额、涨跌幅。红涨绿跌。" title="主要指数">
          <div className="index-grid">
            {indexQuotes.map((quote) => (
              <article className={`index-card ${quote.trend === "up" ? "up-card" : "down-card"}`} key={quote.name}>
                <h4>{quote.name}</h4>
                <strong>{quote.value}</strong>
                <div className="bottom">
                  <span className={quote.trend}>{quote.change}</span>
                  <span className={quote.trend}>{quote.pct}</span>
                </div>
              </article>
            ))}
          </div>
        </Panel>
      </div>

      <div className="section-row">
        <Panel meta="板块热度" subtitle="领涨领跌放在同一模块内，保持首页快速扫描。" title="板块领涨领跌">
          <Tabs active={sectorTab} items={["领涨板块", "领跌板块"]} onChange={setSectorTab} />
          <RankList items={sectorTab === "领涨板块" ? sectorLeaders : sectorLosers} />
        </Panel>
        <Panel meta="个股强弱" subtitle="保留代表性个股，不在首页展开全部名单。" title="个股领涨领跌">
          <Tabs active={stockTab} items={["领涨个股", "领跌个股"]} onChange={setStockTab} />
          <RankList items={stockTab === "领涨个股" ? stockGainers : stockLosers} />
        </Panel>
      </div>

      <div className="bottom-row">
        <Panel meta="资讯雷达" subtitle="四类新闻使用 tab 样式按钮切换。" title="新闻板块">
          <Tabs active={newsTab} items={Object.keys(newsByTab)} onChange={setNewsTab} />
          {(newsByTab[newsTab] ?? []).map((item) => (
            <div className="news-item" key={item.title}>
              <span className="news-tag">{item.tag}</span>
              <div>
                <h4 className="news-title">{item.title}</h4>
                <p className="news-desc">{item.desc}</p>
              </div>
              <span className="news-time">{item.time}</span>
            </div>
          ))}
        </Panel>
        <Panel meta="交易纪律" subtitle="将市场判断转为可执行的操作建议。" title="操作建议">
          <div className="advice-main">
            <h3>主线聚焦，分歧低吸，避免非主线追高。</h3>
            <p>市场热度尚可，但广度并不稳定。当前更适合围绕算力、黄金、有色、高股息等已被市场验证的方向寻找机会。</p>
          </div>
          {[
            ["适合做什么", "关注算力、黄金、有色、高股息等已被市场验证的方向。"],
            ["不适合做什么", "避免在非主线板块追涨，尤其是成交承接不足的跟风股。"],
            ["仓位建议", "建议总体仓位 5~7 成；若高位分歧扩大，则回撤至 3~5 成。"],
          ].map(([title, desc]) => (
            <div className="bullet" key={title}>
              <div className="bullet-dot" />
              <div>
                <h5>{title}</h5>
                <p>{desc}</p>
              </div>
            </div>
          ))}
        </Panel>
      </div>
    </>
  );
}

function MetricCard({
  badge,
  desc,
  fillClass,
  label,
  mini,
  unit,
  value,
}: {
  label: string;
  badge: string;
  value: string;
  unit: string;
  desc: string;
  fillClass: string;
  mini: ReactNode;
}) {
  return (
    <article className="metric">
      <div className="metric-head">
        <span>{label}</span>
        <span className="badge">{badge}</span>
      </div>
      <div className="value">
        <strong>{value}</strong>
        <span>{unit}</span>
      </div>
      <div className="meter">
        <div className={`fill ${fillClass}`} />
      </div>
      <p className="desc">{desc}</p>
      <div className="mini-list">{mini}</div>
    </article>
  );
}

function EmotionAnalysisPage({
  range,
  selectedHistoryIndex,
  selectedPoint,
  setDrawerStage,
  setRange,
  setSelectedHistoryIndex,
  visibleHistory,
}: {
  range: number;
  selectedHistoryIndex: number;
  selectedPoint: (typeof historyPoints)[number];
  visibleHistory: typeof historyPoints;
  setRange: (value: number) => void;
  setSelectedHistoryIndex: (value: number) => void;
  setDrawerStage: (stage: LadderStage) => void;
}) {
  return (
    <Panel>
      <div className="emotion-hero">
        <h2>情绪分析</h2>
        <p>从市场广度、涨跌停结构与连板高度三个维度，快速判断当前赚钱效应、亏钱效应以及短线情绪强弱。</p>
        <div className="hero-pills">
          <span className="mini"><span className="up">▲</span>情绪温度 62</span>
          <span className="mini"><span className="up">▲</span>涨停 59</span>
          <span className="mini"><span className="down">▼</span>跌停 8</span>
          <span className="mini"><span className="flat">•</span>连板高度 6 板</span>
          <span className="mini"><span className="flat">•</span>封板率 69%</span>
        </div>
      </div>

      <Panel className="emotion-full-panel" meta="量能监控" subtitle="左边聚焦今日成交额与资金面结论，右边展示历史成交额走势。" title="成交额">
        <div className="split">
          <div className="subcard">
            <h4>今日成交总额</h4>
            <p className="subtitle">把“成交了多少、相较昨日变化、资金流向”放在一眼可读的位置。</p>
            <div className="today-turnover">
              <strong>21,473 亿</strong>
              <span>截至 14:36</span>
            </div>
            <div className="flow-grid">
              <div className="flow-metric"><div className="label">较昨日</div><strong className="down">-3,033 亿</strong></div>
              <div className="flow-metric"><div className="label">资金流向</div><strong className="down">净流出 128 亿</strong></div>
              <div className="flow-metric"><div className="label">市场判断</div><strong className="flat">缩量震荡</strong></div>
            </div>
            <div className="mini-list">
              <span className="mini"><span className="up">▲</span>北向净流入 18.6 亿</span>
              <span className="mini"><span className="down">▼</span>主力净流出 146 亿</span>
              <span className="mini"><span className="flat">•</span>量能分位 64%</span>
            </div>
          </div>
          <div className="subcard">
            <div className="chart-title-row">
              <div>
                <h4>历史成交额</h4>
                <p className="subtitle">横轴为日期，纵轴为成交额（亿元）。</p>
              </div>
              <RangeTabs value={range} onChange={setRange} />
            </div>
            <div className="chart-legend"><span className="legend-item"><span className="legend-line gold" />成交额</span></div>
            <HistoryLineChart mode="turnover" onHoverIndex={setSelectedHistoryIndex} points={visibleHistory} selectedIndex={selectedHistoryIndex} />
            <div className="chart-footer"><span>近 {range} 日均值：18,240 亿</span><span className="flat">量能中枢高于上周</span></div>
          </div>
        </div>
        <LinkagePanel selectedPoint={selectedPoint} />
      </Panel>

      <div className="emotion-row">
        <Panel meta="市场广度" subtitle="左看当日分布，右看历史涨跌家数。" title="涨跌分布">
          <div className="split">
            <DistributionToday />
            <div className="subcard">
              <div className="chart-title-row">
                <div>
                  <h4>历史涨跌</h4>
                  <p className="subtitle">上涨家数与下跌家数各画一条线。</p>
                </div>
                <RangeTabs value={range} onChange={setRange} />
              </div>
              <div className="chart-legend">
                <span className="legend-item"><span className="legend-line red" />上涨家数</span>
                <span className="legend-item"><span className="legend-line green" />下跌家数</span>
              </div>
              <HistoryLineChart mode="breadth" onHoverIndex={setSelectedHistoryIndex} points={visibleHistory} selectedIndex={selectedHistoryIndex} />
              <div className="chart-footer"><span>上涨家数均值：2,186</span><span>下跌家数均值：2,972</span></div>
            </div>
          </div>
        </Panel>
        <LimitBoardPanel />
      </div>

      <div className="emotion-bottom">
        <Panel meta="连板结构" subtitle="首板在左，高板在右。点击数量或“查看全部”打开右侧抽屉。" title="连板天梯">
          <div className="ladder-toolbar">
            <div className="toolbar-tip">交互建议：<strong>点击每列数量</strong> 或 <strong>查看全部</strong>，用右侧抽屉查看完整股票列表。</div>
            <div className="tabs"><div className="tab active">按连板数</div><div className="tab">按行业</div></div>
          </div>
          <div className="ladder-stage">
            {ladderStages.map((stage) => (
              <LadderStageColumn key={stage.key} onOpen={setDrawerStage} stage={stage} />
            ))}
          </div>
          <div className="ladder-note">
            <div className="note-card"><h4>情绪解读</h4><p>高度来到 6 板，说明短线情绪仍有承载核心龙头的能力，但高位只剩单核。</p></div>
            <div className="note-card"><h4>明日观察</h4><p>重点看 6 板龙头是否继续打高度，以及 4 板、5 板梯队是否同步晋级。</p></div>
            <div className="note-card"><h4>抽屉交互</h4><p>天梯主视图保持总览感，具体股票名单进入右侧抽屉，避免撑乱主页面。</p></div>
          </div>
        </Panel>
      </div>
    </Panel>
  );
}

function LinkagePanel({ selectedPoint }: { selectedPoint: (typeof historyPoints)[number] }) {
  return (
    <div className="linkage-panel">
      <div className="linkage-head">
        <div>
          <h4>成交额 × 市场广度联动观察</h4>
          <p className="subtitle">同一日期下，同时观察成交额、上涨家数、下跌家数与净流向。</p>
        </div>
        <div className="meta">{selectedPoint.date}</div>
      </div>
      <div className="linkage-grid">
        <div className="linkage-metric"><span>成交额</span><strong>{selectedPoint.turnover.toLocaleString("zh-CN")} 亿</strong></div>
        <div className="linkage-metric"><span>上涨家数</span><strong className="up">{selectedPoint.rising.toLocaleString("zh-CN")} 家</strong></div>
        <div className="linkage-metric"><span>下跌家数</span><strong className="down">{selectedPoint.falling.toLocaleString("zh-CN")} 家</strong></div>
        <div className="linkage-metric"><span>资金流向</span><strong className={selectedPoint.flow >= 0 ? "up" : "down"}>{selectedPoint.flow >= 0 ? "净流入" : "净流出"} {Math.abs(selectedPoint.flow)} 亿</strong></div>
      </div>
      <div className="insight">{selectedPoint.insight}</div>
    </div>
  );
}

function DistributionToday() {
  const bars = [
    [">10%", 11, "up", 4], ["10~7%", 22, "up", 7], ["7~5%", 67, "up", 16], ["5~3%", 691, "up", 28], ["3~0%", 3490, "up", 100],
    ["0%", 52, "neutral", 14], ["0~-3%", 810, "down", 30], ["-3~-5%", 162, "down", 12], ["-5~-7%", 76, "down", 8], ["<-7%", 25, "down", 5],
  ] as const;

  return (
    <div className="subcard">
      <h4>今日涨跌分布</h4>
      <p className="subtitle">上方看区间分布，下方看涨跌家数汇总。</p>
      <div className="dist-bars">
        {bars.map(([label, value, trend, height]) => (
          <div className="dist-col" key={label}>
            <div className={`dist-value ${trend}`}>{value}</div>
            <div className={`dist-bar ${trend === "up" ? "red" : trend === "down" ? "green" : "gray"}`} style={{ height: `${height}%` }} />
            <div className="dist-label">{label}</div>
          </div>
        ))}
      </div>
      <div className="dist-summary">
        <span>跌 <TrendText trend="down"><strong>4299</strong></TrendText> 家</span>
        <span>涨 <TrendText trend="up"><strong>1140</strong></TrendText> 家</span>
        <span>跌停 <TrendText trend="down"><strong>13</strong></TrendText> 家</span>
        <span>平盘 <TrendText trend="neutral"><strong>52</strong></TrendText> 家</span>
      </div>
    </div>
  );
}

function LimitBoardPanel() {
  const metrics = [
    ["涨停板", "59", "53", "red"], ["涨停封板率", "69%", "77%", "red"], ["涨停打开", "26", "16", "red"],
    ["跌停板", "8", "1", "green"], ["跌停封板率", "80%", "25%", "green"], ["跌停打开", "2", "3", "green"],
  ] as const;

  return (
    <Panel meta="涨停战法" subtitle="今日 / 昨日对比与封板质量。" title="涨跌停板">
      <div className="limit-grid">
        {metrics.map(([label, today, yesterday, tone]) => (
          <div className="limit-item" key={label}>
            <div className={`limit-head ${tone}`}>{label}</div>
            <div className="limit-body">
              <div className="limit-values">
                <div className="limit-stat"><div className={`limit-num ${tone === "red" ? "up" : "down"}`}>{today}</div><div className="limit-caption">今日</div></div>
                <div className="limit-stat"><div className="limit-num">{yesterday}</div><div className="limit-caption">昨日</div></div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
