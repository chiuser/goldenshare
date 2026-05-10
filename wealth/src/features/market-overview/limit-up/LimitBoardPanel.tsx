import { useEffect, useMemo, useState } from "react";
import { ComboBarChart } from "../../../shared/charts/ComboBarChart";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import type { LimitLeaderPerformanceItem, LimitSectorLeaderStructure, MarketOverview } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

export function LimitBoardPanel({ overview }: { overview: MarketOverview }) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="涨跌停统计与分布"
      help="Review v4：右上/右下改为“涨停板块分布｜领涨股涨停表现”；每行一只股票并展示对应涨停表现，最多3只。左上统计卡和左下历史柱图保持 v2 外层结构。"
      meta={<RangeSwitch ariaLabel="涨跌停历史范围" onChange={setRange} options={ranges} value={range} />}
    >
      <div className="limit-v2-grid">
        <div className="limit-cell" aria-label="涨跌停核心统计卡">
          <div className="limit-day-title">
            <b>核心统计</b>
            <span className="day-tag">今日</span>
          </div>
          <div className="limit-stats">
            {overview.limitMetrics.map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                sub={metric.sub}
                value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
              />
            ))}
          </div>
        </div>
        <LimitStructureBlock label="今日 04-28" structure={overview.limitStructures.today} />
        <div className="limit-cell chart-cell" aria-label="历史涨跌停组合柱状图">
          <div className="sub-chart-title">
            <span>历史涨跌停组合柱图</span>
            <span className="secondary">横轴日期 / 纵轴数量</span>
          </div>
          <ComboBarChart data={overview.charts.limitHistory[range]} />
        </div>
        <LimitStructureBlock label="昨日 04-27" structure={overview.limitStructures.yesterday} />
      </div>
    </Panel>
  );
}

function LimitStructureBlock({ label, structure }: { label: string; structure: LimitSectorLeaderStructure }) {
  const [selectedSectorCode, setSelectedSectorCode] = useState(structure.selectedSectorCode);
  const [selectedStockCode, setSelectedStockCode] = useState(structure.selectedStockCode);

  useEffect(() => {
    setSelectedSectorCode(structure.selectedSectorCode);
    setSelectedStockCode(structure.selectedStockCode);
  }, [structure.selectedSectorCode, structure.selectedStockCode]);

  const selectedStocks = useMemo(() => structure.leaderStocks[selectedSectorCode] ?? [], [structure.leaderStocks, selectedSectorCode]);
  const stocks = selectedStocks.slice(0, 3);

  useEffect(() => {
    if (stocks.length === 0) {
      setSelectedStockCode("");
      return;
    }
    if (!stocks.find((stock) => stock.stockCode === selectedStockCode)) {
      setSelectedStockCode(stocks[0].stockCode);
    }
  }, [stocks, selectedStockCode]);

  return (
    <div className="limit-cell" aria-label={`${label}涨停板块分布与领涨股涨停表现`}>
      <div className="limit-day-title">
        <b>涨停板块分布｜领涨股涨停表现</b>
        <span className="day-tag">{label}</span>
      </div>
      <div className="limit-sector-leader">
        <div className="limit-v3-col">
          <div className="limit-v3-title">
            <span>涨停板块分布</span>
            <span className="secondary">数量</span>
          </div>
          <div className="limit-v3-rows">
            {structure.sectors.map((sector) => (
              <div
                className={`sector-bar-row${sector.sectorCode === selectedSectorCode ? " selected" : ""}`}
                key={sector.sectorCode}
                onMouseEnter={() => setSelectedSectorCode(sector.sectorCode)}
                title={`板块：${sector.sectorName}`}
              >
                <span className="sector-bar-name">{sector.sectorName}</span>
                <span className="sector-bar-track">
                  <span className="sector-bar-fill" style={{ width: `${sector.ratio}%` }} />
                </span>
                <span className="num up">{sector.limitUpCount}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="limit-v3-col">
          <div className="limit-v3-title">
            <span>领涨股涨停表现</span>
            <span className="secondary">最多3只</span>
          </div>
          <div className="limit-v3-rows">
            {stocks.map((stock) => (
              <LeaderPerformanceRow key={stock.stockCode} onMouseEnter={() => setSelectedStockCode(stock.stockCode)} selected={stock.stockCode === selectedStockCode} stock={stock} />
            ))}
            {selectedStocks.length > 3 ? <div className="more-row">更多 {selectedStocks.length - 3} 只涨停股</div> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function LeaderPerformanceRow({ onMouseEnter, selected, stock }: { onMouseEnter: () => void; selected: boolean; stock: LimitLeaderPerformanceItem }) {
  const directionClass = stock.changePct >= 0 ? "up" : "down";

  return (
    <div
      className={`leader-performance-row${selected ? " selected" : ""}`}
      onMouseEnter={onMouseEnter}
      title={`${stock.stockName}｜${stock.streakLabel}｜${stock.recentLimitText}｜首次封板 ${stock.firstLimitTime}｜开板 ${stock.openTimes} 次｜封单 ${stock.sealedAmountDisplayText}`}
    >
      <span className="num muted">{stock.rank}</span>
      <span className="leader-stock-main">
        <strong>{stock.stockName}</strong>
        <span>{stock.stockCode}</span>
      </span>
      <span className="leader-price">
        <b className={`num ${directionClass}`}>{stock.latestPrice.toFixed(2)}</b>
        <small className={`num ${directionClass}`}>{stock.changePct >= 0 ? "+" : ""}{stock.changePct.toFixed(2)}%</small>
      </span>
      <span className="perf-inline">
        <span className="perf-tag">{stock.streakLabel}</span>
        <span className="perf-tag">{stock.recentLimitText}</span>
      </span>
      <span className="seal-meta">
        <span>{stock.firstLimitTime}</span>
        <span>开板 {stock.openTimes}次</span>
      </span>
      <span className="seal-amount">{stock.sealedAmountDisplayText}</span>
    </div>
  );
}
