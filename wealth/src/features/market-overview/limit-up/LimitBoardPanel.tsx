import { useEffect, useMemo, useState } from "react";
import { ComboBarChart } from "../../../shared/charts/ComboBarChart";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type {
  LimitLeaderPerformanceItemView,
  LimitSectorLeaderStructureView,
  MarketLimitUpViewModel,
} from "./api/marketLimitUpAdapter";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

interface LimitBoardPanelProps {
  viewState: "loading" | "ready" | "error";
  limitUp?: MarketLimitUpViewModel;
  errorMessage?: string;
}

export function LimitBoardPanel({ viewState, limitUp, errorMessage }: LimitBoardPanelProps) {
  const [range, setRange] = useState("1m");
  const badgeLabel =
    viewState === "loading"
      ? "涨跌停模块加载中"
      : viewState === "error"
        ? "涨跌停模块加载失败"
        : limitUp?.statusLabel ?? "事实聚合已就绪";
  const badgeTone = viewState === "ready" ? (limitUp?.statusTone ?? "ready") : "delayed";

  return (
    <Panel
      title="涨跌停统计与分布"
      help="Review v4：右上/右下改为“涨停板块分布｜领涨股涨停表现”；每行一只股票并展示对应涨停表现，最多3只。左上统计卡和左下历史柱图保持 v2 外层结构。"
      meta={
        <div className="section-meta-inline">
          <RangeSwitch ariaLabel="涨跌停历史范围" onChange={setRange} options={ranges} value={range} />
          <DataStatusBadge label={badgeLabel} tone={badgeTone} />
        </div>
      }
    >
      {viewState === "loading" ? (
        <div className="summary-state-wrap">
          <SkeletonBlock />
        </div>
      ) : null}
      {viewState === "error" ? (
        <div className="summary-state-wrap">
          <div className="state-block error-box">
            <strong>error</strong>
            <br />
            <span>{errorMessage ?? "请求超时，请稍后重试。"}</span>
          </div>
        </div>
      ) : null}
      {viewState === "ready" && limitUp ? (
        <div className="limit-v2-grid">
          <div className="limit-cell" aria-label="涨跌停核心统计卡">
            <div className="limit-day-title">
              <b>核心统计</b>
              <span className="day-tag">今日</span>
            </div>
            <div className="limit-stats">
              {limitUp.metrics.map((metric) => (
                <MetricCard
                  key={metric.label}
                  label={metric.label}
                  sub={metric.sub}
                  value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
                />
              ))}
            </div>
          </div>
          <LimitStructureBlock label={`今日 ${formatTradeDateLabel(limitUp.structures.today.tradeDate)}`} structure={limitUp.structures.today} />
          <div className="limit-cell chart-cell" aria-label="历史涨跌停组合柱状图">
            <div className="sub-chart-title">
              <span>历史涨跌停组合柱图</span>
              <span className="secondary">横轴日期 / 纵轴数量</span>
            </div>
            <ComboBarChart data={limitUp.historyByRange[range as "1m" | "3m"]} />
          </div>
          <LimitStructureBlock label={`昨日 ${formatTradeDateLabel(limitUp.structures.yesterday.tradeDate)}`} structure={limitUp.structures.yesterday} />
        </div>
      ) : null}
    </Panel>
  );
}

function formatTradeDateLabel(tradeDate: string): string {
  if (!tradeDate) return "--";
  const [year, month, day] = tradeDate.split("-");
  if (!year || !month || !day) return tradeDate;
  return `${month}-${day}`;
}

function LimitStructureBlock({ label, structure }: { label: string; structure: LimitSectorLeaderStructureView }) {
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

function LeaderPerformanceRow({ onMouseEnter, selected, stock }: { onMouseEnter: () => void; selected: boolean; stock: LimitLeaderPerformanceItemView }) {
  const directionClass = stock.changePct === null ? "flat" : stock.changePct >= 0 ? "up" : "down";
  const changeText = stock.changePct === null ? "--" : `${stock.changePct >= 0 ? "+" : ""}${stock.changePct.toFixed(2)}%`;
  const priceText = stock.latestPrice === null ? "--" : stock.latestPrice.toFixed(2);

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
        <b className={`num ${directionClass}`}>{priceText}</b>
        <small className={`num ${directionClass}`}>{changeText}</small>
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
