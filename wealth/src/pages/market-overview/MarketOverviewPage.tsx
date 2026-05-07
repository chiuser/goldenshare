import { useEffect, useState } from "react";
import { fetchMarketOverviewMock } from "../../features/market-overview/api/marketOverviewMockAdapter";
import type { MarketOverview } from "../../features/market-overview/api/marketOverviewTypes";
import { MarketBreadthPanel } from "../../features/market-overview/breadth/MarketBreadthPanel";
import { MajorIndexPanel } from "../../features/market-overview/indices/MajorIndexPanel";
import { Breadcrumb } from "../../features/market-overview/layout/Breadcrumb";
import { PageHeader } from "../../features/market-overview/layout/PageHeader";
import { ShortcutBar } from "../../features/market-overview/layout/ShortcutBar";
import { TopMarketBar } from "../../features/market-overview/layout/TopMarketBar";
import { LeaderboardPanel } from "../../features/market-overview/leaderboards/LeaderboardPanel";
import { LimitBoardPanel } from "../../features/market-overview/limit-up/LimitBoardPanel";
import { StreakLadderPanel } from "../../features/market-overview/limit-up/StreakLadderPanel";
import { MarketMoneyFlowPanel } from "../../features/market-overview/money-flow/MarketMoneyFlowPanel";
import { SectorOverviewPanel } from "../../features/market-overview/sectors/SectorOverviewPanel";
import { MarketStylePanel } from "../../features/market-overview/style/MarketStylePanel";
import { MarketSummaryPanel } from "../../features/market-overview/summary/MarketSummaryPanel";
import { TurnoverOverviewPanel } from "../../features/market-overview/turnover/TurnoverOverviewPanel";
import { SkeletonBlock } from "../../shared/ui/SkeletonBlock";
import "./market-overview-page.css";

export function MarketOverviewPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [toast, setToast] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchMarketOverviewMock().then((response) => setOverview(response.data));
  }, []);

  function showToast(message: string) {
    setToast(message);
    window.clearTimeout(window.__wealthToastTimer);
    window.__wealthToastTimer = window.setTimeout(() => setToast(""), 1800);
  }

  function refresh() {
    setRefreshing(true);
    window.setTimeout(() => {
      setRefreshing(false);
      showToast("市场总览已刷新：2026-04-28 15:05:18");
    }, 900);
  }

  if (!overview) {
    return (
      <main className="page-shell">
        <SkeletonBlock />
      </main>
    );
  }

  return (
    <div className="market-terminal">
      <TopMarketBar dataDelayText={overview.dataDelayText} onAction={showToast} statusText={overview.statusText} tickers={overview.tickers} />
      <main className="page-shell">
        <Breadcrumb onAction={showToast} />
        <PageHeader refreshing={refreshing} tradeDate={overview.tradeDate} updateTime={overview.updateTime} onRefresh={refresh} />
        <ShortcutBar onAction={showToast} />
        <div className="content-grid">
          <div className="summary-index-row" aria-label="今日市场客观总结与主要指数组合">
            <MarketSummaryPanel facts={overview.summaryFacts} text={overview.summaryText} />
            <MajorIndexPanel indices={overview.indices} onAction={showToast} />
          </div>
          <div className="row-three">
            <MarketBreadthPanel overview={overview} />
            <MarketStylePanel overview={overview} />
            <TurnoverOverviewPanel overview={overview} />
          </div>
          <div className="row-two">
            <MarketMoneyFlowPanel overview={overview} />
            <LeaderboardPanel overview={overview} onAction={showToast} />
          </div>
          <LimitBoardPanel overview={overview} />
          <StreakLadderPanel overview={overview} onAction={showToast} />
          <SectorOverviewPanel overview={overview} onAction={showToast} />
          <StateBaselinePanel />
        </div>
      </main>
      {toast ? <div id="toast">{toast}</div> : null}
    </div>
  );
}

function StateBaselinePanel() {
  return (
    <section className="panel" aria-label="状态样式基线">
      <div className="section-header">
        <div className="section-title">
          状态样式基线
          <span
            className="help"
            data-tip="供 Codex 和前端工程师落地时复用：loading、empty、error、hover、active、selected、data delayed。"
            title="供 Codex 和前端工程师落地时复用：loading、empty、error、hover、active、selected、data delayed。"
          >
            ?
          </span>
        </div>
        <span className="secondary">展示基础状态，不参与业务判断</span>
      </div>
      <div className="state-lab">
        <SkeletonBlock />
        <div className="state-block empty-box">
          <span>—</span>
          <span>empty：当前筛选条件下暂无数据，可切换最近交易日。</span>
        </div>
        <div className="state-block error-box">
          <strong>error</strong>
          <br />
          <span>503001 数据源不可用，可点击重试。</span>
        </div>
        <div className="state-block delayed-box">
          <strong>data delayed</strong>
          <br />
          <span>盘中源延迟 90s，历史数据已就绪。</span>
        </div>
      </div>
    </section>
  );
}

declare global {
  interface Window {
    __wealthToastTimer?: number;
  }
}
