import { useEffect, useMemo, useRef, useState } from "react";

import { fetchStockNineTurnSeries } from "../../features/nine-turn/api/nineTurnApiClient";
import type { NineTurnPeriod } from "../../features/nine-turn/api/nineTurnApiTypes";
import type { NineTurnSeriesLoader } from "../../features/nine-turn/controller/useNineTurnSeriesRegistry";
import { useNineTurnSeriesRegistry } from "../../features/nine-turn/controller/useNineTurnSeriesRegistry";
import { fetchStockDetailKline, fetchStockDetailPageInit } from "../../features/stock-detail/api/stockDetailApiClient";
import { fetchStockMinuteBars, fetchStockMinuteIndicators } from "../../features/stock-detail/api/stockMinuteApiClient";
import { buildStockMinuteChartViewModel, minuteFrequencyFromPeriodKey } from "../../features/stock-detail/api/stockMinuteViewModelAdapter";
import { getStockDetailViewModel } from "../../features/stock-detail/api/stockDetailMockAdapter";
import { buildStockDetailViewModel } from "../../features/stock-detail/api/stockDetailViewModelAdapter";
import { StockChartWorkspace } from "../../features/stock-detail/chart/StockChartWorkspace";
import { StockMinuteChartWorkspace } from "../../features/stock-detail/chart/StockMinuteChartWorkspace";
import { StockBreadcrumbActionBar } from "../../features/stock-detail/layout/StockBreadcrumbActionBar";
import { StockChartToolbar } from "../../features/stock-detail/layout/StockChartToolbar";
import { StockInfoRail } from "../../features/stock-detail/sidebar/StockInfoRail";
import { StockDetailToast } from "../../features/stock-detail/ui/StockDetailToast";
import { useStockTrendChannel } from "../../features/stock-detail/trend-channel/controller/useStockTrendChannel";
import { useStockWatchlist } from "../../features/watchlist/model/useStockWatchlist";
import {
  buildIndexDetailPath,
  navigateWealth,
  resolveTopMarketNavPath,
  returnToWealthOverview,
} from "../../app/routes/routerState";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import type { StockDetailViewModel, StockPeriodKey } from "../../features/stock-detail/model/stockDetailTypes";
import type { StockDetailPageInitResponseDto, StockMinuteFrequency } from "../../features/stock-detail/api/stockDetailApiTypes";
import type { StockMinuteChartViewModel } from "../../features/stock-detail/api/stockMinuteViewModelAdapter";
import "./stock-detail-page.css";

interface StockDetailPageProps {
  tsCode: string;
}

const EMPTY_NINE_TURN_PERIODS: NineTurnPeriod[] = [];
const loadStockNineTurnSeries: NineTurnSeriesLoader = (request, options) => {
  if (request.subjectType !== "stock" || !isStockNineTurnPeriod(request.period)) {
    throw new Error("股票九转请求周期不符合产品合同。");
  }
  return fetchStockNineTurnSeries({
    endDate: request.endDate,
    limit: request.limit,
    period: request.period,
    tsCode: request.tsCode,
  }, options);
};

