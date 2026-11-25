import { useEffect, useRef, useState } from "react";

import { fetchStockNineTurnSeries } from "../../features/nine-turn/api/nineTurnApiClient";
import type { NineTurnPeriod } from "../../features/nine-turn/api/nineTurnApiTypes";
import { DAILY_CHART_PAGE_SIZE } from "../../shared/charts/dailyChartRequestLimits";
import { useDetailChartIndicatorControls } from "../../shared/charts/detail-workspace/useDetailChartIndicatorControls";
import type { NineTurnSeriesLoader } from "../../features/nine-turn/controller/useNineTurnSeriesRegistry";
import { useNineTurnDisplayControl } from "../../features/nine-turn/controller/useNineTurnDisplayControl";
import { useNineTurnSeriesRegistry } from "../../features/nine-turn/controller/useNineTurnSeriesRegistry";
import { idleNineTurnLayer } from "../../features/nine-turn/model/nineTurnAdapter";
import type { NineTurnLayerViewModel } from "../../features/nine-turn/model/nineTurnTypes";
import { fetchStockDetailKline, fetchStockDetailPageInit } from "../../features/stock-detail/api/stockDetailApiClient";
import { fetchStockMinuteChart } from "../../features/stock-detail/api/stockMinuteApiClient";
import { buildStockMinuteChartViewModel, minuteFrequencyFromPeriodKey } from "../../features/stock-detail/api/stockMinuteViewModelAdapter";
import { useMajorIndexTickers } from "../../features/major-indices/model/useMajorIndexTickers";
import { buildStockDailyNineTurnLayer, buildStockDetailViewModel } from "../../features/stock-detail/api/stockDetailViewModelAdapter";
import { StockChartWorkspace } from "../../features/stock-detail/chart/StockChartWorkspace";
import { StockMinuteChartWorkspace } from "../../features/stock-detail/chart/StockMinuteChartWorkspace";
import { useStockDailyHistory, type StockDailyHistorySeed } from "../../features/stock-detail/controller/useStockDailyHistory";
import { useStockPeriodKline } from "../../features/stock-detail/controller/useStockPeriodKline";
import { StockBreadcrumbActionBar } from "../../features/stock-detail/layout/StockBreadcrumbActionBar";
import { StockChartToolbar } from "../../features/stock-detail/layout/StockChartToolbar";
import { StockInfoRail } from "../../features/stock-detail/sidebar/StockInfoRail";
import { StockDetailToast } from "../../features/stock-detail/ui/StockDetailToast";
import { StockRuleEntry } from "../../features/trading-assistant/ui/StockRuleEntry";
import { useStockTrendChannel } from "../../features/stock-detail/trend-channel/controller/useStockTrendChannel";
import { useStockWatchlistGroups } from "../../features/watchlist/model/useStockWatchlistGroups";
import {
  buildIndexDetailPath,
  navigateWealth,
  resolveTopMarketNavPath,
  returnToWealthOverview,
} from "../../app/routes/routerState";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import type { StockDetailViewModel, StockPeriodKey } from "../../features/stock-detail/model/stockDetailTypes";
import type { StockDetailPageInitResponseDto } from "../../features/stock-detail/api/stockDetailApiTypes";
import type { StockMinuteChartViewModel } from "../../features/stock-detail/api/stockMinuteViewModelAdapter";
import "./stock-detail-page.css";

interface StockDetailPageProps {
  tsCode: string;
  tradeDate?: string;
  debug?: 1;
}

interface StockDetailLoad {
  requestKey: string;
  state: "loading" | "ready" | "empty" | "error";
  pageInit?: StockDetailPageInitResponseDto;
  viewModel?: StockDetailViewModel;
  historySeed?: StockDailyHistorySeed;
  dailyNineTurnLayer?: NineTurnLayerViewModel;
  errorMessage?: string;
}

const EMPTY_NINE_TURN_PERIODS: NineTurnPeriod[] = [];
const DAILY_NINE_TURN_PERIODS: NineTurnPeriod[] = ["day"];
const loadStockNineTurnSeries: NineTurnSeriesLoader = (request, options) => {
  if (request.subjectType !== "stock" || request.period !== "day") {
    throw new Error("股票九转请求周期不符合产品合同。");
  }
  return fetchStockNineTurnSeries({
    endDate: request.endDate,
    limit: request.limit,
    period: "day",
    tsCode: request.tsCode,
  }, options);
};

