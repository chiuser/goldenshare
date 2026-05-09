import { useEffect, useMemo, useState } from "react";
import { marketOverviewModuleSources } from "../../features/market-overview/api/moduleSources";
import { fetchMarketOverviewMock } from "../../features/market-overview/api/marketOverviewMockAdapter";
import type { MarketOverview } from "../../features/market-overview/api/marketOverviewTypes";
import { MarketBreadthPanel } from "../../features/market-overview/breadth/MarketBreadthPanel";
import {
  buildBreadthViewModelFromApi,
  buildBreadthViewModelFromMock,
  type MarketBreadthViewModel,
} from "../../features/market-overview/breadth/api/marketBreadthAdapter";
import { fetchMarketBreadth, type BreadthDebugInfo } from "../../features/market-overview/breadth/api/marketBreadthApi";
import { MajorIndexPanel } from "../../features/market-overview/indices/MajorIndexPanel";
import {
  buildMajorIndicesViewModelFromApi,
  buildMajorIndicesViewModelFromMock,
  type MarketMajorIndicesViewModel,
} from "../../features/market-overview/indices/api/marketMajorIndicesAdapter";
import { fetchMarketMajorIndices, type MajorIndicesDebugInfo } from "../../features/market-overview/indices/api/marketMajorIndicesApi";
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
import { buildSummaryViewModelFromApi, buildSummaryViewModelFromMock, type MarketSummaryViewModel } from "../../features/market-overview/summary/api/marketSummaryAdapter";
import { fetchMarketSummary, type SummaryDebugInfo } from "../../features/market-overview/summary/api/marketSummaryApi";
import { TurnoverOverviewPanel } from "../../features/market-overview/turnover/TurnoverOverviewPanel";
import { SkeletonBlock } from "../../shared/ui/SkeletonBlock";
import "./market-overview-page.css";

const SUMMARY_FETCH_TIMEOUT_MS = 5000;
const MAJOR_INDICES_FETCH_TIMEOUT_MS = 5000;
const BREADTH_FETCH_TIMEOUT_MS = 5000;