export function StockDetailPage({ tsCode }: StockDetailPageProps) {
  const scaffoldViewModel = useMemo(() => getStockDetailViewModel(tsCode), [tsCode]);
  const [viewModel, setViewModel] = useState<StockDetailViewModel | null>(null);
  const [pageInit, setPageInit] = useState<StockDetailPageInitResponseDto | null>(null);
  const [activePeriod, setActivePeriod] = useState<StockPeriodKey>("day");
  const [minuteChart, setMinuteChart] = useState<StockMinuteChartViewModel | null>(null);
  const [minuteLoadState, setMinuteLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [minuteError, setMinuteError] = useState("");
  const minuteCacheRef = useRef(new Map<StockMinuteFrequency, StockMinuteChartViewModel>());
  const minuteControllerRef = useRef<AbortController | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState("");
  const activePageInit = pageInit?.stock.tsCode === tsCode ? pageInit : null;
  const watchlist = useStockWatchlist(tsCode, activePageInit?.capabilities.userActions.watchlist === true);
  useEffect(() => { if (watchlist.error) setToast(watchlist.error); }, [watchlist.error]);
  const trendChannel = useStockTrendChannel({
    enabled: activePageInit?.capabilities.supportsTrendChannel ?? false,
    endDate: activePageInit?.pageContext.tradeDate ?? null,
    tsCode,
  });
  const nineTurnRegistry = useNineTurnSeriesRegistry({
    endDate: activePageInit?.pageContext.tradeDate ?? null,
    load: loadStockNineTurnSeries,
    subjectType: "stock",
    supportedPeriods: activePageInit?.capabilities.nineTurnPeriods ?? EMPTY_NINE_TURN_PERIODS,
    supportsNineTurn: activePageInit?.capabilities.supportsNineTurn ?? false,
    tsCode,
  });
  const activeNineTurnPeriod = nineTurnPeriodFromStockPeriod(activePeriod);
  const nineTurnLayer = activeNineTurnPeriod === null
    ? nineTurnRegistry.stateFor("day")
    : nineTurnRegistry.stateFor(activeNineTurnPeriod);

  useEffect(() => {
    if (loadState !== "ready" || activeNineTurnPeriod === null) return;
    void nineTurnRegistry.ensure(activeNineTurnPeriod);
  }, [activeNineTurnPeriod, loadState, nineTurnRegistry.ensure]);

  useEffect(() => {
    const controller = new AbortController();
    const searchParams = new URLSearchParams(window.location.search);
    const tradeDate = searchParams.get("tradeDate") ?? undefined;
    const debug = searchParams.get("debug") === "1" ? 1 : undefined;

    setLoadState("loading");
    setErrorMessage("");
    setViewModel(null);
    setPageInit(null);
    setMinuteChart(null);
    setMinuteLoadState("idle");
    setMinuteError("");
    minuteCacheRef.current.clear();
    minuteControllerRef.current?.abort();

    async function loadStockDetail() {
      try {
        const pageInit = await fetchStockDetailPageInit({ tsCode, tradeDate, debug }, { signal: controller.signal });
        const kline = await fetchStockDetailKline(
          {
            tsCode,
            period: "day",
            adjustment: "forward",
            endDate: pageInit.pageContext.tradeDate,
            limit: 300,
            debug,
          },
          { signal: controller.signal },
        );
        const nextViewModel = buildStockDetailViewModel(pageInit, kline);
        setPageInit(pageInit);
        setViewModel(nextViewModel);
        setActivePeriod(nextViewModel.activePeriod);
        setLoadState("ready");
      } catch (error) {
        if (controller.signal.aborted) return;
        setErrorMessage(error instanceof Error ? error.message : "股票详情数据加载失败");
        setLoadState("error");
      }
    }

    void loadStockDetail();

    return () => {
      controller.abort();
      minuteControllerRef.current?.abort();
    };
  }, [tsCode]);

  async function handlePeriodChange(period: StockPeriodKey) {
    setActivePeriod(period);
    if (period === "day") {
      minuteControllerRef.current?.abort();
      setMinuteChart(null);
      setMinuteLoadState("idle");
      setMinuteError("");
      return;
    }

    const frequency = minuteFrequencyFromPeriodKey(period);
    if (!frequency || !pageInit?.capabilities.supportsMinute) return;
    const cached = minuteCacheRef.current.get(frequency);
    if (cached) {
      setMinuteChart(cached);
      setMinuteLoadState("ready");
      setMinuteError("");
      return;
    }

    minuteControllerRef.current?.abort();
    const controller = new AbortController();
    minuteControllerRef.current = controller;
    setMinuteChart(null);
    setMinuteLoadState("loading");
    setMinuteError("");

    const params = {
      tsCode,
      freq: frequency,
      endDate: pageInit.pageContext.tradeDate,
      limit: 500,
    } as const;
    try {
      const [bars, indicators] = await Promise.all([
        fetchStockMinuteBars(params, { signal: controller.signal }),
        fetchStockMinuteIndicators(params, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      const nextMinuteChart = buildStockMinuteChartViewModel(bars, indicators);
      minuteCacheRef.current.set(frequency, nextMinuteChart);
      setMinuteChart(nextMinuteChart);
      setMinuteLoadState("ready");
    } catch (error) {
      if (controller.signal.aborted) return;
      setMinuteLoadState("error");
      setMinuteError(error instanceof Error ? error.message : "分钟数据加载失败");
    }
  }

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 1800);
  }

  function handleTopNavigate(target: TopMarketNavKey) {
    const path = resolveTopMarketNavPath(target);
    if (path) {
      navigateWealth(path);
      return;
    }
    showToast("该入口暂未开放");
  }

  function openIndexDetail(indexCode: string) {
    navigateWealth(buildIndexDetailPath(indexCode));
  }

  if (loadState !== "ready" || viewModel === null) {
    return (
      <div className="stock-detail-app">
        <TopMarketBar
          activeNav="market"
          onNavigate={handleTopNavigate}
          onTickerSelect={openIndexDetail}
          tickers={scaffoldViewModel.topMarketTickers}
        />
        <section className="stock-detail-state-panel" aria-label={loadState === "loading" ? "股票详情加载中" : "股票详情加载失败"}>
          <div className="state-title">{loadState === "loading" ? "正在加载股票详情" : "股票详情加载失败"}</div>
          <div className="state-detail">{loadState === "loading" ? "正在读取真实行情数据，请稍候。" : errorMessage}</div>
        </section>
        <StockDetailToast message={toast} />
      </div>
    );
  }

  return (
    <div className="stock-detail-app">
      <TopMarketBar
        activeNav="market"
        onNavigate={handleTopNavigate}
        onTickerSelect={openIndexDetail}
        tickers={viewModel.topMarketTickers}
      />
      <StockBreadcrumbActionBar onReturnHome={returnToWealthOverview} stock={viewModel.stock} />
      <StockChartToolbar
        activePeriod={activePeriod}
        onAction={showToast}
        onPeriodChange={handlePeriodChange}
        periods={viewModel.periods}
        stock={viewModel.stock}
      />
      <main className="stock-detail-main-content" aria-label="MainContent">
        {activePeriod === "day" ? (
          <StockChartWorkspace
            candles={viewModel.chart.candles}
            indicatorTabs={viewModel.indicatorTabs}
            nineTurnLayer={nineTurnLayer}
            onNineTurnRetry={() => {
              if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
            }}
            onAction={showToast}
            onTrendSelect={trendChannel.ensure}
            supportsTrendChannel={activePageInit?.capabilities.supportsTrendChannel ?? false}
            trend={trendChannel.data}
            tsCode={viewModel.stock.tsCode}
          />
        ) : (
          <StockMinuteChartWorkspace
            data={minuteChart}
            errorMessage={minuteError}
            loadState={minuteLoadState}
            nineTurnLayer={nineTurnLayer}
            onNineTurnRetry={() => {
              if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
            }}
          />
        )}
        <StockInfoRail onAction={showToast} viewModel={viewModel} watchlistState={watchlist.status} onAddToWatchlist={() => void watchlist.add()} />
      </main>
      <StockDetailToast message={toast} />
    </div>
  );
}

function nineTurnPeriodFromStockPeriod(period: StockPeriodKey): NineTurnPeriod | null {
  if (period === "day") return "day";
  const frequency = minuteFrequencyFromPeriodKey(period);
  return frequency === null ? null : String(frequency) as NineTurnPeriod;
}

function isStockNineTurnPeriod(
  period: NineTurnPeriod,
): period is Extract<NineTurnPeriod, "day" | "30" | "60" | "90" | "120"> {
  return period === "day" || period === "30" || period === "60" || period === "90" || period === "120";
}