export function StockDetailPage({ tsCode, tradeDate, debug }: StockDetailPageProps) {
  const requestKey = JSON.stringify([tsCode, tradeDate, debug]);
  const activeRequestKey = useRef(requestKey);
  activeRequestKey.current = requestKey;
  const indicatorControls = useDetailChartIndicatorControls(tsCode);
  const [load, setLoad] = useState<StockDetailLoad | null>(null);
  const currentLoad = load?.requestKey === requestKey ? load : null;
  const activePageInit = currentLoad?.pageInit ?? null;
  const viewModel = currentLoad?.viewModel ?? null;
  const loadState = currentLoad?.state ?? "loading";
  const errorMessage = currentLoad?.errorMessage ?? "";
  const tickers = useMajorIndexTickers(activePageInit?.pageContext.tradeDate, activePageInit !== null);
  const [activePeriod, setActivePeriod] = useState<StockPeriodKey>("day");
  const stockPeriod = activePeriod === "week" || activePeriod === "month" ? activePeriod : null;
  const periodKline = useStockPeriodKline(tsCode, stockPeriod, activePageInit?.pageContext.tradeDate, debug);
  const periodData = periodKline.data;
  const [minuteChart, setMinuteChart] = useState<StockMinuteChartViewModel | null>(null);
  const [minuteLoadState, setMinuteLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [minuteError, setMinuteError] = useState("");
  const minuteCacheRef = useRef(new Map<string, StockMinuteChartViewModel>());
  const minuteControllerRef = useRef<AbortController | null>(null);
  const [toast, setToast] = useState("");
  const [ruleEntry, setRuleEntry] = useState<"PLAN" | "ALERT" | null>(null);
  useEffect(() => setRuleEntry(null), [requestKey]);
  const watchlist = useStockWatchlistGroups(tsCode, activePageInit?.capabilities.userActions.watchlist === true);
  useEffect(() => { if (watchlist.error) setToast(watchlist.error); }, [watchlist.error]);
  const trendChannel = useStockTrendChannel({
    enabled: loadState === "ready" && viewModel !== null && (activePageInit?.capabilities.supportsTrendChannel ?? false),
    endDate: activePageInit?.pageContext.tradeDate ?? null,
    tsCode,
  });
  const nineTurnRegistry = useNineTurnSeriesRegistry({
    dailyLimit: DAILY_CHART_PAGE_SIZE,
    endDate: activePageInit?.pageContext.tradeDate ?? null,
    load: loadStockNineTurnSeries,
    subjectType: "stock",
    supportedPeriods: activePageInit?.capabilities.nineTurnPeriods.includes("day")
      ? DAILY_NINE_TURN_PERIODS : EMPTY_NINE_TURN_PERIODS,
    supportsNineTurn: loadState === "ready" && viewModel !== null && (activePageInit?.capabilities.supportsNineTurn ?? false),
    tsCode,
  });
  const activeNineTurnPeriod = nineTurnPeriodFromStockPeriod(activePeriod);
  const dailyHistory = useStockDailyHistory(currentLoad?.historySeed ?? null, activePeriod === "day");
  const nineTurnCapabilities = activePageInit?.capabilities;
  const displayNineTurnPeriod = stockPeriod ?? activeNineTurnPeriod;
  const nineTurnControl = useNineTurnDisplayControl(tsCode,
    displayNineTurnPeriod !== null && nineTurnCapabilities?.supportsNineTurn === true
      && nineTurnCapabilities.nineTurnPeriods.includes(displayNineTurnPeriod));
  const dailyNineTurnLayer = activeNineTurnPeriod === "day" ? currentLoad?.dailyNineTurnLayer : undefined;
  const nineTurnLayer = dailyNineTurnLayer ?? nineTurnRegistry.stateFor("day");

  useEffect(() => {
    if (loadState !== "ready" || activeNineTurnPeriod !== "day" || dailyNineTurnLayer) return;
    void nineTurnRegistry.ensure("day");
  }, [activeNineTurnPeriod, dailyNineTurnLayer, loadState, nineTurnRegistry.ensure]);

  useEffect(() => {
    const controller = new AbortController();
    const isCurrent = () => !controller.signal.aborted && activeRequestKey.current === requestKey;

    setLoad({ requestKey, state: "loading" });
    setActivePeriod("day");
    setMinuteChart(null);
    setMinuteLoadState("idle");
    setMinuteError("");
    minuteCacheRef.current.clear();
    minuteControllerRef.current?.abort();

    async function loadStockDetail() {
      let pageInit: StockDetailPageInitResponseDto | undefined;
      try {
        pageInit = await fetchStockDetailPageInit({ tsCode, tradeDate, debug }, { signal: controller.signal });
        if (!isCurrent()) return;
        setLoad({ requestKey, state: "loading", pageInit });
        const anchor = pageInit.pageContext.tradeDate;
        const local = !("quote" in pageInit);
        const kline = await fetchStockDetailKline(
          {
            tsCode,
            period: "day",
            adjustment: "forward",
            tradeDate: local ? anchor : undefined,
            endDate: anchor,
            limit: DAILY_CHART_PAGE_SIZE,
            debug,
          },
          { signal: controller.signal },
        );
        if (!isCurrent()) return;
        let dailyNineTurnLayer: NineTurnLayerViewModel | undefined;
        if (local) {
          if (!Array.isArray(kline.nineTurnMarkers)) throw new Error("股票日线回包缺少九转标记");
          dailyNineTurnLayer = buildStockDailyNineTurnLayer(kline.nineTurnMarkers);
        }
        if (kline.bars.length === 0 || (local && kline.dataStatus.status === "EMPTY")) {
          setLoad({ requestKey, state: "empty", pageInit });
          return;
        }
        const nextViewModel = buildStockDetailViewModel(pageInit, kline);
        const historySeed = local && kline.meta.nextEndDate ? {
          tsCode, tradeDate: anchor, nextEndDate: kline.meta.nextEndDate,
          candles: nextViewModel.chart.candles, debug,
        } : undefined;
        setActivePeriod(nextViewModel.activePeriod);
        setLoad({ requestKey, state: "ready", pageInit, viewModel: nextViewModel, historySeed, dailyNineTurnLayer });
      } catch (error) {
        if (!isCurrent()) return;
        setLoad({
          requestKey, state: "error", pageInit,
          errorMessage: error instanceof Error ? error.message : "股票详情数据加载失败",
        });
      }
    }

    void loadStockDetail();

    return () => {
      controller.abort();
      minuteControllerRef.current?.abort();
    };
  }, [requestKey, tsCode, tradeDate, debug]);

  async function handlePeriodChange(period: StockPeriodKey) {
    setActivePeriod(period);
    if (period === "week" || period === "month") {
      minuteControllerRef.current?.abort();
      return;
    }
    if (period === "day") {
      minuteControllerRef.current?.abort();
      setMinuteChart(null);
      setMinuteLoadState("idle");
      setMinuteError("");
      return;
    }

    const frequency = minuteFrequencyFromPeriodKey(period);
    if (!frequency || !activePageInit?.capabilities.supportsMinute) return;
    const endDate = activePageInit.pageContext.tradeDate;
    const cacheKey = `${tsCode}|${endDate}|${frequency}`;
    minuteControllerRef.current?.abort();
    const cached = minuteCacheRef.current.get(cacheKey);
    if (cached) {
      setMinuteChart(cached);
      setMinuteLoadState("ready");
      setMinuteError("");
      return;
    }

    const controller = new AbortController();
    minuteControllerRef.current = controller;
    setMinuteChart(null);
    setMinuteLoadState("loading");
    setMinuteError("");

    const params = {
      tsCode,
      freq: frequency,
      endDate,
      limit: 500,
    } as const;
    try {
      const response = await fetchStockMinuteChart(params, { signal: controller.signal });
      if (controller.signal.aborted || activeRequestKey.current !== requestKey) return;
      const nextMinuteChart = buildStockMinuteChartViewModel(response);
      minuteCacheRef.current.set(cacheKey, nextMinuteChart);
      setMinuteChart(nextMinuteChart);
      setMinuteLoadState("ready");
    } catch (error) {
      if (controller.signal.aborted || activeRequestKey.current !== requestKey) return;
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

  if (loadState !== "ready" || viewModel === null || activePageInit === null) {
    return (
      <div className="stock-detail-app">
        <TopMarketBar
          activeNav="market"
          onNavigate={handleTopNavigate}
          onTickerSelect={openIndexDetail}
          tickers={tickers}
        />
        <section className="stock-detail-state-panel" aria-label={loadState === "empty" ? "暂无行情信息" : loadState === "loading" ? "股票详情加载中" : "股票详情加载失败"}>
          <div className="state-title">{loadState === "empty" ? "暂无行情信息" : loadState === "loading" ? "正在加载股票详情" : "股票详情加载失败"}</div>
          {loadState !== "empty" && <div className="state-detail">{loadState === "loading" ? "正在读取真实行情数据，请稍候。" : errorMessage}</div>}
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
        tickers={tickers}
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
            history={dailyHistory}
            indicatorControls={indicatorControls}
            indicatorTabs={viewModel.indicatorTabs}
            nineTurnControl={nineTurnControl}
            nineTurnLayer={nineTurnLayer}
            onNineTurnRetry={() => {
              if (!dailyNineTurnLayer) void nineTurnRegistry.retry("day");
            }}
            onAction={showToast}
            onTrendSelect={() => {
              trendChannel.ensure();
              dailyHistory.ensureTrend();
            }}
            supportsTrendChannel={activePageInit?.capabilities.supportsTrendChannel ?? false}
            trend={trendChannel.data}
            tsCode={viewModel.stock.tsCode}
          />
        ) : stockPeriod ? (
          periodData?.dataStatus && periodData.candles.length > 0 ? (
            <StockChartWorkspace
              candles={periodData.candles}
              indicatorControls={indicatorControls}
              indicatorTabs={viewModel.indicatorTabs}
              nineTurnControl={nineTurnControl}
              nineTurnLayer={buildStockDailyNineTurnLayer(periodData.markers, stockPeriod)}
              onNineTurnRetry={periodKline.retry}
              onAction={showToast}
              onTrendSelect={() => undefined}
              supportsTrendChannel={false}
              trend={null}
              tsCode={viewModel.stock.tsCode}
              period={stockPeriod}
              tradeDate={activePageInit.pageContext.tradeDate}
              periodNote={periodData.dataStatus.status === "DELAYED" ? periodData.dataStatus.note : null}
              periodHistory={stockPeriod === "week" ? {
                phase: periodData.phase, onViewport: periodKline.onViewport, retry: periodKline.retry,
              } : undefined}
            />
          ) : (
            <section className="stock-detail-state-panel" role="status">
              <div className="state-title">{periodData?.dataStatus
                ? periodData.dataStatus.note ?? "暂无行情信息"
                : periodData?.error ?? "正在加载周期行情"}</div>
              {periodData?.phase === "error" ? <button type="button" onClick={periodKline.retry}>重试</button> : null}
            </section>
          )
        ) : (
          <StockMinuteChartWorkspace
            data={minuteChart}
            errorMessage={minuteError}
            indicatorControls={indicatorControls}
            loadState={minuteLoadState}
            nineTurnControl={nineTurnControl}
            nineTurnLayer={minuteChart?.nineTurnLayer ?? idleNineTurnLayer(activeNineTurnPeriod ?? "day")}
          />
        )}
        <StockInfoRail onAction={showToast} viewModel={viewModel} watchlist={watchlist}
          tradeDate={activePageInit.pageContext.tradeDate}
          onCreatePlan={activePageInit?.capabilities.userActions.tradePlan ? () => setRuleEntry("PLAN") : undefined}
          onCreateAlert={activePageInit?.capabilities.userActions.alert ? () => setRuleEntry("ALERT") : undefined} />
      </main>
      <StockDetailToast message={toast} />
      {ruleEntry && <StockRuleEntry key={tsCode} kind={ruleEntry} stock={{ tsCode, name: viewModel.stock.name }} onClose={() => setRuleEntry(null)} />}
    </div>
  );
}

function nineTurnPeriodFromStockPeriod(period: StockPeriodKey): NineTurnPeriod | null {
  if (period === "day") return "day";
  const frequency = minuteFrequencyFromPeriodKey(period);
  return frequency === null ? null : String(frequency) as NineTurnPeriod;
}