export function MarketOverviewPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [summary, setSummary] = useState<MarketSummaryViewModel | null>(null);
  const [summaryViewState, setSummaryViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.summary === "real" ? "loading" : "ready",
  );
  const [summaryErrorMessage, setSummaryErrorMessage] = useState<string | null>(null);
  const [summaryDebugInfo, setSummaryDebugInfo] = useState<SummaryDebugInfo | null>(null);
  const [majorIndices, setMajorIndices] = useState<MarketMajorIndicesViewModel | null>(null);
  const [majorIndicesViewState, setMajorIndicesViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.majorIndices === "real" ? "loading" : "ready",
  );
  const [majorIndicesErrorMessage, setMajorIndicesErrorMessage] = useState<string | null>(null);
  const [majorIndicesDebugInfo, setMajorIndicesDebugInfo] = useState<MajorIndicesDebugInfo | null>(null);
  const [breadth, setBreadth] = useState<MarketBreadthViewModel | null>(null);
  const [breadthViewState, setBreadthViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.breadth === "real" ? "loading" : "ready",
  );
  const [breadthErrorMessage, setBreadthErrorMessage] = useState<string | null>(null);
  const [breadthDebugInfo, setBreadthDebugInfo] = useState<BreadthDebugInfo | null>(null);
  const [toast, setToast] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const pageDebugEnabled = useMemo(() => {
    if (!import.meta.env.DEV) return false;
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("debug") === "1";
  }, []);
  const overviewDebugInfo = useMemo(() => {
    if (!pageDebugEnabled) return null;
    const moduleItems = [
      ...(summaryDebugInfo?.modules ?? []),
      ...(majorIndicesDebugInfo?.modules ?? []),
      ...(breadthDebugInfo?.modules ?? []),
    ];
    const exceptionItems = [
      ...(summaryDebugInfo?.exceptions ?? []),
      ...(majorIndicesDebugInfo?.exceptions ?? []),
      ...(breadthDebugInfo?.exceptions ?? []),
    ];
    if (!moduleItems.length && !exceptionItems.length) return null;
    return { modules: moduleItems, exceptions: exceptionItems };
  }, [pageDebugEnabled, summaryDebugInfo, majorIndicesDebugInfo, breadthDebugInfo]);

  useEffect(() => {
    fetchMarketOverviewMock().then((response) => {
      setOverview(response.data);
      if (marketOverviewModuleSources.summary === "mock") {
        setSummary(buildSummaryViewModelFromMock(response.data));
        setSummaryViewState("ready");
      } else {
        setSummary(null);
        setSummaryViewState("loading");
        setSummaryErrorMessage(null);
      }
      if (marketOverviewModuleSources.majorIndices === "mock") {
        setMajorIndices(buildMajorIndicesViewModelFromMock(response.data.indices));
        setMajorIndicesViewState("ready");
      } else {
        setMajorIndices(null);
        setMajorIndicesViewState("loading");
        setMajorIndicesErrorMessage(null);
      }
      if (marketOverviewModuleSources.breadth === "mock") {
        setBreadth(buildBreadthViewModelFromMock(response.data));
        setBreadthViewState("ready");
      } else {
        setBreadth(null);
        setBreadthViewState("loading");
        setBreadthErrorMessage(null);
      }
    });
  }, []);

  useEffect(() => {
    if (!overview) return;
    if (marketOverviewModuleSources.summary !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setSummary(null);
    setSummaryViewState("loading");
    setSummaryErrorMessage(null);
    setSummaryDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), SUMMARY_FETCH_TIMEOUT_MS);

    fetchMarketSummary(
      { market: "CN_A", debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setSummary(buildSummaryViewModelFromApi(payload));
          setSummaryViewState("ready");
          setSummaryErrorMessage(null);
          setSummaryDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout ? `请求超时：/api/v1/wealth/market/summary` : error instanceof Error ? error.message : "客观总结加载失败";
          setSummaryDebugInfo(null);
          setSummary(null);
          setSummaryViewState("error");
          setSummaryErrorMessage(message);
          showToast(`客观总结模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageDebugEnabled]);

  useEffect(() => {
    if (!overview) return;
    if (marketOverviewModuleSources.breadth !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setBreadth(null);
    setBreadthViewState("loading");
    setBreadthErrorMessage(null);
    setBreadthDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), BREADTH_FETCH_TIMEOUT_MS);

    fetchMarketBreadth(
      { market: "CN_A", debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setBreadth(buildBreadthViewModelFromApi(payload));
          setBreadthViewState("ready");
          setBreadthErrorMessage(null);
          setBreadthDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout ? `请求超时：/api/v1/wealth/market/breadth` : error instanceof Error ? error.message : "涨跌分布加载失败";
          setBreadth(null);
          setBreadthViewState("error");
          setBreadthErrorMessage(message);
          setBreadthDebugInfo(null);
          showToast(`涨跌分布模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageDebugEnabled]);

  useEffect(() => {
    if (!overview) return;
    if (marketOverviewModuleSources.majorIndices !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setMajorIndices(null);
    setMajorIndicesViewState("loading");
    setMajorIndicesErrorMessage(null);
    setMajorIndicesDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), MAJOR_INDICES_FETCH_TIMEOUT_MS);

    fetchMarketMajorIndices(
      { market: "CN_A", debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setMajorIndices(buildMajorIndicesViewModelFromApi(payload));
          setMajorIndicesViewState("ready");
          setMajorIndicesErrorMessage(null);
          setMajorIndicesDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/major-indices`
            : error instanceof Error
              ? error.message
              : "主要指数加载失败";
          setMajorIndices(null);
          setMajorIndicesViewState("error");
          setMajorIndicesErrorMessage(message);
          setMajorIndicesDebugInfo(null);
          showToast(`主要指数模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageDebugEnabled]);

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
            <MarketSummaryPanel
              viewState={summaryViewState}
              facts={summary?.facts}
              layoutVariant={summary?.layoutVariant}
              statusLabel={summary?.statusLabel}
              statusTone={summary?.statusTone}
              textContent={summary?.textContent}
              textTitle={summary?.textTitle}
              errorMessage={summaryErrorMessage ?? undefined}
            />
            <MajorIndexPanel
              viewState={majorIndicesViewState}
              indices={majorIndices?.indices}
              errorMessage={majorIndicesErrorMessage ?? undefined}
              onAction={showToast}
            />
          </div>
          {overviewDebugInfo ? <OverviewDebugPanel debugInfo={overviewDebugInfo} /> : null}
          <div className="row-three">
            <MarketBreadthPanel
              viewState={breadthViewState}
              metrics={breadth?.metrics}
              chartsByRange={breadth?.chartsByRange}
              errorMessage={breadthErrorMessage ?? undefined}
            />
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

interface OverviewDebugInfo {
  modules: Array<{
    moduleKey: string;
    expectedTradeDate: string;
    observedTradeDate?: string | null;
    lagDays?: number | null;
    status: string;
    note?: string | null;
  }>;
  exceptions: Array<{
    module: string;
    code: string;
    severity: "info" | "warn" | "error";
    message: string;
  }>;
}

function OverviewDebugPanel({ debugInfo }: { debugInfo: OverviewDebugInfo }) {
  return (
    <section className="panel summary-debug-panel" aria-label="页面调试信息">
      <div className="section-header">
        <div className="section-title">页面调试信息（本地 DEV）</div>
      </div>
      <div className="summary-debug-grid">
        {debugInfo.modules.map((module) => (
          <div className="summary-debug-card" key={module.moduleKey}>
            <div className="summary-debug-title">{module.moduleKey}</div>
            <div className="summary-debug-line">expectedTradeDate: {module.expectedTradeDate}</div>
            <div className="summary-debug-line">observedTradeDate: {module.observedTradeDate ?? "-"}</div>
            <div className="summary-debug-line">lagDays: {module.lagDays ?? "-"}</div>
            <div className="summary-debug-line">status: {module.status}</div>
            <div className="summary-debug-line">note: {module.note ?? "-"}</div>
          </div>
        ))}
      </div>
      {debugInfo.exceptions.length ? (
        <div className="summary-debug-exceptions">
          {debugInfo.exceptions.map((exception, index) => (
            <div className="summary-debug-line" key={`${exception.module}-${exception.code}-${index}`}>
              [{exception.severity}] {exception.module} / {exception.code} - {exception.message}
            </div>
          ))}
        </div>
      ) : (
        <div className="summary-debug-line summary-debug-empty">exceptions: []</div>
      )}
    </section>
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
